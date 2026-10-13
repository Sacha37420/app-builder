"""Lot 6 — le graphe d'une spécification, à toutes les échelles."""
from django.test import SimpleTestCase

from api import graphe, remise

from .remise import _AvecSpecs, spec_riche

__all__ = ['VueEnsembleTests', 'GrapheReglesTests']


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
        self.assertEqual(set(g), {'spec', 'scales', 'nodes', 'links'})
        self.assertEqual([e['id'] for e in g['scales']], ['overview', 'architecture', 'data', 'pipelines', 'roadmap'])
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
