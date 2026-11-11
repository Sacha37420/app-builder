"""Chantier app-builder-v2, secteur B — serveur MCP d'App Builder et jetons personnels (I5).

Les jetons Keycloak sont de vrais RS256 (socle.Base) ; les jetons `abt_` sont créés
par l'API de gestion, comme le ferait un utilisateur. Aucun appel réseau.
"""
from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import McpToken, PatchApplication

from .ia import OP_INVALIDE, OP_VALIDE, doubler_i3
from .socle import Base, _spec_complete

__all__ = ['McpJetonsTests', 'McpProtocoleTests', 'McpCloisonnementTests']


class _McpBase(Base):

    def setUp(self):
        super().setUp()
        doubler_i3(self)
        self.alice = self.client_de('alice')
        self.bob = self.client_de('bob')
        self.spec = self.alice.post('/api/apps/', _spec_complete(), format='json').json()['id']
        self.autre = self.alice.post('/api/apps/', {'name': 'Autre'}, format='json').json()['id']
        self.spec_bob = self.bob.post('/api/apps/', {'name': 'De Bob'}, format='json').json()['id']

    def creer(self, client=None, **corps):
        resp = (client or self.alice).post('/api/mcp-tokens/', {'name': 'mon poste', **corps}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        return resp.json()

    @staticmethod
    def mcp_client(jeton: str) -> APIClient:
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {jeton}')
        return c

    def rpc(self, jeton, methode, params=None, ident=1, attendu=200):
        corps = {'jsonrpc': '2.0', 'method': methode}
        if ident is not None:
            corps['id'] = ident
        if params is not None:
            corps['params'] = params
        resp = self.mcp_client(jeton).post('/api/mcp/', corps, format='json')
        self.assertEqual(resp.status_code, attendu, resp.content)
        return resp.json() if resp.content else None

    def outil(self, jeton, nom, **args):
        r = self.rpc(jeton, 'tools/call', {'name': nom, 'arguments': args})['result']
        import json
        return json.loads(r['content'][0]['text']), r['isError']


class McpJetonsTests(_McpBase):

    def test_creation_le_jeton_n_est_rendu_qu_une_fois(self):
        d = self.creer(scope='ecrire', spec_id=self.spec, days=7)
        self.assertRegex(d['token'], r'^abt_[A-Za-z0-9_-]{43}$')
        self.assertEqual(d['prefix'], d['token'][:12])
        self.assertEqual((d['scope'], d['spec_id'], d['revoked'], d['last_used_at']), ('ecrire', self.spec, False, None))
        self.assertEqual(set(d), {'id', 'name', 'prefix', 'scope', 'spec_id', 'created_at', 'expires_at',
                                  'last_used_at', 'revoked', 'token'})
        liste = self.alice.get('/api/mcp-tokens/').json()
        self.assertEqual(len(liste), 1)
        self.assertNotIn('token', liste[0])
        self.assertNotIn(d['token'], str(liste))
        # En base : l'empreinte seulement.
        jeton = McpToken.objects.get()
        self.assertNotIn(d['token'], str(McpToken.objects.values().get()))
        self.assertEqual(len(jeton.token_hash), 64)
        self.assertAlmostEqual((jeton.expires_at - timezone.now()).days, 6, delta=1)
        # Défaut : lire, 30 jours.
        d = self.creer()
        self.assertEqual((d['scope'], d['spec_id']), ('lire', None))
        self.assertAlmostEqual((McpToken.objects.get(pk=d['id']).expires_at - timezone.now()).days, 29, delta=1)

    def test_corps_refuses(self):
        for corps in ({'name': ''}, {'name': 'x' * 81}, {'name': 'a', 'scope': 'admin'}, {'name': 'a', 'days': 0},
                      {'name': 'a', 'days': 91}, {'name': 'a', 'days': '3'}, {'name': 'a', 'spec_id': self.spec_bob},
                      {'name': 'a', 'spec_id': 'x'}):
            with self.subTest(corps=corps):
                self.assertEqual(self.alice.post('/api/mcp-tokens/', corps, format='json').status_code, 400)
        self.assertFalse(McpToken.objects.exists())

    def test_revocation_et_cloisonnement_de_la_gestion(self):
        d = self.creer()
        self.assertEqual(self.bob.delete(f"/api/mcp-tokens/{d['id']}/").status_code, 404)
        self.assertEqual(self.bob.get('/api/mcp-tokens/').json(), [])
        self.assertEqual(self.alice.delete(f"/api/mcp-tokens/{d['id']}/").status_code, 204)
        self.assertTrue(self.alice.get('/api/mcp-tokens/').json()[0]['revoked'])
        self.assertEqual(self.rpc(d['token'], 'ping', attendu=401)['detail'], 'Jeton MCP invalide, expiré ou révoqué.')
        # La gestion est derrière la serrure Keycloak : ni abt_, ni autre client, ni hors groupe.
        d2 = self.creer()
        self.assertIn(self.mcp_client(d2['token']).get('/api/mcp-tokens/').status_code, (401, 403))
        self.assertIn(self.mcp_client(d2['token']).post('/api/mcp-tokens/', {'name': 'x'}, format='json').status_code,
                      (401, 403))
        self.assertEqual(self.client_de('alice', azp='lab-admin').get('/api/mcp-tokens/').status_code, 403)
        self.assertEqual(self.client_de('alice', groups=()).post('/api/mcp-tokens/', {'name': 'x'},
                                                                 format='json').status_code, 403)
        self.assertEqual(self.client.get('/api/mcp-tokens/').status_code, 403)

    @override_settings(FORCE_SCRIPT_NAME='/app-builder-api')
    def test_info_sans_jeton_reel(self):
        with mock.patch('api.mcp.config', side_effect=lambda cle, default='': {'DOMAIN': 'lab.exemple.org'}.get(cle, default)):
            d = self.alice.get('/api/mcp/info/').json()
        self.assertEqual(d['url'], 'https://lab.exemple.org/app-builder-api/api/mcp/')
        self.assertIn('claude mcp add', d['claude'])
        self.assertIn('--transport http', d['claude'])
        self.assertIn('<JETON>', d['claude'])
        self.assertIn('<JETON>', d['vibe'])
        self.assertIn('streamable-http', d['vibe'])
        self.assertNotIn('abt_', d['claude'] + d['vibe'])
        with mock.patch('api.mcp.config', side_effect=lambda cle, default='': {'DOMAIN': 'CHANGE_ME',
                                                                                'BACKEND_URL': 'http://localhost:8087'}.get(cle, default)):
            self.assertEqual(self.alice.get('/api/mcp/info/').json()['url'], 'http://localhost:8087/api/mcp/')


class McpProtocoleTests(_McpBase):

    def setUp(self):
        super().setUp()
        self.ecrire = self.creer(scope='ecrire')['token']
        self.lire = self.creer(scope='lire')['token']

    def test_initialize_ping_notifications_et_methodes(self):
        from api.ia import prompt
        r = self.rpc(self.lire, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                               'clientInfo': {'name': 'claude-code', 'version': '1'}})
        self.assertEqual(r['jsonrpc'], '2.0')
        self.assertEqual(r['id'], 1)
        res = r['result']
        self.assertEqual(res['protocolVersion'], '2025-06-18')
        self.assertEqual(res['serverInfo']['name'], 'app-builder')
        self.assertIn('tools', res['capabilities'])
        self.assertTrue(res['instructions'].startswith(prompt.REGLES))
        self.assertEqual(self.rpc(self.lire, 'initialize', {'protocolVersion': '1999-01-01'})['result']['protocolVersion'],
                         '2025-06-18')
        self.assertIsNone(self.rpc(self.lire, 'notifications/initialized', ident=None, attendu=202))
        self.assertEqual(self.rpc(self.lire, 'ping', ident='a')['result'], {})
        self.assertEqual(self.rpc(self.lire, 'inexistante')['error']['code'], -32601)
        self.assertEqual(self.rpc(self.lire, 'tools/call', {'name': 'pirate'})['error']['code'], -32602)
        resp = self.mcp_client(self.lire).post('/api/mcp/', {'method': 'ping', 'id': 1}, format='json')
        self.assertEqual(resp.json()['error']['code'], -32600)
        resp = self.mcp_client(self.lire).post('/api/mcp/', [{'jsonrpc': '2.0', 'method': 'ping', 'id': 1}], format='json')
        self.assertEqual(resp.json()['error']['code'], -32600)
        resp = self.mcp_client(self.lire).generic('POST', '/api/mcp/', '{pas du json', content_type='application/json')
        self.assertEqual(resp.json()['error']['code'], -32700)
        self.assertEqual(self.mcp_client(self.lire).get('/api/mcp/').status_code, 405)
        self.assertEqual(self.client.get('/api/mcp/').status_code, 405)

    def test_tools_list_selon_la_portee(self):
        tous = {'lister_specs', 'creer_spec', 'lire_index', 'lire_elements', 'verifier_spec', 'essayer_operations',
                'appliquer_operations', 'historique', 'annuler', 'lire_livrables'}
        ecriture = {'creer_spec', 'appliquer_operations', 'annuler'}
        noms = {t['name'] for t in self.rpc(self.ecrire, 'tools/list')['result']['tools']}
        self.assertEqual(noms, tous)
        noms = {t['name'] for t in self.rpc(self.lire, 'tools/list')['result']['tools']}
        self.assertEqual(noms, tous - ecriture)
        for t in self.rpc(self.ecrire, 'tools/list')['result']['tools']:
            self.assertEqual(t['inputSchema']['type'], 'object')

    def test_parcours_complet(self):
        specs, err = self.outil(self.lire, 'lister_specs')
        self.assertFalse(err)
        self.assertEqual({s['id'] for s in specs}, {self.spec, self.autre})
        index, err = self.outil(self.lire, 'lire_index', spec_id=self.spec)
        self.assertFalse(err)
        self.assertIn('index', index)
        self.assertRegex(index['version'], r'^v:')
        elements, err = self.outil(self.lire, 'lire_elements', spec_id=self.spec, section='modeles', noms=['Produit'])
        self.assertFalse(err)
        self.assertIn('elements', elements)
        verif, err = self.outil(self.lire, 'verifier_spec', spec_id=self.spec)
        self.assertEqual(set(verif) >= {'blocages', 'avertissements'}, True)
        essai, err = self.outil(self.lire, 'essayer_operations', spec_id=self.spec, operations=[OP_INVALIDE])
        self.assertFalse(err)
        self.assertFalse(essai['ok'])
        essai, _ = self.outil(self.lire, 'essayer_operations', spec_id=self.spec, operations=[OP_VALIDE])
        self.assertTrue(essai['ok'])
        self.assertFalse(PatchApplication.objects.exists())

        fait, err = self.outil(self.ecrire, 'appliquer_operations', spec_id=self.spec, operations=[OP_VALIDE],
                               base_version=index['version'])
        self.assertFalse(err, fait)
        self.assertNotEqual(fait['version'], index['version'])
        perime, err = self.outil(self.ecrire, 'appliquer_operations', spec_id=self.spec, operations=[OP_VALIDE],
                                 base_version=index['version'])
        self.assertTrue(err)
        self.assertEqual((perime['error'], perime['version']), ('version_perimee', fait['version']))
        refus, err = self.outil(self.ecrire, 'appliquer_operations', spec_id=self.spec, operations=[OP_INVALIDE],
                                base_version=fait['version'])
        self.assertTrue(err)
        self.assertEqual(refus['error'], 'refus')
        histo, _ = self.outil(self.lire, 'historique', spec_id=self.spec)
        self.assertEqual(histo[0]['id'], fait['application']['id'])
        livrables, err = self.outil(self.lire, 'lire_livrables', spec_id=self.spec)
        self.assertFalse(err)
        self.assertIn('cahier_des_charges_md', livrables)
        self.assertIn('lots_md', livrables)
        nouvelle, err = self.outil(self.ecrire, 'creer_spec', name='Neuve')
        self.assertFalse(err)
        self.assertEqual(self.alice.get(f"/api/apps/{nouvelle['id']}/").status_code, 200)
        # Erreurs d'outil : JSON {error, detail}, isError vrai.
        absent, err = self.outil(self.lire, 'lire_index', spec_id=999999)
        self.assertTrue(err)
        self.assertEqual(set(absent), {'error', 'detail'})
        mauvais, err = self.outil(self.lire, 'essayer_operations', spec_id=self.spec, operations='x')
        self.assertTrue(err)

    def test_dernier_usage_note(self):
        d = self.creer()
        self.assertIsNone(McpToken.objects.get(pk=d['id']).last_used_at)
        self.rpc(d['token'], 'ping')
        self.assertIsNotNone(McpToken.objects.get(pk=d['id']).last_used_at)

    def test_le_journal_ne_porte_ni_jeton_ni_arguments(self):
        with self.assertLogs('api.mcp', 'INFO') as journal:
            self.outil(self.lire, 'essayer_operations', spec_id=self.spec,
                       operations=[{**OP_VALIDE, 'data': {'description': 'ARGUMENT-SECRET'}}])
        texte = '\n'.join(journal.output)
        self.assertIn('essayer_operations', texte)
        self.assertIn('alice@ssolab.local', texte)
        self.assertNotIn('ARGUMENT-SECRET', texte)
        self.assertNotIn(self.lire, texte)
        self.assertNotIn(self.lire[4:], texte)


class McpCloisonnementTests(_McpBase):

    def test_jeton_keycloak_refuse_sur_le_point_mcp(self):
        resp = self.alice.post('/api/mcp/', {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}, format='json')
        self.assertEqual(resp.status_code, 401)
        self.assertNotIn('result', resp.json())

    def test_jeton_abt_refuse_partout_ailleurs(self):
        jeton = self.creer(scope='ecrire')['token']
        c = self.mcp_client(jeton)
        for methode, chemin in (('get', '/api/apps/'), ('get', f'/api/apps/{self.spec}/'), ('get', '/api/me/'),
                                ('get', '/api/ai-keys/'), ('get', '/api/mcp/info/'), ('get', '/api/handoff/specs/'),
                                ('post', '/api/chat/'), ('post', f'/api/apps/{self.spec}/operations/')):
            with self.subTest(chemin=chemin):
                resp = getattr(c, methode)(chemin, {}, format='json')
                self.assertIn(resp.status_code, (401, 403))
                self.assertNotIn(jeton, resp.content.decode())

    def test_jeton_inconnu_expire_revoque_ou_mal_forme(self):
        d = self.creer()
        McpToken.objects.filter(pk=d['id']).update(expires_at=timezone.now() - timedelta(seconds=1))
        attendu = 'Jeton MCP invalide, expiré ou révoqué.'
        for jeton in (d['token'], 'abt_' + 'x' * 43, 'abt_', 'pas-un-abt', 'abt_' + 'y' * 200):
            with self.subTest(jeton=jeton[:12]):
                r = self.rpc(jeton, 'tools/list', attendu=401)
                self.assertEqual(r['detail'], attendu)
        resp = APIClient().post('/api/mcp/', {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}, format='json')
        self.assertEqual(resp.status_code, 401)

    def test_portee_lire_refuse_les_outils_d_ecriture(self):
        jeton = self.creer(scope='lire')['token']
        v = self.alice.get(f'/api/apps/{self.spec}/').json()['version']
        for nom, args in (('appliquer_operations', {'spec_id': self.spec, 'operations': [OP_VALIDE], 'base_version': v}),
                          ('annuler', {'spec_id': self.spec, 'application_id': 1}),
                          ('creer_spec', {'name': 'x'})):
            with self.subTest(outil=nom):
                charge, err = self.outil(jeton, nom, **args)
                self.assertTrue(err)
                self.assertEqual(charge['error'], 'portee')
        self.assertFalse(PatchApplication.objects.exists())
        self.assertEqual(self.alice.get('/api/apps/').json().__len__(), 2)

    def test_specs_d_autrui_invisibles(self):
        jeton = self.creer(scope='ecrire')['token']
        specs, _ = self.outil(jeton, 'lister_specs')
        self.assertNotIn(self.spec_bob, {s['id'] for s in specs})
        for nom, args in (('lire_index', {}), ('lire_elements', {'section': 'meta', 'noms': []}),
                          ('verifier_spec', {}), ('essayer_operations', {'operations': [OP_VALIDE]}),
                          ('historique', {}), ('lire_livrables', {}),
                          ('appliquer_operations', {'operations': [OP_VALIDE], 'base_version': 'v:0'}),
                          ('annuler', {'application_id': 1})):
            with self.subTest(outil=nom):
                charge, err = self.outil(jeton, nom, spec_id=self.spec_bob, **args)
                self.assertTrue(err)
                self.assertEqual(charge['error'], 'introuvable')
        # Le jeton de Bob ne voit pas Alice non plus.
        jeton_bob = self.creer(self.bob, scope='ecrire')['token']
        self.assertEqual([s['id'] for s in self.outil(jeton_bob, 'lister_specs')[0]], [self.spec_bob])

    def test_jeton_lie_a_une_spec_ne_voit_qu_elle(self):
        jeton = self.creer(scope='ecrire', spec_id=self.spec)['token']
        specs, _ = self.outil(jeton, 'lister_specs')
        self.assertEqual([s['id'] for s in specs], [self.spec])
        charge, err = self.outil(jeton, 'lire_index', spec_id=self.autre)
        self.assertTrue(err)
        self.assertEqual(charge['error'], 'introuvable')
        self.assertFalse(self.outil(jeton, 'lire_index', spec_id=self.spec)[1])
        self.assertNotIn('creer_spec', {t['name'] for t in self.rpc(jeton, 'tools/list')['result']['tools']})
        self.assertEqual(self.outil(jeton, 'creer_spec', name='x')[0]['error'], 'portee')
        # Spec supprimée ⇒ jeton supprimé avec elle (CASCADE) ⇒ refusé.
        self.alice.delete(f'/api/apps/{self.spec}/')
        self.rpc(jeton, 'ping', attendu=401)
