"""Lot 3 — mesure du contexte : ce que pèse un envoi, ce que le modèle peut tenir."""
import json
from unittest import mock

import requests

from api import budget, views

from .socle import Base, _client_claude, _spec_complete

__all__ = ['BudgetContexteTests']


class BudgetContexteTests(Base):

    def setUp(self):
        super().setUp()
        self.alice = self.client_de('alice')
        self.corps = {'provider': 'claude', 'api_key': 'cle-de-alice',
                      'messages': [{'role': 'user', 'content': 'Une boutique'}], 'app_spec': {'name': 'B'}}

    def estimer(self, **corps):
        resp = self.alice.post('/api/chat/estimate/', {**self.corps, **corps}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()['context']

    # ── Table des modèles ─────────────────────────────────────────────────────

    def test_la_liste_des_modeles_est_servie_par_l_api(self):
        resp = self.alice.get('/api/models/')
        self.assertEqual(resp.status_code, 200)
        catalogue = resp.json()
        self.assertEqual(set(catalogue['providers']), {'claude', 'mistral'})
        for fournisseur in catalogue['providers'].values():
            ids = [m['id'] for m in fournisseur['models']]
            self.assertIn(fournisseur['default'], ids)
            for m in fournisseur['models']:
                self.assertEqual(set(m), {'id', 'label', 'context_window', 'max_output'})
                self.assertGreater(m['context_window'], m['max_output'])
        self.assertEqual(catalogue['lot_budget_tokens'], budget.LOT_BUDGET_JETONS)
        self.assertEqual(self.client_de('alice', azp='lab-admin').get('/api/models/').status_code, 403)

    def test_seuil_par_modele(self):
        petit = self.estimer(provider='mistral', model='mistral-small-latest')
        grand = self.estimer(provider='claude', model='claude-sonnet-4-6')
        self.assertEqual((petit['context_window'], grand['context_window']), (32_000, 1_000_000))
        self.assertEqual(petit['available_tokens'], 32_000 - 4096 - budget.MARGE_JETONS)
        self.assertGreater(petit['ratio'], grand['ratio'])
        # Sans modèle : celui par défaut du fournisseur. Ancien identifiant : reconnu. Inconnu : prudence.
        self.assertEqual(self.estimer(model='')['model'], 'claude-sonnet-4-6')
        self.assertEqual(self.estimer(provider='mistral', model=None)['model'], 'mistral-small-latest')
        self.assertEqual(budget.modele('claude', 'claude-haiku-4-5-20251001')['context_window'], 200_000)
        self.assertEqual(self.estimer(model='modele-inconnu')['context_window'], 32_000)
        # Un modèle d'un autre fournisseur n'emprunte pas sa fenêtre.
        self.assertEqual(self.estimer(provider='mistral', model='claude-sonnet-4-6')['context_window'], 32_000)

    # ── Estimation ────────────────────────────────────────────────────────────

    def test_estimation_croissante_avec_la_spec_et_la_conversation(self):
        vide = self.estimer(app_spec={})
        petite = self.estimer(app_spec=_spec_complete())
        grosse = _spec_complete()
        grosse['data_models'] += [{'name': f'Modele{i}', 'fields': [{'name': 'champ', 'type': 'string'}]} for i in range(50)]
        grande = self.estimer(app_spec=grosse)
        self.assertLess(vide['spec_tokens'], petite['spec_tokens'])
        self.assertLess(petite['spec_tokens'], grande['spec_tokens'])
        self.assertLess(petite['estimated_tokens'], grande['estimated_tokens'])
        self.assertEqual(petite['estimated_tokens'], petite['system_tokens'] + petite['history_tokens'])
        bavarde = self.estimer(messages=[{'role': 'user', 'content': 'x' * 3000}])
        self.assertEqual(bavarde['history_tokens'], 1000)
        self.assertEqual(set(vide), {'model', 'provider', 'context_window', 'reserved_output_tokens', 'available_tokens',
                                     'system_tokens', 'spec_tokens', 'history_tokens', 'estimated_tokens', 'ratio',
                                     'fits', 'messages_sent', 'messages_dropped'})

    def test_l_estimation_n_appelle_personne_et_ne_demande_pas_de_cle(self):
        corps = dict(self.corps)
        corps.pop('api_key')
        with mock.patch('anthropic.Anthropic', side_effect=AssertionError('appel')), \
                mock.patch.object(views.http_requests, 'post', side_effect=AssertionError('appel')), \
                mock.patch('socket.socket', side_effect=AssertionError('réseau')):
            resp = self.alice.post('/api/chat/estimate/', corps, format='json')
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json()['context']['fits'])
            self.assertEqual(budget.estimer_jetons('é' * 3), 2)

    def test_la_spec_part_sous_forme_compacte_et_sans_la_conversation(self):
        spec = {**_spec_complete(), 'id': 7, 'chat_history': [{'role': 'user', 'content': 'CONFIDENTIEL-HISTORIQUE',
                                                               'spec_patch': {'set_meta': {'name': 'PATCH-JOINT'}}}]}
        for prompt in (views._build_system_prompt(spec), views._build_patch_system_prompt(spec)):
            self.assertIn('"name": "Boutique"', prompt)
            self.assertIn('"endpoint_group_names": ["Produits"]', prompt)   # liens par nom
            self.assertNotIn('endpoint_group_ids', prompt)
            self.assertNotIn('chat_history', prompt)
            self.assertIn(views._spec_compacte(spec), prompt)
        compacte = views._spec_compacte(spec)
        self.assertNotIn('\n', compacte)                                   # plus d'indentation
        self.assertLess(len(compacte), len(json.dumps(spec, ensure_ascii=False, indent=2)) * 0.6)
        self.assertEqual(views._spec_compacte(None), '{}')
        # Par l'API : la conversation jointe à la spec ne pèse rien et ne part pas.
        sans = self.estimer(app_spec=_spec_complete())
        avec = self.estimer(app_spec={**_spec_complete(), 'chat_history': [{'role': 'user', 'content': 'x' * 30000}]})
        self.assertEqual(avec['estimated_tokens'], sans['estimated_tokens'])
        client = _client_claude('Bien.')
        with mock.patch('anthropic.Anthropic', return_value=client):
            self.alice.post('/api/chat/', {**self.corps, 'app_spec': spec}, format='json')
        envoye = client.messages.stream.call_args.kwargs
        self.assertNotIn('CONFIDENTIEL-HISTORIQUE', envoye['system'])
        self.assertNotIn('PATCH-JOINT', json.dumps(envoye, default=str))

    # ── Historique borné ──────────────────────────────────────────────────────

    def _conversation(self, echanges, taille=30):
        msgs = []
        for i in range(echanges):
            msgs += [{'role': 'user', 'content': f'question {i} ' + 'q' * taille, 'applied': 'merged'},
                     {'role': 'assistant', 'content': f'réponse {i} ' + 'r' * taille, 'spec_patch': {'pages': []}}]
        return msgs + [{'role': 'user', 'content': 'LA DERNIÈRE QUESTION'}]

    def test_historique_tronque_sans_perdre_le_dernier_message(self):
        client = _client_claude('Bien.')
        with mock.patch('anthropic.Anthropic', return_value=client):
            resp = self.alice.post('/api/chat/', {**self.corps, 'messages': self._conversation(40)}, format='json')
        self.assertEqual(resp.status_code, 200)
        envoyes = client.messages.stream.call_args.kwargs['messages']
        self.assertLessEqual(len(envoyes), budget.HISTORIQUE_MAX_MESSAGES)
        self.assertEqual(envoyes[-1], {'role': 'user', 'content': 'LA DERNIÈRE QUESTION'})
        self.assertEqual(envoyes[0]['role'], 'user')
        # Les plus récents sont gardés, dans l'ordre, sans rien d'autre que rôle et texte.
        self.assertTrue(envoyes[-2]['content'].startswith('réponse 39'))
        self.assertTrue(all(set(m) == {'role', 'content'} for m in envoyes))
        contexte = resp.json()['context']
        self.assertEqual((contexte['messages_sent'], contexte['messages_dropped']), (len(envoyes), 81 - len(envoyes)))

    def test_petite_fenetre_on_garde_ce_qui_tient_en_partant_de_la_fin(self):
        messages = self._conversation(8, taille=9000)        # ≈ 3 000 jetons par message
        contexte = self.estimer(provider='mistral', model='mistral-small-latest', messages=messages, app_spec={})
        self.assertTrue(contexte['fits'])
        self.assertGreater(contexte['messages_dropped'], 0)
        self.assertLess(contexte['messages_sent'], 17)
        self.assertLessEqual(contexte['estimated_tokens'], contexte['available_tokens'])
        gardes, retires = budget.borner(budget.nettoyer(messages), 7000)
        self.assertEqual(([m['content'][:10] for m in gardes], retires), (['question 7', 'réponse 7 ', 'LA DERNIÈR'], 14))
        # Budget nul : le dernier message part quand même, seul.
        self.assertEqual(budget.borner(budget.nettoyer(messages), 0), ([{'role': 'user', 'content': 'LA DERNIÈRE QUESTION'}], 16))
        self.assertEqual(budget.borner([], 100), ([], 0))
        self.assertEqual(budget.nettoyer([None, {'role': 'system', 'content': 'x'}, {'role': 'user', 'content': '  '},
                                          {'role': 'user', 'content': 'ok', 'api_key': 'k'}, 'texte']),
                         [{'role': 'user', 'content': 'ok'}])
        self.assertEqual(budget.nettoyer('pas une liste'), [])

    # ── Refus avant l'appel ───────────────────────────────────────────────────

    def test_refus_avant_appel_quand_le_budget_est_depasse(self):
        enorme = _spec_complete()
        enorme['data_models'] = [{'name': f'M{i}', 'description': 'd' * 400, 'fields': []} for i in range(300)]
        corps = {**self.corps, 'provider': 'mistral', 'model': 'mistral-small-latest', 'app_spec': enorme}
        with mock.patch('anthropic.Anthropic') as anthropic_ctor, mock.patch.object(views.http_requests, 'post') as post:
            resp = self.alice.post('/api/chat/', corps, format='json')
            self.assertEqual(resp.status_code, 413)
            anthropic_ctor.assert_not_called()
            post.assert_not_called()
        refus = resp.json()
        self.assertEqual(refus['code'], 'context_too_large')
        self.assertIn('mistral-small-latest', refus['error'])
        self.assertFalse(refus['context']['fits'])
        self.assertGreater(refus['context']['ratio'], 1)
        # La même spec tient dans une grande fenêtre : l'appel part.
        client = _client_claude('Bien.')
        with mock.patch('anthropic.Anthropic', return_value=client):
            resp = self.alice.post('/api/chat/', {**corps, 'provider': 'claude', 'model': 'claude-sonnet-4-6'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['context']['fits'])
        # Un dernier message plus gros que la fenêtre : refusé, pas tronqué.
        with mock.patch.object(views.http_requests, 'post') as post:
            resp = self.alice.post('/api/chat/', {**self.corps, 'provider': 'mistral',
                                                  'messages': [{'role': 'user', 'content': 'x' * 200_000}]}, format='json')
            self.assertEqual(resp.status_code, 413)
            post.assert_not_called()

    def test_sans_message_rien_ne_part(self):
        with mock.patch('anthropic.Anthropic') as ctor:
            for messages in ([], None, [{'role': 'user', 'content': ''}], 'texte'):
                resp = self.alice.post('/api/chat/', {**self.corps, 'messages': messages}, format='json')
                self.assertEqual(resp.status_code, 400)
            ctor.assert_not_called()

    def test_le_patch_n_est_pas_demande_s_il_ne_tient_pas(self):
        appel = mock.Mock(return_value='{"data_models": [{"name": "X"}]}')
        gros = [{'role': 'user', 'content': 'x' * 3 * 25_000}]
        with mock.patch.object(views, '_call_mistral_once', appel):
            patch, erreur = views._generate_patch('mistral', 'cle', 'mistral-small-latest', {}, gros, 'ok')
        self.assertIsNone(patch)
        self.assertIn('dépassent', erreur)
        appel.assert_not_called()

    # ── Erreur du fournisseur traduite ────────────────────────────────────────

    def test_erreur_contexte_trop_long_du_fournisseur_traduite(self):
        cas = [RuntimeError("Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
                            "'message': 'prompt is too long: 1200000 tokens > 1000000 maximum'}}"),
               RuntimeError('This model\'s maximum context length is 32000 tokens')]
        for erreur in cas:
            with self.subTest(erreur=str(erreur)[:40]), mock.patch('anthropic.Anthropic', side_effect=erreur):
                resp = self.alice.post('/api/chat/', self.corps, format='json')
                self.assertEqual(resp.status_code, 413)
                self.assertEqual(resp.json()['code'], 'context_too_large')
                self.assertNotIn('invalid_request_error', resp.json()['error'])
        http = requests.exceptions.HTTPError('400 Client Error')
        http.response = mock.Mock(text='{"message": "Prompt contains 40000 tokens, too large for model with 32000 maximum context length"}')
        with mock.patch.object(views.http_requests, 'post', side_effect=http):
            resp = self.alice.post('/api/chat/', {**self.corps, 'provider': 'mistral'}, format='json')
        self.assertEqual(resp.status_code, 413)
        # Toute autre panne reste une erreur de passerelle.
        with mock.patch('anthropic.Anthropic', side_effect=RuntimeError('clé refusée')):
            self.assertEqual(self.alice.post('/api/chat/', self.corps, format='json').status_code, 502)

    def test_la_mesure_accompagne_chaque_reponse(self):
        with mock.patch('anthropic.Anthropic', return_value=_client_claude('Bien.')):
            donnees = self.alice.post('/api/chat/', self.corps, format='json').json()
        self.assertEqual(donnees['context'], self.estimer())
        self.assertEqual(donnees['context']['messages_sent'], 1)

    def test_meme_estimateur_pour_les_lots_generes(self):
        from api import remise
        self.assertIs(remise.estimer_jetons, budget.estimer_jetons)
        self.assertEqual(remise.LOT_BUDGET_JETONS, budget.LOT_BUDGET_JETONS)
