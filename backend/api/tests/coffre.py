"""Lot 8 — coffre des clés d'API (contrat « failles », I3).

La clé est saisie une fois, gardée chiffrée côté serveur (`VAULT_ENCRYPTION_KEY`),
jamais rendue au navigateur ; le backend appelle le fournisseur avec elle.
"""
from unittest import mock

from cryptography.fernet import Fernet
from django.db import connection
from django.test import override_settings

from api import views
from api.models import AiKeyVault

from .socle import Base, _client_claude, jeton

__all__ = ['CoffreClesTests']

CLE_CLAUDE = 'sk-ant-api03-SECRETE-de-alice'
CLE_MISTRAL = 'mistral-SECRETE-de-alice'


class CoffreClesTests(Base):

    def setUp(self):
        super().setUp()
        self.alice = self.client_de('alice')
        self.bob = self.client_de('bob')

    def deposer(self, client=None, **corps):
        return (client or self.alice).put('/api/ai-keys/', corps, format='json')

    def etat(self, client=None):
        resp = (client or self.alice).get('/api/ai-keys/')
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def brut(self, email='alice@ssolab.local'):
        with connection.cursor() as cur:
            cur.execute('SELECT claude_key, mistral_key FROM ai_key_vault WHERE owner_email = %s', [email])
            return cur.fetchone()

    # ── Forme de l'API ────────────────────────────────────────────────────────

    def test_get_ne_rend_que_configured(self):
        self.assertEqual(self.etat(), {'claude_key_configured': False, 'mistral_key_configured': False})
        resp = self.deposer(claude_key=CLE_CLAUDE)
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.content, b'')
        resp = self.alice.get('/api/ai-keys/')
        self.assertEqual(resp.json(), {'claude_key_configured': True, 'mistral_key_configured': False})
        self.assertNotIn('SECRETE', resp.content.decode())
        self.assertNotIn('sk-ant', resp.content.decode())

    def test_les_deux_cles_puis_suppression_par_chaine_vide(self):
        self.assertEqual(self.deposer(claude_key=CLE_CLAUDE, mistral_key=CLE_MISTRAL).status_code, 204)
        self.assertEqual(self.etat(), {'claude_key_configured': True, 'mistral_key_configured': True})
        # Champ absent : inchangé ; chaîne vide : supprimée.
        self.assertEqual(self.deposer(mistral_key='').status_code, 204)
        self.assertEqual(self.etat(), {'claude_key_configured': True, 'mistral_key_configured': False})
        self.assertEqual(self.deposer(claude_key='   ').status_code, 204)
        self.assertEqual(self.etat(), {'claude_key_configured': False, 'mistral_key_configured': False})

    def test_corps_refuses(self):
        for corps in ({}, {'autre': 'x'}, {'claude_key': 12}, {'claude_key': None},
                      {'claude_key': 'deux mots'}, {'claude_key': 'x' * 513}, {'mistral_key': 'a\nb'}):
            with self.subTest(corps=corps):
                self.assertEqual(self.alice.put('/api/ai-keys/', corps, format='json').status_code, 400)
        self.assertEqual(self.alice.put('/api/ai-keys/', ['claude_key'], format='json').status_code, 400)
        self.assertFalse(AiKeyVault.objects.exists())

    # ── Chiffrement au repos ──────────────────────────────────────────────────

    def test_chiffree_en_base_avec_la_cle_du_coffre_et_non_secret_key(self):
        self.deposer(claude_key=CLE_CLAUDE)
        claude_brut, mistral_brut = self.brut()
        self.assertTrue(claude_brut.startswith('gAAAAA'))
        self.assertNotIn('SECRETE', claude_brut)
        self.assertEqual(mistral_brut, '')
        from django.conf import settings
        self.assertEqual(Fernet(settings.VAULT_ENCRYPTION_KEY.encode()).decrypt(claude_brut.encode()).decode(), CLE_CLAUDE)
        # Faire tourner SECRET_KEY ne détruit rien.
        with override_settings(SECRET_KEY='une-toute-autre-cle-django'):
            self.assertEqual(AiKeyVault.objects.get().claude_key, CLE_CLAUDE)

    def test_valeur_indechiffrable_traitee_comme_absente_jamais_rendue_ni_envoyee(self):
        self.deposer(claude_key=CLE_CLAUDE)
        claude_brut, _ = self.brut()
        with override_settings(VAULT_ENCRYPTION_KEY=Fernet.generate_key().decode()), \
                self.assertLogs('api.fields', 'WARNING') as journal:
            self.assertEqual(self.etat(), {'claude_key_configured': False, 'mistral_key_configured': False})
            with mock.patch('anthropic.Anthropic') as ctor:
                resp = self.alice.post('/api/chat/', {'provider': 'claude', 'messages': [{'role': 'user', 'content': 'x'}]},
                                       format='json')
            self.assertEqual(resp.status_code, 400)
            ctor.assert_not_called()
        self.assertNotIn(claude_brut, '\n'.join(journal.output))

    # ── Cloisonnement ─────────────────────────────────────────────────────────

    def test_un_autre_compte_ne_lit_ni_n_utilise_la_cle_d_autrui(self):
        self.deposer(claude_key=CLE_CLAUDE, mistral_key=CLE_MISTRAL)
        self.assertEqual(self.etat(self.bob), {'claude_key_configured': False, 'mistral_key_configured': False})
        for provider in ('claude', 'mistral'):
            with self.subTest(provider=provider), mock.patch('anthropic.Anthropic') as ctor, \
                    mock.patch.object(views.http_requests, 'post') as post:
                resp = self.bob.post('/api/chat/', {'provider': provider, 'messages': [{'role': 'user', 'content': 'x'}]},
                                     format='json')
                self.assertEqual(resp.status_code, 400)
                ctor.assert_not_called()
                post.assert_not_called()
        # Bob qui dépose la sienne ne touche pas à celle d'Alice.
        self.deposer(self.bob, claude_key='cle-de-bob')
        self.assertEqual(AiKeyVault.objects.get(owner_email='alice@ssolab.local').claude_key, CLE_CLAUDE)
        client = _client_claude('Bonjour.')
        with mock.patch('anthropic.Anthropic', return_value=client) as ctor:
            self.bob.post('/api/chat/', {'provider': 'claude', 'messages': [{'role': 'user', 'content': 'x'}]}, format='json')
        self.assertEqual(ctor.call_args.kwargs, {'api_key': 'cle-de-bob'})

    @override_settings(KEYCLOAK_HANDOFF_CLIENTS='lab-admin')
    def test_jeton_d_un_autre_client_refuse_en_lecture_et_en_ecriture(self):
        self.deposer(claude_key=CLE_CLAUDE)
        for azp in ('admin-cli', 'lab-admin', 'storage', None):
            client = self.avec(jeton('alice', azp=azp))
            with self.subTest(azp=azp):
                resp = client.get('/api/ai-keys/')
                self.assertEqual(resp.status_code, 403)
                self.assertNotIn('SECRETE', resp.content.decode())
                self.assertEqual(client.put('/api/ai-keys/', {'claude_key': 'pirate'}, format='json').status_code, 403)
        sans_groupe = self.client_de('alice', groups=())
        self.assertEqual(sans_groupe.get('/api/ai-keys/').status_code, 403)
        # Sans jeton : refus (403 dans cette app, l'authentification n'émet pas de WWW-Authenticate).
        self.assertEqual(self.client.get('/api/ai-keys/').status_code, 403)
        self.assertEqual(self.client.put('/api/ai-keys/', {'claude_key': 'pirate'}, format='json').status_code, 403)
        self.assertEqual(AiKeyVault.objects.get().claude_key, CLE_CLAUDE)

    # ── Appel au fournisseur ──────────────────────────────────────────────────

    def test_le_fournisseur_recoit_la_cle_du_coffre_et_la_reponse_ne_la_cite_pas(self):
        self.deposer(claude_key=CLE_CLAUDE, mistral_key=CLE_MISTRAL)
        client = _client_claude('Voici.\nPATCH_READY', '{"set_meta": {"required_groups": ["famille"]}}')
        with mock.patch('anthropic.Anthropic', return_value=client) as ctor:
            resp = self.alice.post('/api/chat/', {'provider': 'claude', 'messages': [{'role': 'user', 'content': 'x'}]},
                                   format='json')
        self.assertEqual(resp.status_code, 200)
        # Les deux échanges (texte puis patch) utilisent la clé du coffre.
        self.assertEqual([c.kwargs for c in ctor.call_args_list], [{'api_key': CLE_CLAUDE}] * 2)
        self.assertNotIn('SECRETE', resp.content.decode())

        flux = mock.MagicMock()
        flux.__enter__.return_value.iter_lines.return_value = iter([b'data: {"choices": [{"delta": {"content": "ok"}}]}'])
        with mock.patch.object(views.http_requests, 'post', return_value=flux) as post:
            resp = self.alice.post('/api/chat/', {'provider': 'mistral', 'messages': [{'role': 'user', 'content': 'x'}]},
                                   format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], f'Bearer {CLE_MISTRAL}')
        self.assertTrue(post.call_args.args[0].startswith('https://api.mistral.ai/'))
        self.assertNotIn('SECRETE', resp.content.decode())
