"""Lot 12 — Albert (API de la DINUM), troisième fournisseur, compatible OpenAI.

Aucun appel réseau : `requests.post` (chat) et `requests.get` (catalogue) sont remplacés.
Ce qui est prouvé ici : adresse et en-tête d'Albert, `tool_choice: "auto"` explicite, boucle
d'outils complète, clé lue au coffre de l'appelant (jamais une autre), catalogue lu chez le
fournisseur (filtre de type, fenêtre, panne ⇒ table prudente), messages d'erreur fixes.
"""
import json
from unittest import mock

import requests
from django.core.cache import cache

from api import budget
from api.ia import catalogue, fournisseurs

from .ia import OP_VALIDE, _ChatBase, rep_mistral

__all__ = ['AlbertTests']

URL_CHAT = 'https://albert.api.etalab.gouv.fr/v1/chat/completions'
URL_MODELES = 'https://albert.api.etalab.gouv.fr/v1/models'


def rep_modeles(*modeles, statut=200):
    r = mock.Mock()
    r.status_code = statut
    if statut >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(response=r)
    else:
        r.raise_for_status.return_value = None
    r.json.return_value = {'object': 'list', 'data': list(modeles)}
    return r


def erreur_http(statut):
    r = mock.Mock()
    r.status_code = statut
    r.text = ''
    r.raise_for_status.side_effect = requests.HTTPError('refus https://albert…?key=secret', response=r)
    return r


class AlbertTests(_ChatBase):

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.coffre('alice', claude='cle-de-alice', mistral='cle-mistral-de-alice', albert='cle-albert-de-alice')

    def chat_albert(self, *reponses, client=None, **corps):
        with mock.patch.object(fournisseurs.http_requests, 'post', side_effect=list(reponses)) as post:
            resp = (client or self.alice).post('/api/chat/', {**self.corps, 'provider': 'albert',
                                                              'model': 'openweight-large', **corps}, format='json')
        self.post = post
        return resp

    # ── Le fournisseur ────────────────────────────────────────────────────────

    def test_albert_est_un_fournisseur_compatible_openai(self):
        f = budget.FOURNISSEURS['albert']
        self.assertEqual((f['protocole'], f['url'], f['champ']),
                         ('openai', 'https://albert.api.etalab.gouv.fr/v1', 'albert_key'))
        self.assertEqual(budget.fournisseur('albert'), 'albert')
        self.assertEqual(budget.fournisseur('inconnu'), 'claude')
        self.assertEqual(budget.modele('albert')['id'], 'openweight-large')
        self.assertTrue(budget.modele('albert')['tools'])

    def test_boucle_d_outils_complete_sur_albert(self):
        resp = self.chat_albert(
            rep_mistral('', [('t1', 'lire_elements', json.dumps({'section': 'modeles', 'noms': ['Produit']}))]),
            rep_mistral('', [('t2', 'proposer_operations', json.dumps({'operations': [OP_VALIDE]}))]),
            rep_mistral('Le prix est proposé.'))
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()
        self.assertEqual(d['provider'], 'albert')
        self.assertEqual(d['proposal']['operations'], [OP_VALIDE])
        self.assertEqual(d['usage']['calls'], 3)
        premier = self.post.call_args_list[0]
        self.assertEqual(premier.args[0], URL_CHAT)
        self.assertEqual(premier.kwargs['headers']['Authorization'], 'Bearer cle-albert-de-alice')
        payload = premier.kwargs['json']
        self.assertEqual(payload['model'], 'openweight-large')
        # Explicite : sans lui, DeepSeek V4 sur Albert n'émet aucun appel d'outil (doc DINUM).
        self.assertEqual(payload['tool_choice'], 'auto')
        self.assertEqual(payload['tools'][0]['type'], 'function')
        # Résultats d'outils au format OpenAI (messages `tool`).
        suite = self.post.call_args_list[1].kwargs['json']['messages']
        self.assertEqual((suite[-1]['role'], suite[-1]['tool_call_id']), ('tool', 't1'))

    def test_appel_d_outil_a_contenu_vide(self):
        # Gemma 4 sur Albert : l'appel d'outil arrive avec `content` vide (doc DINUM).
        vide = rep_mistral('', [('g1', 'verifier_spec', '{}')])
        vide.json.return_value['choices'][0]['message']['content'] = None
        d = self.chat_albert(vide, rep_mistral('Rien à signaler.')).json()
        self.assertEqual(d['content'], 'Rien à signaler.')

    def test_sans_cle_albert_aucun_appel(self):
        self.coffre('alice', claude='cle-de-alice', mistral='cle-mistral-de-alice', albert='')
        resp = self.chat_albert()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['code'], 'key_not_configured')
        self.assertIn('Intelligence artificielle', resp.json()['error'])
        self.post.assert_not_called()

    def test_jamais_la_cle_d_un_autre(self):
        bob = self.client_de('bob')
        app_bob = bob.post('/api/apps/', {'name': 'Bob'}, format='json').json()['id']
        resp = self.chat_albert(client=bob, app_id=app_bob)
        self.assertEqual(resp.status_code, 400)          # bob n'a pas de clé Albert
        self.post.assert_not_called()

    def test_erreurs_traduites_en_message_fixe(self):
        for statut, attendu in ((401, 'Clé Albert (DINUM) refusée'), (404, 'Modèle inconnu chez Albert'),
                                (429, 'Quota du fournisseur Albert')):
            resp = self.chat_albert(erreur_http(statut))
            self.assertEqual(resp.status_code, 502, statut)
            self.assertIn(attendu, resp.json()['error'])
            self.assertNotIn('secret', resp.content.decode())

    # ── Le coffre ─────────────────────────────────────────────────────────────

    def test_coffre_garde_la_cle_albert_sans_la_rendre(self):
        self.assertEqual(self.alice.put('/api/ai-keys/', {'albert_key': 'nouvelle-cle-albert'},
                                        format='json').status_code, 204)
        etat = self.alice.get('/api/ai-keys/').json()
        self.assertTrue(etat['albert_key_configured'])
        self.assertNotIn('nouvelle-cle-albert', json.dumps(etat))
        self.assertEqual(self.alice.put('/api/ai-keys/', {'albert_key': ''}, format='json').status_code, 204)
        self.assertFalse(self.alice.get('/api/ai-keys/').json()['albert_key_configured'])

    # ── Le catalogue ──────────────────────────────────────────────────────────

    def test_catalogue_lu_chez_albert_avec_la_cle_de_l_appelant(self):
        reponse = rep_modeles(
            {'id': 'gpt-oss-120b', 'type': 'text-generation', 'max_context_length': 131072},
            {'id': 'deepseek-v4-flash', 'type': 'text-generation', 'max_context_length': 131072},
            {'id': 'embeddings-small', 'type': 'text-embeddings-inference', 'max_context_length': 8192},
            {'id': 'lightonocr-2-1b', 'type': 'text-generation'},
            {'id': 'whisper', 'type': 'automatic-speech-recognition'})
        with mock.patch.object(catalogue.http_requests, 'get', return_value=reponse) as get:
            d = self.alice.get('/api/models/').json()
            self.alice.get('/api/models/')                     # second appel : cache
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.args[0], URL_MODELES)
        self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer cle-albert-de-alice')
        ids = [m['id'] for m in d['providers']['albert']['models']]
        self.assertEqual(ids[:3], ['openweight-large', 'openweight-medium', 'openweight-small'])  # table d'abord
        self.assertIn('gpt-oss-120b', ids)
        self.assertIn('deepseek-v4-flash', ids)
        self.assertNotIn('embeddings-small', ids)
        self.assertNotIn('lightonocr-2-1b', ids)
        self.assertNotIn('whisper', ids)
        self.assertEqual(d['providers']['albert']['label'], 'Albert (DINUM)')
        # Un modèle lu chez Albert est ensuite connu du budget, sans appel réseau.
        fiche = budget.modele('albert', 'deepseek-v4-flash')
        self.assertEqual((fiche['context_window'], fiche['tools']), (131072, True))

    def test_catalogue_en_panne_table_prudente(self):
        with mock.patch.object(catalogue.http_requests, 'get', return_value=rep_modeles(statut=401)):
            d = self.alice.get('/api/models/').json()
        self.assertEqual([m['id'] for m in d['providers']['albert']['models']],
                         ['openweight-large', 'openweight-medium', 'openweight-small'])
        with mock.patch.object(catalogue.http_requests, 'get', side_effect=requests.ConnectionError('x')):
            cache.clear()
            self.assertEqual(self.alice.get('/api/models/').status_code, 200)

    def test_sans_cle_aucune_lecture_du_catalogue(self):
        bob = self.client_de('bob')
        with mock.patch.object(catalogue.http_requests, 'get') as get:
            d = bob.get('/api/models/').json()
        get.assert_not_called()
        self.assertEqual(sorted(d['providers']), ['albert', 'claude', 'mistral'])

    def test_modele_inconnu_d_albert_reste_prudent(self):
        fiche = budget.modele('albert', 'modele-jamais-vu')
        self.assertEqual(fiche['context_window'], budget._FENETRE_INCONNUE)
        self.assertFalse(fiche['tools'])
