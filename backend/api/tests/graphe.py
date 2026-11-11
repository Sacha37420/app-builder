"""Lot 6 — le graphe d'une spécification, à toutes les échelles (v2 : interface I6)."""
import copy
import json

from django.test import SimpleTestCase

from api import graphe, remise

from .remise import _AvecSpecs, spec_riche

__all__ = ['VueEnsembleTests', 'GrapheReglesTests', 'GrapheV2Tests']


def _par_id(g):
    return {n['id']: n for n in g['nodes']}


def _liens(g, kind=None):
    return {(lien['source'], lien['target']) for lien in g['links'] if kind is None or lien['kind'] == kind}


class VueEnsembleTests(_AvecSpecs):

    def graphe(self):
        resp = self.alice.get(f"/api/apps/{self.prete['id']}/graph/")
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()

    def test_l_api_rend_le_graphe_de_la_spec(self):
        g = self.graphe()
        self.assertGreaterEqual(set(g), {'spec', 'scales', 'nodes', 'links'})
        self.assertEqual([e['id'] for e in g['scales']][:5], ['overview', 'architecture', 'data', 'pipelines', 'roadmap'])
        self.assertEqual(g['version'], 2)
        self.assertEqual(g['spec']['name'], 'Gestion de stock')
        noeuds = _par_id(g)
        self.assertEqual(len(noeuds), len(g['nodes']))                      # identifiants uniques
        for n in g['nodes']:
            self.assertGreaterEqual(set(n), {'id', 'kind', 'scale', 'label', 'parent', 'detail'})
            self.assertIn(n['scale'], {e['id'] for e in g['scales']})
            self.assertTrue(n['parent'] is None or n['parent'] in noeuds, n)
        # Aucun lien ne pend dans le vide.
        for lien in g['links']:
            self.assertIn(lien['source'], noeuds)
            self.assertIn(lien['target'], noeuds)

    def test_noeuds_coherents_avec_la_spec(self):
        g = self.graphe()
        spec = self.alice.get(f"/api/apps/{self.prete['id']}/").json()
        par_genre = {}
        for n in g['nodes']:
            par_genre.setdefault(n['kind'], []).append(n)
        self.assertCountEqual([n['label'] for n in par_genre['data_model']], [m['name'] for m in spec['data_models']])
        self.assertCountEqual([n['label'] for n in par_genre['endpoint_group']], [x['name'] for x in spec['endpoint_groups']])
        self.assertEqual(len(par_genre['endpoint']), sum(len(x['endpoints']) for x in spec['endpoint_groups']))
        self.assertCountEqual([n['label'] for n in par_genre['service']], [s['name'] for s in spec['services']])
        self.assertCountEqual([n['label'] for n in par_genre['page']], [p['name'] for p in spec['pages']])
        self.assertEqual(len(par_genre['pipeline']), sum(len(p['pipelines']) for p in spec['pages']))
        self.assertEqual(len(par_genre['step']), sum(len(pl['steps']) for p in spec['pages'] for pl in p['pipelines']))
        self.assertEqual(len(par_genre['lot']), len(remise.lots(spec)))
        noeuds = _par_id(g)
        self.assertEqual(noeuds['model:Produit']['fields'], [{'name': 'nom', 'type': 'string'}, {'name': 'photo', 'type': 'storage_file'}])
        self.assertTrue(noeuds['endpoint:Produits/GET /api/vitrine/']['public'])
        self.assertEqual(noeuds['endpoint:Produits/POST /api/produits/']['roles'], ['manager'])

    def test_vue_d_ensemble_groupes_keycloak_interface_api_base_storage(self):
        g = self.graphe()
        ensemble = [n['id'] for n in g['nodes'] if n['scale'] == 'overview' and n['id'].startswith('infra:')]
        self.assertEqual(ensemble, ['infra:groups', 'infra:keycloak', 'infra:frontend', 'infra:api', 'infra:database',
                                    'infra:storage', 'infra:email'])
        flux = _liens(g, 'flow')
        self.assertEqual(flux, {('infra:groups', 'infra:keycloak'), ('infra:keycloak', 'infra:frontend'),
                                ('infra:frontend', 'infra:api'), ('infra:api', 'infra:database'),
                                ('infra:api', 'infra:storage'), ('infra:api', 'infra:email')})
        noeuds = _par_id(g)
        self.assertEqual(noeuds['infra:groups']['detail'], 'developers, famille')
        self.assertEqual((noeuds['infra:frontend']['detail'], noeuds['infra:api']['detail']),
                         ('/gestion-stock', '/gestion-stock-api'))
        self.assertEqual((noeuds['infra:api']['opens'], noeuds['infra:database']['opens'], noeuds['infra:api']['count']),
                         ('architecture', 'data', 4))

    def test_liens_coherents_et_navigation_d_une_echelle_a_l_autre(self):
        g = self.graphe()
        tous = _liens(g)
        for attendu in (
            ('page:ListeProduits', 'service:ProduitService'),               # la page utilise le service
            ('service:ProduitService', 'group:Produits'),                   # qui appelle le groupe d'endpoints
            ('endpoint:Produits/GET /api/produits/', 'model:Produit'),      # dont l'endpoint lit le modèle
            ('model:Mouvement', 'model:Produit'),                           # relation entre modèles
            ('interaction:ListeProduits/Page chargée', 'pipeline:ListeProduits/Chargement'),
            ('step:ListeProduits/Chargement/0', 'service:ProduitService'),  # l'étape invoque le service
        ):
            self.assertIn(attendu, tous)
        # Chaque nœud fin remonte à la vue d'ensemble par ses parents.
        noeuds = _par_id(g)
        def racine(ident):
            while noeuds[ident]['parent']:
                ident = noeuds[ident]['parent']
            return ident
        self.assertEqual(racine('step:ListeProduits/Chargement/0'), 'infra:frontend')
        self.assertEqual(racine('endpoint:Produits/GET /api/produits/'), 'infra:api')
        self.assertEqual(racine('model:Produit'), 'infra:database')

    def test_les_lots_sont_relies_aux_elements_qu_ils_construisent(self):
        g = self.graphe()
        construit = _liens(g, 'builds')
        self.assertIn(('lot:2', 'model:Produit'), construit)
        self.assertIn(('lot:2', 'model:Mouvement'), construit)
        self.assertIn(('lot:3', 'group:Produits'), construit)
        self.assertIn(('lot:4', 'rule:Stock jamais négatif'), construit)
        self.assertIn(('lot:7', 'pipeline:ListeProduits/Chargement'), construit)
        # Tout élément constructible de la spec est couvert par un lot.
        couverts = {cible for _, cible in construit}
        for n in g['nodes']:
            if n['kind'] in ('data_model', 'endpoint_group', 'service', 'page', 'pipeline', 'business_rule'):
                self.assertIn(n['id'], couverts)
        self.assertEqual(_liens(g, 'next') & {('lot:2', 'lot:3')}, {('lot:2', 'lot:3')})

    def test_le_graphe_d_autrui_est_ferme(self):
        self.assertEqual(self.client_de('bob').get(f"/api/apps/{self.prete['id']}/graph/").status_code, 404)
        self.assertEqual(self.client_de('alice', azp='lab-admin').get(f"/api/apps/{self.prete['id']}/graph/").status_code, 403)
        self.assertEqual(self.alice.post(f"/api/apps/{self.prete['id']}/graph/", {}, format='json').status_code, 405)
        self.assertNotIn('CONFIDENTIELLE', self.alice.get(f"/api/apps/{self.prete['id']}/graph/").content.decode())


class GrapheReglesTests(SimpleTestCase):

    def test_selon_le_type_d_app(self):
        spec = spec_riche()
        spec['app_type'] = 'angular'
        ids = set(_par_id(graphe.graphe(spec)))
        self.assertIn('infra:frontend', ids)
        self.assertFalse(ids & {'infra:api', 'infra:database', 'infra:storage'})
        spec['app_type'] = 'django'
        g = graphe.graphe(spec)
        ids = set(_par_id(g))
        self.assertNotIn('infra:frontend', ids)
        self.assertIn(('infra:keycloak', 'infra:api'), _liens(g, 'flow'))
        self.assertEqual(_par_id(g)['infra:api']['detail'], '/gestion-stock')

    def test_spec_vide_ou_abimee(self):
        g = graphe.graphe({'name': 'Vide'})
        self.assertEqual([n['id'] for n in g['nodes']],
                         ['infra:groups', 'infra:keycloak', 'infra:frontend', 'infra:api', 'infra:database'])
        self.assertIn('aucun', _par_id(g)['infra:groups']['detail'])
        abimee = spec_riche()
        abimee['data_models'] += [{'name': 'Produit'}, {'name': None}, 'texte']        # doublon, sans nom, pas un objet
        abimee['endpoint_groups'][0]['endpoints'][0]['linked_model_name'] = 'Disparu'  # référence morte
        abimee['pages'][0]['pipelines'][0]['trigger_interaction'] = 'Inconnue'
        abimee['pages'][0]['service_ids'] = [999, 'x']
        g = graphe.graphe(abimee)
        noeuds = _par_id(g)
        self.assertEqual(len(noeuds), len(g['nodes']))
        for lien in g['links']:
            self.assertIn(lien['source'], noeuds)
            self.assertIn(lien['target'], noeuds)


def _spec_v2() -> dict:
    """spec_riche, avec des identifiants partout et les structures I1."""
    spec = spec_riche()
    for rang, e in enumerate(spec['endpoint_groups'][0]['endpoints']):
        e['id'] = 100 + rang
    spec['endpoint_groups'][1]['endpoints'][0]['id'] = 110
    spec['pages'][0]['interactions'][0]['id'] = 50
    spec['pages'][0]['pipelines'][0]['id'] = 40
    spec['roles'] = [{'name': 'manager', 'kind': 'keycloak_group', 'implies': ['lecteur']},
                     {'name': 'lecteur', 'kind': 'object_role', 'on_model': 'Produit'}]
    spec['jobs'] = [{'name': 'Recalcul', 'kind': 'async', 'trigger': 'POST /api/produits/',
                     'input_model': 'Produit', 'tracked_by': 'Mouvement'}]
    spec['integrations'] = [{'type': 'storage', 'mode': 'service_account'}]
    spec['external_apis'] = [{'name': 'Stripe', 'purpose': 'paiement', 'auth': 'app_key'}]
    spec['data_models'][0]['states'] = {
        'field': 'statut', 'initial': 'brouillon', 'values': ['brouillon', 'publie'],
        'transitions': [{'from': ['brouillon'], 'to': 'publie', 'by': ['role:manager'], 'action': 'POST /api/produits/'}]}
    return spec


def _spec_securite() -> dict:
    """Une page ouverte au groupe A dont le service appelle une route réservée au rôle B."""
    return {
        'name': 'Sécu', 'project_name': 'secu', 'app_type': 'django-angular', 'required_groups': ['A'],
        'roles': [{'name': 'B'}],
        'endpoint_groups': [{'id': 1, 'name': 'G', 'endpoints': [
            {'id': 2, 'method': 'GET', 'path': '/api/b/', 'operation': 'list', 'required_roles': ['B']},
            {'id': 3, 'method': 'GET', 'path': '/api/ouvert/', 'auth_required': False},
            {'id': 4, 'method': 'POST', 'path': '/api/hook/', 'auth': {'mode': 'hmac_signature'}}]}],
        'services': [{'id': 5, 'name': 'S', 'endpoint_group_ids': [1]}],
        'pages': [{'id': 6, 'name': 'P', 'route': '/p', 'required_roles': ['A'], 'service_ids': [5]},
                  {'id': 7, 'name': 'Vitrine', 'route': '/', 'public': True}],
    }


class GrapheV2Tests(SimpleTestCase):

    def test_cles_v1_conservees_et_tete_v2(self):
        g = graphe.graphe(spec_riche())
        self.assertGreaterEqual(set(g), {'scales', 'nodes', 'links', 'version', 'kinds', 'issues', 'matrices', 'sequences'})
        self.assertEqual(g['version'], 2)
        for cle in ('scales', 'nodes', 'links', 'issues', 'sequences'):
            self.assertIsInstance(g[cle], list)
        self.assertEqual([e['id'] for e in g['scales']],
                         ['overview', 'architecture', 'data', 'pipelines', 'roadmap',
                          'api', 'pages', 'security', 'lifecycles', 'jobs'])
        notations = {e['id']: e['notation'] for e in g['scales']}
        self.assertEqual(notations, {'overview': 'c4', 'architecture': 'c4', 'data': 'er', 'pipelines': 'sequence',
                                     'roadmap': 'kanban', 'api': 'tree', 'pages': 'sitemap', 'security': 'matrix',
                                     'lifecycles': 'statechart', 'jobs': 'timeline'})
        self.assertEqual(g['issues'], [])                                     # spec saine : rien à signaler
        noeuds = _par_id(g)
        for n in g['nodes']:
            self.assertGreaterEqual(set(n), {'id', 'kind', 'scale', 'label', 'parent', 'detail',
                                             'ref', 'edit', 'attrs', 'lots', 'appears_in', 'issues'})
            self.assertIn(n['scale'], n['appears_in'])
            self.assertEqual(set(n['edit']), {'route', 'query'})
            self.assertIn(n['kind'], g['kinds'])
            self.assertTrue(g['kinds'][n['kind']]['cat'].startswith('k-'))
        self.assertEqual([lien['id'] for lien in g['links']], [f'l{i}' for i in range(1, len(g['links']) + 1)])
        # Champs v1 des nœuds, inchangés.
        self.assertEqual(noeuds['model:Produit']['fields'][0], {'name': 'nom', 'type': 'string'})
        self.assertEqual(noeuds['step:ListeProduits/Chargement/0']['order'], 0)
        self.assertEqual(noeuds['endpoint:Produits/GET /api/produits/']['attrs'],
                         {'method': 'GET', 'path': '/api/produits/', 'operation': 'list', 'auth': 'jwt', 'model': 'Produit'})
        self.assertEqual(noeuds['endpoint:Produits/GET /api/vitrine/']['attrs']['auth'], 'public')
        relation = next(lien for lien in g['links'] if lien['kind'] == 'relation')
        self.assertEqual(relation['cardinality'], {'source': 'N', 'target': '1'})
        self.assertIsNone(next(lien for lien in g['links'] if lien['kind'] == 'contains')['cardinality'])

    def test_ref_et_edit_selon_la_table(self):
        g = graphe.graphe(_spec_v2())
        n = _par_id(g)
        attendu = {
            'model:Produit': ({'collection': 'data_models', 'id': 1}, '/models', {'modele': 1}),
            'group:Produits': ({'collection': 'endpoint_groups', 'id': 10}, '/endpoints', {'groupe': 10}),
            'endpoint:Produits/POST /api/produits/': ({'collection': 'endpoints', 'id': 101}, '/endpoints',
                                                      {'groupe': 10, 'endpoint': 101}),
            'page:ListeProduits': ({'collection': 'pages', 'id': 30}, '/pages-config', {'page': 30}),
            'pipeline:ListeProduits/Chargement': ({'collection': 'pipelines', 'id': 40}, '/pipelines',
                                                  {'page': 30, 'pipeline': 40}),
            'interaction:ListeProduits/Page chargée': ({'collection': 'interactions', 'id': 50}, '/pipelines', {'page': 30}),
            'role:manager': ({'collection': 'roles', 'id': None, 'name': 'manager'}, '/infra', {'section': 'roles'}),
            'job:Recalcul': ({'collection': 'jobs', 'id': None, 'name': 'Recalcul'}, '/infra', {'section': 'jobs'}),
            'integration:storage': ({'collection': 'integrations', 'id': None, 'name': 'storage'}, '/infra',
                                    {'section': 'integrations'}),
            'external_api:Stripe': ({'collection': 'external_apis', 'id': None, 'name': 'Stripe'}, '/infra',
                                    {'section': 'external_apis'}),
            'rule:Stock jamais négatif': ({'collection': 'business_rules', 'id': None, 'name': 'Stock jamais négatif'},
                                          '/infra', {'section': 'rules'}),
            'lot:2': ({'collection': 'lots', 'id': None, 'name': '2'}, '/preview', {'lot': 2}),
            'infra:groups': ({'collection': 'infra', 'id': None, 'name': 'groups'}, '/infra', {'section': 'meta'}),
        }
        for ident, (ref, route, query) in attendu.items():
            self.assertEqual(n[ident]['ref'], ref, ident)
            self.assertEqual(n[ident]['edit'], {'route': route, 'query': query}, ident)
        # Étape → édition de son pipeline ; état et transition → celle de leur modèle.
        self.assertEqual(n['step:ListeProduits/Chargement/0']['edit'], n['pipeline:ListeProduits/Chargement']['edit'])
        self.assertEqual(n['state:Produit/brouillon']['edit'], n['model:Produit']['edit'])
        self.assertEqual(n['transition:Produit/0']['edit'], n['model:Produit']['edit'])
        # Élément sans identifiant numérique : id null et nom.
        sans_id = _par_id(graphe.graphe(spec_riche()))['endpoint:Produits/GET /api/produits/']
        self.assertEqual(sans_id['ref'], {'collection': 'endpoints', 'id': None, 'name': 'GET /api/produits/'})
        self.assertEqual(sans_id['edit'], {'route': '/endpoints', 'query': {'groupe': 10, 'endpoint': None}})

    def test_lots_et_appartenance_aux_vues(self):
        n = _par_id(graphe.graphe(_spec_v2()))
        self.assertEqual(n['model:Produit']['lots'], [2])
        self.assertEqual(n['group:Produits']['lots'], [3])
        self.assertEqual(n['endpoint:Produits/GET /api/produits/']['lots'], [3])     # avec son groupe
        self.assertEqual(n['lot:2']['lots'], [])
        self.assertEqual(n['endpoint:Produits/GET /api/produits/']['appears_in'], ['architecture', 'api', 'security'])
        self.assertEqual(n['model:Produit']['appears_in'], ['data', 'api', 'lifecycles', 'jobs'])
        self.assertEqual(n['page:ListeProduits']['appears_in'], ['architecture', 'pages', 'security'])

    def test_doublon_signale(self):
        spec = spec_riche()
        spec['data_models'].append({'id': 99, 'name': 'Produit', 'fields': []})
        g = graphe.graphe(spec)
        doublons = [i for i in g['issues'] if i['code'] == 'duplicate_name']
        self.assertEqual(len(doublons), 1)
        self.assertEqual(doublons[0]['node'], 'model:Produit')
        self.assertEqual(_par_id(g)['model:Produit']['ref']['id'], 1)                 # le premier est gardé
        self.assertEqual([i['code'] for i in _par_id(g)['model:Produit']['issues']], ['duplicate_name'])

    def test_reference_inconnue_signalee_avec_la_valeur_fautive(self):
        spec = spec_riche()
        spec['endpoint_groups'][0]['endpoints'][0]['linked_model_name'] = 'Disparu'
        g = graphe.graphe(spec)
        source = 'endpoint:Produits/GET /api/produits/'
        pendantes = [i for i in g['issues'] if i['code'] == 'dangling_ref']
        self.assertEqual(len(pendantes), 1, g['issues'])                    # la vitrine (modèle vide) n'est pas signalée
        self.assertEqual(pendantes[0]['node'], source)
        self.assertIn('Disparu', pendantes[0]['message'])
        self.assertIn('Disparu', _par_id(g)[source]['issues'][0]['message'])
        self.assertNotIn((source, 'model:Disparu'), _liens(g))               # le lien reste non émis

    def test_matrice_de_securite_et_incoherence(self):
        g = graphe.graphe(_spec_securite())
        m = g['matrices']['security']
        self.assertEqual(m['rows'], ['public', 'groupe:A', 'role:B'])
        self.assertEqual(m['cols'], ['endpoint:G/GET /api/b/', 'endpoint:G/GET /api/ouvert/', 'endpoint:G/POST /api/hook/',
                                     'page:P', 'page:Vitrine'])
        self.assertEqual(m['cells'], [
            ['deny', 'allow', 'allow', 'deny', 'allow'],
            ['deny', 'allow', 'allow', 'inconsistent', 'allow'],
            ['allow', 'allow', 'allow', 'deny', 'allow'],
        ])
        self.assertEqual(list(m['notes']), ['1,3'])
        self.assertIn('GET /api/b/', m['notes']['1,3'])
        # La même page sans rôle requis sur la route : plus d'incohérence.
        spec = _spec_securite()
        spec['endpoint_groups'][0]['endpoints'][0]['required_roles'] = []
        self.assertEqual(graphe.graphe(spec)['matrices']['security']['notes'], {})

    def test_matrice_crud(self):
        m = graphe.graphe(spec_riche())['matrices']['crud']
        self.assertEqual(m['rows'], ['Produit', 'Mouvement'])
        self.assertEqual(m['cols'], ['list', 'create', 'retrieve', 'update', 'partial_update', 'delete', 'custom'])
        self.assertEqual(m['cells'][0], [['GET /api/produits/'], ['POST /api/produits/'], [], [], [], [], []])
        self.assertEqual(m['cells'][1], [['GET /api/ouvert/'], [], [], [], [], [], []])

    def test_sequence_depuis_un_pipeline(self):
        g = graphe.graphe(spec_riche())
        self.assertEqual(len(g['sequences']), 1)
        s = g['sequences'][0]
        self.assertEqual(s['pipeline'], 'pipeline:ListeProduits/Chargement')
        self.assertEqual(s['lifelines'], ['user', 'page:ListeProduits', 'service:ProduitService', 'group:Produits',
                                          'infra:database'])
        self.assertEqual(s['messages'][0], {'from': 0, 'to': 1, 'label': 'Page chargée'})
        self.assertEqual(s['messages'][1]['label'], 'ProduitService.getAll()')
        self.assertEqual([(x['from'], x['to']) for x in s['messages']], [(0, 1), (1, 2), (2, 3), (3, 4)])
        noeuds = _par_id(g)
        for ligne in s['lifelines'][1:]:
            self.assertIn(ligne, noeuds)

    def test_cycles_de_vie_disponibles_seulement_avec_des_etats(self):
        echelles = {e['id']: e for e in graphe.graphe(spec_riche())['scales']}
        self.assertFalse(echelles['lifecycles']['available'])
        self.assertTrue(echelles['lifecycles']['reason'])
        self.assertFalse(echelles['jobs']['available'])
        self.assertTrue(echelles['api']['available'])
        self.assertNotIn('reason', echelles['api'])
        g = graphe.graphe(_spec_v2())
        echelles = {e['id']: e for e in g['scales']}
        self.assertTrue(echelles['lifecycles']['available'])
        self.assertTrue(echelles['jobs']['available'])
        n = _par_id(g)
        self.assertEqual(n['state:Produit/brouillon']['parent'], 'model:Produit')
        self.assertEqual(n['state:Produit/brouillon']['scale'], 'lifecycles')
        self.assertTrue(n['state:Produit/brouillon']['attrs']['initial'])
        self.assertEqual(n['transition:Produit/0']['attrs']['to'], 'publie')
        liens = _liens(g, 'transition')
        self.assertEqual(liens, {('state:Produit/brouillon', 'transition:Produit/0'),
                                 ('transition:Produit/0', 'state:Produit/publie')})
        self.assertIn(('endpoint:Produits/POST /api/produits/', 'transition:Produit/0'), _liens(g, 'performs'))
        # Une transition vers un état inconnu est signalée.
        spec = _spec_v2()
        spec['data_models'][0]['states']['transitions'].append({'from': ['publie'], 'to': 'archive'})
        issues = graphe.graphe(spec)['issues']
        self.assertTrue(any(i['code'] == 'dangling_ref' and 'archive' in i['message'] for i in issues), issues)

    def test_roles_jobs_integrations_api_externes(self):
        g = graphe.graphe(_spec_v2())
        self.assertEqual(g['issues'], [])
        n = _par_id(g)
        self.assertEqual((n['role:manager']['kind'], n['job:Recalcul']['kind'], n['integration:storage']['kind'],
                          n['external_api:Stripe']['kind']), ('role', 'job', 'integration', 'external_api'))
        self.assertEqual(n['job:Recalcul']['scale'], 'jobs')
        tous = _liens(g)
        for attendu in (('job:Recalcul', 'model:Produit'), ('job:Recalcul', 'model:Mouvement'),
                        ('role:manager', 'role:lecteur'), ('role:lecteur', 'model:Produit'),
                        ('endpoint:Produits/POST /api/produits/', 'job:Recalcul')):
            self.assertIn(attendu, tous)
        for genre in ('role', 'job', 'integration', 'external_api', 'state', 'transition'):
            self.assertIn(genre, g['kinds'])
        spec = _spec_v2()
        spec['jobs'][0]['tracked_by'] = 'Fantome'
        self.assertIn('Fantome', graphe.graphe(spec)['issues'][0]['message'])

    def test_elements_de_lot_de_genre_inconnu_ignores(self):
        lots = [{'number': 2, 'title': 'x', 'objective': '', 'family': 'f', 'tokens': 1,
                 'elements': [{'kind': 'mystere', 'name': 'x'}, {'kind': 'job', 'name': 'Recalcul'},
                              {'kind': 'role', 'name': 'manager'}, 'pas un objet']}]
        g = graphe.graphe(_spec_v2(), lots)
        self.assertEqual(_liens(g, 'builds'), {('lot:2', 'job:Recalcul'), ('lot:2', 'role:manager')})
        self.assertEqual(_par_id(g)['job:Recalcul']['lots'], [2])

    def test_deterministe(self):
        for spec in (spec_riche(), _spec_v2(), _spec_securite()):
            a = json.dumps(graphe.graphe(spec), sort_keys=True)
            b = json.dumps(graphe.graphe(copy.deepcopy(spec)), sort_keys=True)
            self.assertEqual(a, b)

    def test_aucun_lien_ne_pend_et_parents_presents(self):
        for spec in (spec_riche(), _spec_v2(), _spec_securite()):
            g = graphe.graphe(spec)
            noeuds = _par_id(g)
            self.assertEqual(len(noeuds), len(g['nodes']))
            self.assertEqual(len({lien['id'] for lien in g['links']}), len(g['links']))
            for lien in g['links']:
                self.assertIn(lien['source'], noeuds)
                self.assertIn(lien['target'], noeuds)
            for n in g['nodes']:
                self.assertTrue(n['parent'] is None or n['parent'] in noeuds, n)
            for s in g['sequences']:
                for x in s['messages']:
                    self.assertTrue(0 <= x['from'] < len(s['lifelines']) and 0 <= x['to'] < len(s['lifelines']))

    def test_cles_de_mauvais_type_sans_exception(self):
        spec = _spec_v2()
        spec.update({'roles': 'x', 'jobs': [1, None, {'name': None}], 'integrations': {'a': 1},
                     'external_apis': [{'name': ['liste']}], 'required_groups': 'pas une liste'})
        spec['data_models'][0].update({'states': 'x', 'access': [], 'constraints': 'x'})
        spec['data_models'][1]['states'] = {'values': 'x', 'transitions': [None, {'from': 'x', 'to': 3}]}
        spec['endpoint_groups'][0]['endpoints'][0].update({'auth': 'jwt', 'required_roles': None})
        spec['pages'][0].update({'public': 'yes', 'required_roles': 'A', 'service_ids': [None, True, 3.5, [1]]})
        g = graphe.graphe(spec)
        json.dumps(g, sort_keys=True)
        for vide in ({}, {'name': 'Vide', 'data_models': None, 'pages': 'x'}):
            g = graphe.graphe(vide)
            self.assertFalse(next(e for e in g['scales'] if e['id'] == 'security')['available'])
