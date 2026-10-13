"""Lot 4 — une spécification décrit une app que le moteur du lab sait créer."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase

from api import conformite, patching, views
from api.models import AppSpec, DataModel

from .socle import Base, _spec_complete

__all__ = ['ConformiteCadricielTests', 'ConformiteReglesTests', 'MigrationCadricielTests']


def _prete() -> dict:
    return {**_spec_complete(), 'project_name': 'ma-boutique'}


class ConformiteCadricielTests(Base):

    def setUp(self):
        super().setUp()
        self.alice = self.client_de('alice')

    def creer(self, spec=None, attendu=201):
        resp = self.alice.post('/api/apps/', spec if spec is not None else _prete(), format='json')
        self.assertEqual(resp.status_code, attendu, resp.content)
        return resp.json()

    def lab(self, pk, client=None):
        resp = (client or self.alice).get(f'/api/apps/{pk}/lab/')
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()

    def codes(self, pk):
        return [b['code'] for b in self.lab(pk)['blockers']]

    # ── Type d'app ────────────────────────────────────────────────────────────

    def test_type_refuse_hors_liste(self):
        for app_type in ('spring', 'spring-angular', 'rails', ''):
            with self.subTest(app_type=app_type):
                refus = self.creer({**_prete(), 'app_type': app_type}, attendu=400)
                self.assertIn('app_type', refus)
        self.assertEqual(AppSpec.objects.count(), 0)
        for app_type in conformite.TYPES_CONSTRUCTIBLES:
            self.assertEqual(self.creer({**_prete(), 'app_type': app_type})['app_type'], app_type)
        # Par défaut : Django + Angular.
        self.assertEqual(self.creer({'name': 'Sans type'})['app_type'], 'django-angular')

    def test_on_ne_passe_pas_une_spec_existante_a_un_type_non_constructible(self):
        spec = self.creer()
        for methode in (self.alice.patch, self.alice.put):
            resp = methode(f"/api/apps/{spec['id']}/", {**spec, 'app_type': 'spring'}, format='json')
            self.assertEqual(resp.status_code, 400)
        self.assertEqual(AppSpec.objects.get(pk=spec['id']).app_type, 'django-angular')

    def test_une_spec_ancienne_d_un_autre_type_reste_lisible_et_modifiable_mais_pas_prete(self):
        ancienne = AppSpec.objects.create(name='Vieille', app_type='spring-angular', project_name='vieille',
                                          owner_email='alice@ssolab.local', required_groups=['famille'])
        DataModel.objects.create(app=ancienne, name='Chose', fields=[])
        url = f'/api/apps/{ancienne.pk}/'
        spec = self.alice.get(url).json()
        self.assertEqual(spec['app_type'], 'spring-angular')
        # L'enregistrement automatique renvoie la spec telle quelle : il ne doit pas échouer.
        spec['name'] = 'Vieille, retouchée'
        self.assertEqual(self.alice.put(url, spec, format='json').status_code, 200)
        etat = self.lab(ancienne.pk)
        self.assertFalse(etat['ready'])
        self.assertEqual([b['code'] for b in etat['blockers']], ['app_type'])
        self.assertFalse(etat['footprint']['constructible'])
        # Changer pour un type constructible la rend prête ; aucun retour en arrière possible.
        self.assertEqual(self.alice.patch(url, {'app_type': 'django'}, format='json').status_code, 200)
        self.assertTrue(self.lab(ancienne.pk)['ready'])
        self.assertEqual(self.alice.patch(url, {'app_type': 'spring-angular'}, format='json').status_code, 400)

    # ── Nom de projet ─────────────────────────────────────────────────────────

    def test_slug_invalide_refuse(self):
        invalides = ['Ma-Boutique', 'ma boutique', '1boutique', 'ab', 'boutique-', '-boutique', 'ma--boutique',
                     'boutique_test', 'é-picerie', 'a' * 41, 'ma-boutique/', '../etc']
        for nom in invalides:
            with self.subTest(nom=nom):
                refus = self.creer({**_prete(), 'project_name': nom}, attendu=400)
                self.assertIn('project_name', refus)
        self.assertEqual(AppSpec.objects.count(), 0)
        for nom in ('abc', 'ma-boutique', 'stock2', 'a' * 40):
            with self.subTest(nom=nom):
                self.assertEqual(self.creer({**_prete(), 'project_name': nom})['project_name'], nom)

    def test_le_nom_de_projet_est_distinct_du_titre_et_peut_attendre(self):
        spec = self.creer({**_spec_complete(), 'name': 'Ma Boutique à Moi'})
        self.assertEqual(spec['project_name'], '')
        self.assertEqual(self.codes(spec['id']), ['project_name'])
        resp = self.alice.patch(f"/api/apps/{spec['id']}/", {'project_name': 'ma-boutique'}, format='json')
        self.assertEqual((resp.status_code, resp.json()['name']), (200, 'Ma Boutique à Moi'))
        self.assertTrue(self.lab(spec['id'])['ready'])

    def test_un_patch_ia_pose_le_nom_de_projet_et_un_nom_invalide_le_fait_refuser(self):
        spec = self.creer(_spec_complete())
        url = f"/api/apps/{spec['id']}/patch/"
        resp = self.alice.post(url, {'patch': {'set_meta': {'project_name': 'Ma Boutique'}}}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('project_name', ' '.join(resp.json()['details']))
        resp = self.alice.post(url, {'patch': {'set_meta': {'project_name': 'ma-boutique'}}}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['spec']['project_name'], 'ma-boutique')
        self.assertIn('nom de projet → ma-boutique', resp.json()['application']['summary'])

    # ── Groupes requis ────────────────────────────────────────────────────────

    def test_spec_sans_groupe_non_prete(self):
        spec = self.creer({**_prete(), 'required_groups': []})
        etat = self.lab(spec['id'])
        self.assertFalse(etat['ready'])
        self.assertEqual(etat['blockers'], [{'code': 'required_groups',
                                             'message': "Aucun groupe requis : l'app serait ouverte à tout compte du lab."}])
        self.alice.patch(f"/api/apps/{spec['id']}/", {'required_groups': [' famille ', 'famille', '']}, format='json')
        etat = self.lab(spec['id'])
        self.assertTrue(etat['ready'])
        self.assertEqual(etat['footprint']['keycloak']['required_groups'], ['famille'])
        refus = self.alice.patch(f"/api/apps/{spec['id']}/", {'required_groups': 'famille'}, format='json')
        self.assertEqual(refus.status_code, 400)

    # ── Fichiers : service storage, jamais de champ fichier ───────────────────

    def test_champ_file_refuse(self):
        avec_fichier = _prete()
        avec_fichier['data_models'][0]['fields'].append({'name': 'photo', 'type': 'file'})
        refus = self.creer(avec_fichier, attendu=400)
        self.assertIn('storage', str(refus))
        self.assertEqual(AppSpec.objects.count(), 0)
        # Sur une spec existante non plus, ni par PUT ni par PATCH.
        spec = self.creer()
        for methode in (self.alice.put, self.alice.patch):
            resp = methode(f"/api/apps/{spec['id']}/", {**spec, 'data_models': avec_fichier['data_models']},
                           format='json')
            self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.alice.get(f"/api/apps/{spec['id']}/").json()['data_models'][0]['fields'],
                         [{'name': 'nom', 'type': 'string'}])
        # La référence au service storage, elle, est acceptée.
        avec_fichier['data_models'][0]['fields'][-1]['type'] = 'storage_file'
        cree = self.creer({**avec_fichier, 'project_name': 'avec-photo'})
        etat = self.lab(cree['id'])
        self.assertTrue(etat['ready'])
        self.assertEqual(etat['footprint']['storage']['fields'], ['Produit.photo'])
        self.assertTrue(etat['footprint']['storage']['used'])

    def test_un_patch_ia_ne_fait_jamais_entrer_un_champ_fichier(self):
        spec = self.creer()
        for brut in ('file', 'image', 'upload', 'FILE'):
            resp = self.alice.post(f"/api/apps/{spec['id']}/patch/", {'patch': {'data_models': [
                {'name': 'Produit', 'fields': [{'name': f'piece_{brut.lower()}', 'type': brut}]}]}}, format='json')
            self.assertEqual(resp.status_code, 200, resp.content)
        types = {f['name']: f['type'] for f in resp.json()['spec']['data_models'][0]['fields']}
        self.assertEqual(set(types.values()) - {'string'}, {'storage_file'})
        self.assertNotIn('file_field', self.codes(spec['id']))

    def _ancienne_avec_fichier(self):
        ancienne = AppSpec.objects.create(name='Vieille', project_name='vieille', owner_email='alice@ssolab.local',
                                          required_groups=['famille'])
        DataModel.objects.create(app=ancienne, name='Plat', fields=[
            {'name': 'nom', 'type': 'string'}, {'name': 'photo', 'type': 'file'}])
        return ancienne

    def test_un_champ_fichier_deja_present_reste_enregistrable_mais_bloque_la_remise(self):
        ancienne = self._ancienne_avec_fichier()
        url = f'/api/apps/{ancienne.pk}/'
        spec = self.alice.get(url).json()
        spec['description'] = 'retouchée'
        self.assertEqual(self.alice.put(url, spec, format='json').status_code, 200)
        etat = self.lab(ancienne.pk)
        self.assertEqual([b['code'] for b in etat['blockers']], ['file_field'])
        self.assertIn('Plat.photo', etat['blockers'][0]['message'])
        self.assertEqual(etat['footprint']['storage']['legacy_file_fields'], ['Plat.photo'])
        # Mais on n'en ajoute pas un second à la faveur du premier.
        spec['data_models'][0]['fields'].append({'name': 'menu_pdf', 'type': 'file'})
        self.assertEqual(self.alice.put(url, spec, format='json').status_code, 400)
        # Conversion : par l'éditeur, ou par un patch.
        resp = self.alice.post(f'{url}patch/', {'patch': {'data_models': [
            {'name': 'Plat', 'fields': [{'name': 'photo', 'type': 'storage_file'}]}]}}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(self.lab(ancienne.pk)['ready'])
        # Une fois converti, le type « file » ne revient plus.
        spec = self.alice.get(url).json()
        spec['data_models'][0]['fields'][1]['type'] = 'file'
        self.assertEqual(self.alice.put(url, spec, format='json').status_code, 400)

    def test_annuler_un_patch_rend_la_spec_d_avant_meme_avec_un_ancien_champ_fichier(self):
        ancienne = self._ancienne_avec_fichier()
        url = f'/api/apps/{ancienne.pk}/'
        application = self.alice.post(f'{url}patch/', {'patch': {'data_models': [
            {'name': 'Plat', 'fields': [{'name': 'photo', 'type': 'storage_file'}]}]}}, format='json').json()
        resp = self.alice.post(f"{url}patches/{application['application']['id']}/undo/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['spec']['data_models'][0]['fields'][1], {'name': 'photo', 'type': 'file'})

    # ── Routes publiques, email, règles métier ────────────────────────────────

    def test_route_publique_decision_explicite_visible_dans_l_empreinte(self):
        spec = _prete()
        spec['endpoint_groups'][0]['endpoints'].append(
            {'method': 'GET', 'path': '/api/carte/', 'auth_required': False,
             'public_reason': 'La carte est consultée sans compte.'})
        spec['endpoint_groups'][0]['endpoints'].append({'method': 'GET', 'path': '/api/ouvert/', 'auth_required': False})
        cree = self.creer(spec)
        publiques = self.lab(cree['id'])['footprint']['public_routes']
        self.assertEqual(publiques, [
            {'method': 'GET', 'path': '/api/carte/', 'group': 'Produits', 'reason': 'La carte est consultée sans compte.'},
            {'method': 'GET', 'path': '/api/ouvert/', 'group': 'Produits', 'reason': ''}])
        # Le patch IA porte la justification.
        resp = self.alice.post(f"/api/apps/{cree['id']}/patch/", {'patch': {'endpoint_groups': [{'name': 'Produits', 'endpoints': [
            {'method': 'GET', 'path': '/api/ouvert/', 'public_reason': 'Page vitrine.'}]}]}}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self.lab(cree['id'])['footprint']['public_routes'][1]['reason'], 'Page vitrine.')

    def test_regles_metier_structurees_fusionnees_par_titre(self):
        spec = self.creer({**_prete(), 'business_rules': [{'title': ' Stock positif ', 'description': 'Jamais négatif.'}]})
        self.assertEqual(spec['business_rules'], [{'title': 'Stock positif', 'description': 'Jamais négatif.'}])
        url = f"/api/apps/{spec['id']}/patch/"
        resp = self.alice.post(url, {'patch': {'business_rules': [
            {'title': 'Stock positif', 'description': 'Une sortie supérieure au stock est refusée.'},
            {'title': 'Commande payée figée'}], 'set_meta': {'uses_email': True}}}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        apres = resp.json()['spec']
        self.assertEqual(apres['business_rules'], [
            {'title': 'Stock positif', 'description': 'Une sortie supérieure au stock est refusée.'},
            {'title': 'Commande payée figée', 'description': ''}])
        self.assertTrue(apres['uses_email'])
        self.assertIn('2 règle(s) métier', resp.json()['application']['summary'])
        self.assertTrue(self.lab(spec['id'])['footprint']['email']['used'])
        apres = self.alice.post(url, {'patch': {'remove_business_rules': ['Stock positif']}}, format='json').json()['spec']
        self.assertEqual([r['title'] for r in apres['business_rules']], ['Commande payée figée'])
        # Un patch qui n'en parle pas ne les efface pas.
        apres = self.alice.post(url, {'patch': {'data_models': [{'name': 'Client'}]}}, format='json').json()['spec']
        self.assertEqual(len(apres['business_rules']), 1)
        for mauvaises in ('texte', [{'description': 'sans titre'}], ['texte']):
            with self.subTest(mauvaises=mauvaises):
                resp = self.alice.patch(f"/api/apps/{spec['id']}/", {'business_rules': mauvaises}, format='json')
                self.assertEqual(resp.status_code, 400)

    # ── Empreinte dans le lab ─────────────────────────────────────────────────

    def test_empreinte_selon_le_type(self):
        spec = self.creer()
        e = self.lab(spec['id'])['footprint']
        self.assertEqual([c['name'] for c in e['containers']], ['ma-boutique-backend', 'ma-boutique-frontend'])
        self.assertEqual(e['paths'], {'frontend': '/ma-boutique', 'api': '/ma-boutique-api'})
        self.assertEqual(e['keycloak']['client_id'], 'ma-boutique')
        self.assertEqual(e['database']['schema'], 'ma_boutique')
        self.assertFalse(e['storage']['used'])
        self.alice.patch(f"/api/apps/{spec['id']}/", {'app_type': 'django'}, format='json')
        e = self.lab(spec['id'])['footprint']
        self.assertEqual(([c['name'] for c in e['containers']], e['paths']),
                         (['ma-boutique-app'], {'frontend': None, 'api': '/ma-boutique'}))
        self.alice.patch(f"/api/apps/{spec['id']}/", {'app_type': 'angular'}, format='json')
        e = self.lab(spec['id'])['footprint']
        self.assertEqual((e['paths'], e['database']), ({'frontend': '/ma-boutique', 'api': None}, None))

    def test_spec_vide_et_references_mortes_bloquent(self):
        vide = self.creer({'name': 'Vide', 'project_name': 'vide', 'required_groups': ['famille']})
        self.assertEqual(self.codes(vide['id']), ['empty'])
        spec = self.creer()
        produits = next(g for g in spec['endpoint_groups'] if g['name'] == 'Produits')
        produits['endpoints'][0]['linked_model_name'] = 'Disparu'
        self.alice.put(f"/api/apps/{spec['id']}/", spec, format='json')
        etat = self.lab(spec['id'])
        self.assertEqual([b['code'] for b in etat['blockers']], ['orphan_reference'])
        self.assertIn('Disparu', etat['blockers'][0]['message'])

    def test_la_vue_lab_d_autrui_est_fermee(self):
        spec = self.creer()
        self.assertEqual(self.client_de('bob').get(f"/api/apps/{spec['id']}/lab/").status_code, 404)
        self.assertEqual(self.client_de('alice', azp='lab-admin').get(f"/api/apps/{spec['id']}/lab/").status_code, 403)
        self.assertEqual(self.alice.post(f"/api/apps/{spec['id']}/lab/", {}, format='json').status_code, 405)


class ConformiteReglesTests(SimpleTestCase):

    def test_meme_regle_de_forme_que_check_app_name(self):
        # scripts/check-app-name.sh, règle 1 : ^[a-z][a-z0-9-]{1,38}[a-z0-9]$ et pas de « -- ».
        for nom in ('abc', 'a-b', 'app2', 'x' * 40):
            self.assertIsNone(conformite.erreur_nom_de_projet(nom), nom)
        for nom in ('', 'ab', 'a-', 'A-b', 'a--b', 'x' * 41, None, 12, 'a b', 'a\nb'):
            self.assertIsNotNone(conformite.erreur_nom_de_projet(nom), nom)

    def test_le_prompt_ne_contredit_plus_le_cadriciel(self):
        for prompt in (views._build_system_prompt({}), views._build_patch_system_prompt({})):
            self.assertIn('storage_file', prompt)
            self.assertNotIn('json/file', prompt)
            self.assertIn('project_name', prompt)
            self.assertIn('business_rules', prompt)
            self.assertIn('public_reason', prompt)
        conversation = views._build_system_prompt({})
        for attendu in ('moteur du lab', 'send_mail', 'Foyer', 'storage', 'Angular seul'):
            self.assertIn(attendu, conversation)
        self.assertNotIn('Spring Boot', conversation)

    def test_un_patch_de_regles_seules_a_du_contenu(self):
        self.assertTrue(views._patch_has_content({'business_rules': [{'title': 'x'}]}))
        self.assertTrue(views._patch_has_content({'remove_business_rules': ['x']}))

    def test_la_fusion_garde_les_champs_du_cadriciel(self):
        avant = {'name': 'B', 'project_name': 'ma-boutique', 'uses_email': True,
                 'business_rules': [{'title': 'R', 'description': 'd'}]}
        apres = patching.fusionner(avant, {'data_models': [{'name': 'Produit'}]})
        self.assertEqual((apres['project_name'], apres['uses_email'], apres['business_rules']),
                         ('ma-boutique', True, [{'title': 'R', 'description': 'd'}]))
        apres = patching.fusionner(avant, {'data_models': [{'name': 'Produit'}]}, 'replace')
        self.assertEqual(apres['project_name'], 'ma-boutique')


class MigrationCadricielTests(TransactionTestCase):
    """La migration 0009 n'ajoute que des colonnes : rien de ce qui existe n'est perdu."""

    def test_les_donnees_d_avant_survivent(self):
        executeur = MigrationExecutor(connection)
        try:
            executeur.migrate([('api', '0008_patch_applications')])
            apps = executeur.loader.project_state([('api', '0008_patch_applications')]).apps
            Spec, Modele = apps.get_model('api', 'AppSpec'), apps.get_model('api', 'DataModel')
            Groupe, Point = apps.get_model('api', 'EndpointGroup'), apps.get_model('api', 'Endpoint')
            spec = Spec.objects.create(name='Avant', app_type='spring', owner_email='alice@ssolab.local',
                                       required_groups=['famille'], chat_history=[{'role': 'user', 'content': 'x'}])
            Modele.objects.create(app=spec, name='Plat', fields=[{'name': 'photo', 'type': 'file'}])
            groupe = Groupe.objects.create(app=spec, name='Plats')
            Point.objects.create(group=groupe, method='GET', path='/api/plats/', auth_required=False)

            executeur = MigrationExecutor(connection)
            executeur.migrate([('api', '0009_cadriciel')])
            apres = AppSpec.objects.get(pk=spec.pk)
            self.assertEqual((apres.name, apres.app_type, apres.owner_email, apres.required_groups, apres.chat_history),
                             ('Avant', 'spring', 'alice@ssolab.local', ['famille'], [{'role': 'user', 'content': 'x'}]))
            self.assertEqual((apres.project_name, apres.business_rules, apres.uses_email), ('', [], False))
            self.assertEqual(apres.data_models.get().fields, [{'name': 'photo', 'type': 'file'}])
            point = apres.endpoint_groups.get().endpoints.get()
            self.assertEqual((point.path, point.auth_required, point.public_reason), ('/api/plats/', False, ''))
        finally:
            MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
