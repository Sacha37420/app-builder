"""Lot 3 — mesure du contexte : ce que pèse un envoi, ce que le modèle peut tenir.

Depuis le chantier app-builder-v2 : la spec est lue en base (`app_id`), seule son
index part vers le modèle ; les outils et la place gardée pour leurs résultats
comptent dans la mesure.
"""
from unittest import mock

import requests

from api import budget, views
from api.ia import fournisseurs, prompt

from .ia import FauxClaude, doubler_i3, erreur_anthropic, rep_claude, texte
from .socle import Base, _spec_complete

__all__ = ['BudgetContexteTests']


class BudgetContexteTests(Base):

    def setUp(self):
        super().setUp()
        doubler_i3(self)
        self.alice = self.client_de('alice')
        self.coffre('alice', claude='cle-de-alice', mistral='cle-de-alice')
        self.app_id = self.nouvelle(_spec_complete())
        self.corps = {'app_id': self.app_id, 'provider': 'claude',
                      'messages': [{'role': 'user', 'content': 'Une boutique'}]}

    def nouvelle(self, spec) -> int:
        resp = self.alice.post('/api/apps/', spec, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        return resp.json()['id']

    def estimer(self, **corps):
        resp = self.alice.post('/api/chat/estimate/', {**self.corps, **corps}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()['context']

    def chat(self, faux, **corps):
        with mock.patch('anthropic.Anthropic', return_value=faux):
            return self.alice.post('/api/chat/', {**self.corps, **corps}, format='json')

    # ── Table des modèles ─────────────────────────────────────────────────────

    def test_la_liste_des_modeles_est_servie_par_l_api(self):
        resp = self.alice.get('/api/models/')
        self.assertEqual(resp.status_code, 200)
        catalogue = resp.json()
        self.assertEqual(set(catalogue['providers']), {'claude', 'mistral', 'albert'})
        for fournisseur in catalogue['providers'].values():
            ids = [m['id'] for m in fournisseur['models']]
            self.assertIn(fournisseur['default'], ids)
            for m in fournisseur['models']:
                self.assertEqual(set(m), {'id', 'label', 'context_window', 'max_output', 'tools'})
                self.assertGreater(m['context_window'], m['max_output'])
                self.assertIsInstance(m['tools'], bool)
        ids = [m['id'] for m in catalogue['providers']['claude']['models']]
        for actuel in ('claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'):
            self.assertIn(actuel, ids)
        self.assertEqual(catalogue['lot_budget_tokens'], budget.LOT_BUDGET_JETONS)
        self.assertEqual(self.client_de('alice', azp='lab-admin').get('/api/models/').status_code, 403)

    def test_seuil_par_modele(self):
        petit = self.estimer(provider='mistral', model='mistral-small-latest')
        grand = self.estimer(provider='claude', model='claude-sonnet-5-5')
        self.assertEqual((petit['context_window'], grand['context_window']), (32_000, 1_000_000))
        self.assertEqual(petit['available_tokens'], 32_000 - 8_192 - budget.MARGE_JETONS - budget.RESERVE_OUTILS)
        self.assertEqual(petit['reserved_tool_tokens'], budget.RESERVE_OUTILS)
        self.assertEqual(grand['reserved_output_tokens'], 16_000)
        self.assertGreater(petit['ratio'], grand['ratio'])
        # Sans modèle : celui par défaut du fournisseur. Ancien identifiant : reconnu. Inconnu : prudence.
        self.assertEqual(self.estimer(model='')['model'], 'claude-sonnet-5-5')
        self.assertEqual(self.estimer(provider='mistral', model=None)['model'], 'mistral-small-latest')
        self.assertEqual(budget.modele('claude', 'claude-haiku-4-5-20251001')['context_window'], 200_000)
        inconnu = self.estimer(model='modele-inconnu')
        self.assertEqual(inconnu['context_window'], 32_000)
        # Sans outils : ni outils comptés, ni place gardée pour leurs résultats.
        self.assertEqual((inconnu['tools_tokens'], inconnu['reserved_tool_tokens']), (0, 0))
        # Un modèle d'un autre fournisseur n'emprunte pas sa fenêtre.
        self.assertEqual(self.estimer(provider='mistral', model='claude-sonnet-5-5')['context_window'], 32_000)

    # ── Estimation ────────────────────────────────────────────────────────────

    def test_estimation_croissante_avec_la_spec_et_la_conversation(self):
        vide = self.estimer(app_id=None)
        petite = self.estimer()
        grosse = _spec_complete()
        grosse['data_models'] += [{'name': f'Modele{i}', 'fields': [{'name': 'champ', 'type': 'string'}]} for i in range(50)]
        grande = self.estimer(app_id=self.nouvelle(grosse))
        self.assertLess(vide['index_tokens'], petite['index_tokens'])
        self.assertLess(petite['index_tokens'], grande['index_tokens'])
        self.assertEqual(petite['spec_tokens'], petite['index_tokens'])
        self.assertLess(petite['estimated_tokens'], grande['estimated_tokens'])
        self.assertEqual(petite['estimated_tokens'], petite['system_tokens'] + petite['history_tokens'])
        # Le bloc stable et les outils sont dans system_tokens.
        self.assertGreaterEqual(petite['system_tokens'],
                                budget.estimer_jetons(prompt.REGLES) + petite['tools_tokens'] + petite['index_tokens'])
        bavarde = self.estimer(messages=[{'role': 'user', 'content': 'x' * 3000}])
        self.assertEqual(bavarde['history_tokens'], 1000)
        self.assertEqual(set(vide), {'model', 'provider', 'context_window', 'reserved_output_tokens',
                                     'reserved_tool_tokens', 'available_tokens', 'system_tokens', 'spec_tokens',
                                     'history_tokens', 'tools_tokens', 'index_tokens', 'tool_results_tokens',
                                     'estimated_tokens', 'ratio', 'fits', 'messages_sent', 'messages_dropped'})

    def test_l_estimation_n_appelle_personne_et_ne_demande_pas_de_cle(self):
        with mock.patch('anthropic.Anthropic', side_effect=AssertionError('appel')), \
                mock.patch.object(views.http_requests, 'post', side_effect=AssertionError('appel')), \
                mock.patch('socket.socket', side_effect=AssertionError('réseau')):
            resp = self.client_de('bob').post('/api/chat/estimate/', {**self.corps, 'app_id': None}, format='json')
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json()['context']['fits'])
            self.assertEqual(budget.estimer_jetons('é' * 3), 2)

    def test_la_spec_vient_de_la_base_jamais_du_corps_ni_la_conversation(self):
        base = self.estimer()
        # Une spec (et une conversation) jointes au corps ne pèsent rien et ne partent pas.
        avec = self.estimer(app_spec={**_spec_complete(), 'chat_history': [{'role': 'user', 'content': 'x' * 30000}]})
        self.assertEqual(avec['estimated_tokens'], base['estimated_tokens'])
        self.alice.patch(f'/api/apps/{self.app_id}/chat/',
                         {'chat_history': [{'role': 'user', 'content': 'CONFIDENTIEL-HISTORIQUE'}]}, format='json')
        faux = FauxClaude(rep_claude(texte('Bien.')))
        self.chat(faux, app_spec={'name': 'PATCH-JOINT'})
        envoye = str(faux.requetes)
        self.assertNotIn('CONFIDENTIEL-HISTORIQUE', envoye)
        self.assertNotIn('PATCH-JOINT', envoye)
        self.assertNotIn('chat_history', envoye)

    # ── Historique borné ──────────────────────────────────────────────────────

    def _conversation(self, echanges, taille=30):
        msgs = []
        for i in range(echanges):
            msgs += [{'role': 'user', 'content': f'question {i} ' + 'q' * taille, 'applied': 'merged'},
                     {'role': 'assistant', 'content': f'réponse {i} ' + 'r' * taille, 'proposal': {'operations': []}}]
        return msgs + [{'role': 'user', 'content': 'LA DERNIÈRE QUESTION'}]

    def test_historique_tronque_sans_perdre_le_dernier_message(self):
        faux = FauxClaude(rep_claude(texte('Bien.')))
        resp = self.chat(faux, messages=self._conversation(40))
        self.assertEqual(resp.status_code, 200)
        envoyes = faux.requetes[0]['messages']
        self.assertLessEqual(len(envoyes), budget.HISTORIQUE_MAX_MESSAGES)
        self.assertEqual(envoyes[-1], {'role': 'user', 'content': 'LA DERNIÈRE QUESTION'})
        self.assertEqual(envoyes[0]['role'], 'user')
        self.assertTrue(envoyes[-2]['content'].startswith('réponse 39'))
        self.assertTrue(all(set(m) == {'role', 'content'} for m in envoyes))
        contexte = resp.json()['context']
        self.assertEqual((contexte['messages_sent'], contexte['messages_dropped']), (len(envoyes), 81 - len(envoyes)))

    def test_petite_fenetre_on_garde_ce_qui_tient_en_partant_de_la_fin(self):
        messages = self._conversation(8, taille=9000)        # ≈ 3 000 jetons par message
        contexte = self.estimer(provider='mistral', model='mistral-small-latest', messages=messages, app_id=None)
        self.assertTrue(contexte['fits'])
        self.assertGreater(contexte['messages_dropped'], 0)
        self.assertLess(contexte['messages_sent'], 17)
        self.assertLessEqual(contexte['estimated_tokens'], contexte['available_tokens'])
        gardes, retires = budget.borner(budget.nettoyer(messages), 7000)
        self.assertEqual(([m['content'][:10] for m in gardes], retires), (['question 7', 'réponse 7 ', 'LA DERNIÈR'], 14))
        self.assertEqual(budget.borner(budget.nettoyer(messages), 0), ([{'role': 'user', 'content': 'LA DERNIÈRE QUESTION'}], 16))
        self.assertEqual(budget.borner([], 100), ([], 0))
        self.assertEqual(budget.nettoyer([None, {'role': 'system', 'content': 'x'}, {'role': 'user', 'content': '  '},
                                          {'role': 'user', 'content': 'ok', 'api_key': 'k'}, 'texte']),
                         [{'role': 'user', 'content': 'ok'}])
        self.assertEqual(budget.nettoyer('pas une liste'), [])

    # ── Refus avant l'appel ───────────────────────────────────────────────────

    def test_refus_avant_appel_quand_le_budget_est_depasse(self):
        corps = {'provider': 'mistral', 'model': 'mistral-small-latest',
                 'messages': [{'role': 'user', 'content': 'x' * 200_000}]}
        with mock.patch('anthropic.Anthropic') as ctor, mock.patch.object(fournisseurs.http_requests, 'post') as post:
            resp = self.alice.post('/api/chat/', {**self.corps, **corps}, format='json')
            ctor.assert_not_called()
            post.assert_not_called()
        self.assertEqual(resp.status_code, 413)
        refus = resp.json()
        self.assertEqual(refus['code'], 'context_too_large')
        self.assertIn('mistral-small-latest', refus['error'])
        self.assertFalse(refus['context']['fits'])
        self.assertGreater(refus['context']['ratio'], 1)
        # Le même message tient dans une grande fenêtre : l'appel part.
        resp = self.chat(FauxClaude(rep_claude(texte('Bien.'))), **{**corps, 'provider': 'claude', 'model': 'claude-sonnet-5-5'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['context']['fits'])

    def test_sans_message_rien_ne_part(self):
        with mock.patch('anthropic.Anthropic') as ctor:
            for messages in ([], None, [{'role': 'user', 'content': ''}], 'texte'):
                resp = self.alice.post('/api/chat/', {**self.corps, 'messages': messages}, format='json')
                self.assertEqual(resp.status_code, 400)
            ctor.assert_not_called()

    # ── Erreur du fournisseur traduite ────────────────────────────────────────

    def test_erreur_contexte_trop_long_du_fournisseur_traduite(self):
        import anthropic
        for message in ('prompt is too long: 1200000 tokens > 1000000 maximum',
                        "This model's maximum context length is 32000 tokens"):
            with self.subTest(message=message[:30]):
                resp = self.chat(FauxClaude(erreur_anthropic(anthropic.BadRequestError, 400, message)))
                self.assertEqual(resp.status_code, 413)
                self.assertEqual(resp.json()['code'], 'context_too_large')
                self.assertNotIn('invalid_request_error', resp.json()['error'])
        http = requests.exceptions.HTTPError('400 Client Error')
        http.response = mock.Mock(status_code=400, text='{"message": "Prompt contains 40000 tokens, too large for model '
                                                         'with 32000 maximum context length"}')
        with mock.patch.object(fournisseurs.http_requests, 'post', side_effect=http):
            resp = self.alice.post('/api/chat/', {**self.corps, 'provider': 'mistral'}, format='json')
        self.assertEqual(resp.status_code, 413)
        # Toute autre panne reste une erreur de passerelle.
        resp = self.chat(FauxClaude(erreur_anthropic(anthropic.InternalServerError, 500, 'clé refusée')))
        self.assertEqual(resp.status_code, 502)

    def test_la_mesure_accompagne_chaque_reponse(self):
        donnees = self.chat(FauxClaude(rep_claude(texte('Bien.')))).json()
        self.assertEqual(donnees['context'], self.estimer())
        self.assertEqual(donnees['context']['messages_sent'], 1)

    def test_meme_estimateur_pour_les_lots_generes(self):
        from api import remise
        self.assertIs(remise.estimer_jetons, budget.estimer_jetons)
        self.assertEqual(remise.LOT_BUDGET_JETONS, budget.LOT_BUDGET_JETONS)
