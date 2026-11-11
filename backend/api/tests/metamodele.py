"""Chantier app-builder-v2 — métamodèle v2 (I1) : sérialiseur, patch, conformité, migration."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase

from api import conformite, patching
from api.models import AppSpec

from .socle import Base, _spec_complete

__all__ = ['MetamodeleSerialiseurTests', 'MetamodelePatchTests', 'VerifierTests', 'MigrationMetamodeleV2Tests']


def spec_v2() -> dict:
    """Une spec qui porte toutes les clés I1."""
    return {
        'name': 'Ventes', 'project_name': 'ventes', 'app_type': 'django-angular', 'required_groups': ['vendeurs'],
        'business_rules': [{'title': 'Stock positif', 'description': 'jamais négatif', 'applies_to': 'Produit',
                            'kind': 'invariant', 'enforced_by': ['POST /api/commandes/']}],
        'roles': [{'name': 'manager', 'kind': 'keycloak_group', 'description': 'gère', 'implies': ['vendeur']},
                  {'name': 'vendeur', 'kind': 'keycloak_group'}],
        'jobs': [{'name': 'Relance', 'kind': 'scheduled', 'trigger': 'every:30min', 'input_model': 'Commande',
                  'tracked_by': 'Commande', 'concurrency': '', 'heavy': False}],
        'integrations': [{'type': 'storage', 'mode': 'user_token'}, {'type': 'email'}],
        'external_apis': [{'name': 'Stripe', 'purpose': 'paiement', 'auth': 'app_key', 'called_from': 'backend'}],
        'extensions': {'data_io': [{'name': 'Import CSV', 'direction': 'import', 'format': 'csv', 'model': 'Produit',
                                    'mode': 'upsert', 'async': False}],
                       'notifications': [{'event': 'Commande.payee', 'channel': 'email', 'to': 'owner'}]},
        'data_models': [
            {'name': 'Produit', 'kind': 'reference', 'fields': [
                {'name': 'nom', 'type': 'string'},
                {'name': 'categorie', 'type': 'enum', 'values': ['a', 'b']}],
             'access': {'scope': 'group', 'rules': [{'action': 'update', 'who': ['role:manager']}]},
             'constraints': [{'kind': 'unique', 'fields': ['nom']}]},
            {'name': 'Commande', 'fields': [{'name': 'statut', 'type': 'string'},
                                            {'name': 'owner_email', 'type': 'email'}],
             'relationships': [{'name': 'produit', 'rel_type': 'FK', 'to_model': 'Produit'}],
             'access': {'scope': 'owner', 'owner_field': 'owner_email'},
             'states': {'field': 'statut', 'initial': 'brouillon', 'values': ['brouillon', 'payee'],
                        'transitions': [{'from': ['brouillon'], 'to': 'payee', 'by': ['owner'],
                                         'action': 'POST /api/commandes/{id}/payer/'}],
                        'frozen_in': ['payee']}},
        ],
        'endpoint_groups': [{'id': -1, 'name': 'Commandes', 'endpoints': [
            {'method': 'POST', 'path': '/api/commandes/', 'operation': 'create', 'linked_model_name': 'Commande'},
            {'method': 'POST', 'path': '/api/stripe/webhook/', 'auth': {'mode': 'hmac_signature', 'caller': 'stripe',
                                                                        'reason': 'appelé par Stripe'}},
        ]}],
        'services': [{'id': -10, 'name': 'CommandeService', 'endpoint_group_ids': [-1]}],
        'pages': [{'name': 'Vitrine', 'route': '/vitrine', 'layout': 'canvas', 'service_ids': [-10],
                   'public': True, 'public_reason': 'vitrine', 'required_roles': []},
                  {'name': 'Gestion', 'route': '/gestion', 'layout': 'settings', 'required_roles': ['manager']}],
    }


class MetamodeleSerialiseurTests(Base):

    def setUp(self):
        super().setUp()
        self.alice = self.client_de('alice')

    def test_toutes_les_cles_v2_aller_retour(self):
        resp = self.alice.post('/api/apps/', spec_v2(), format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        relue = self.alice.get(f"/api/apps/{resp.json()['id']}/").json()
        attendu = spec_v2()
        for cle in ('roles', 'jobs', 'integrations', 'external_apis', 'extensions', 'business_rules'):
            self.assertEqual(relue[cle], attendu[cle], cle)
        produit = next(m for m in relue['data_models'] if m['name'] == 'Produit')
        self.assertEqual((produit['kind'], produit['access']['scope'], produit['constraints'][0]['kind']),
                         ('reference', 'group', 'unique'))
        commande = next(m for m in relue['data_models'] if m['name'] == 'Commande')
        self.assertEqual(commande['states']['values'], ['brouillon', 'payee'])
        self.assertEqual(commande['kind'], 'entity')
        vitrine = next(p for p in relue['pages'] if p['name'] == 'Vitrine')
        self.assertEqual((vitrine['public'], vitrine['public_reason'], vitrine['layout']), (True, 'vitrine', 'canvas'))
        gestion = next(p for p in relue['pages'] if p['name'] == 'Gestion')
        self.assertEqual((gestion['required_roles'], gestion['public']), (['manager'], False))

    def test_coherence_de_l_authentification(self):
        relue = self.alice.post('/api/apps/', spec_v2(), format='json').json()
        points = {e['path']: e for e in relue['endpoint_groups'][0]['endpoints']}
        webhook = points['/api/stripe/webhook/']
        self.assertEqual((webhook['auth_required'], webhook['public_reason']), (False, 'appelé par Stripe'))
        self.assertEqual(points['/api/commandes/']['auth'], {})
        spec = spec_v2()
        spec['endpoint_groups'][0]['endpoints'].append(
            {'method': 'GET', 'path': '/api/vitrine/', 'auth_required': False, 'public_reason': 'catalogue'})
        relue = self.alice.post('/api/apps/', spec, format='json').json()
        vitrine = next(e for e in relue['endpoint_groups'][0]['endpoints'] if e['path'] == '/api/vitrine/')
        self.assertEqual(vitrine['auth'], {'mode': 'public'})

    def test_valeurs_fermees_refusees(self):
        cas = {
            'integration': lambda s: s['integrations'].append({'type': 'redis'}),
            'genre de modèle': lambda s: s['data_models'][0].update(kind='table'),
            'mode d\'auth': lambda s: s['endpoint_groups'][0]['endpoints'][0].update(auth={'mode': 'basic'}),
            'liste d\'extensions': lambda s: s['extensions'].update(divers=[{'name': 'x'}]),
            'genre de rôle': lambda s: s['roles'].append({'name': 'x', 'kind': 'superuser'}),
            'genre de job': lambda s: s['jobs'].append({'name': 'x', 'kind': 'daemon'}),
            'rôle sans nom': lambda s: s['roles'].append({'kind': 'keycloak_group'}),
            'access non objet': lambda s: s['data_models'][0].update(access=['owner']),
        }
        for nom, abimer in cas.items():
            with self.subTest(nom):
                spec = spec_v2()
                abimer(spec)
                self.assertEqual(self.alice.post('/api/apps/', spec, format='json').status_code, 400)
        self.assertEqual(AppSpec.objects.count(), 0)

    def test_une_spec_v1_reste_valable(self):
        resp = self.alice.post('/api/apps/', _spec_complete(), format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        spec = resp.json()
        self.assertEqual((spec['roles'], spec['jobs'], spec['extensions']), ([], [], {}))
        self.assertEqual(spec['data_models'][0]['access'], {})


class MetamodelePatchTests(SimpleTestCase):

    def test_normaliser_accepte_app_type_constructible_seulement(self):
        apres = patching.fusionner({'name': 'x'}, {'set_meta': {'app_type': 'angular'}})
        self.assertEqual(apres['app_type'], 'angular')
        for refuse in ('spring', 'rails'):
            with self.subTest(refuse), self.assertRaises(patching.PatchRefuse) as refus:
                patching.fusionner({'name': 'x'}, {'set_meta': {'app_type': refuse}})
            self.assertIn("type d'app", refus.exception.erreurs[0])

    def test_listes_v2_fusionnees_par_nom(self):
        avant = spec_v2()
        apres = patching.fusionner(avant, {
            'roles': [{'name': 'manager', 'description': 'chef'}, {'name': 'stagiaire', 'kind': 'keycloak_group'}],
            'remove_roles': ['vendeur'],
            'integrations': [{'type': 'storage', 'mode': 'service_account'}, {'type': 'postgis'}],
            'external_apis': [{'name': 'Stripe', 'auth': 'oauth_hub'}],
            'jobs': [{'name': 'Export', 'kind': 'async', 'trigger': 'manual'}],
            'extensions': {'data_io': [{'name': 'Export CSV', 'direction': 'export', 'format': 'csv'}],
                           'realtime': [{'name': 'Tableau', 'transport': 'poll'}]},
        })
        roles = {r['name']: r for r in apres['roles']}
        self.assertEqual(set(roles), {'manager', 'stagiaire'})
        self.assertEqual((roles['manager']['description'], roles['manager']['implies']), ('chef', ['vendeur']))
        self.assertEqual({i['type']: i.get('mode') for i in apres['integrations']},
                         {'storage': 'service_account', 'email': None, 'postgis': None})
        self.assertEqual(apres['external_apis'][0]['auth'], 'oauth_hub')
        self.assertEqual(apres['external_apis'][0]['purpose'], 'paiement')
        self.assertEqual([j['name'] for j in apres['jobs']], ['Relance', 'Export'])
        self.assertEqual([x['name'] for x in apres['extensions']['data_io']], ['Import CSV', 'Export CSV'])
        self.assertEqual(len(apres['extensions']['notifications']), 1)
        retire = patching.fusionner(apres, {'remove_extensions': {'data_io': ['Import CSV']},
                                            'remove_integrations': ['email']})
        self.assertEqual([x['name'] for x in retire['extensions']['data_io']], ['Export CSV'])
        self.assertEqual({i['type'] for i in retire['integrations']}, {'storage', 'postgis'})

    def test_access_et_states_remplaces_en_entier(self):
        apres = patching.fusionner(spec_v2(), {'data_models': [
            {'name': 'Produit', 'access': {'scope': 'public_read', 'reason': 'catalogue'}},
            {'name': 'Commande', 'states': {'field': 'statut', 'values': ['a', 'b'],
                                            'transitions': [{'from': 'a', 'to': 'b'}]}}]})
        modeles = {m['name']: m for m in apres['data_models']}
        self.assertEqual(modeles['Produit']['access'], {'scope': 'public_read', 'reason': 'catalogue'})
        self.assertEqual(modeles['Produit']['constraints'], [{'kind': 'unique', 'fields': ['nom']}])
        self.assertEqual(modeles['Commande']['states'], {'field': 'statut', 'values': ['a', 'b'],
                                                         'transitions': [{'from': ['a'], 'to': 'b'}]})
        self.assertEqual(len(modeles['Commande']['fields']), 2)

    def test_nouveaux_types_et_attributs_de_champ(self):
        apres = patching.fusionner({'name': 'x'}, {'data_models': [{'name': 'Lieu', 'fields': [
            {'name': 'site', 'type': 'url'}, {'name': 'mail', 'type': 'email'}, {'name': 'jour', 'type': 'date'},
            {'name': 'cle', 'type': 'password', 'secret_scope': 'user'},
            {'name': 'zone', 'type': 'polygon', 'srid': 2154, 'geometry_kind': 'polygon'},
            {'name': 'genre', 'type': 'choice', 'values': ['a', 'a', 'b']},
            {'name': 'note', 'type': 'int', 'min': 0, 'max': 5},
            {'name': 'scan', 'type': 'image', 'max_bytes': 1000, 'accept': 'image/png, image/jpeg'}]}]})
        champs = {f['name']: f for f in apres['data_models'][0]['fields']}
        self.assertEqual({n: f['type'] for n, f in champs.items()},
                         {'site': 'url', 'mail': 'email', 'jour': 'date', 'cle': 'secret', 'zone': 'geometry',
                          'genre': 'enum', 'note': 'int', 'scan': 'storage_file'})
        self.assertEqual(champs['genre']['values'], ['a', 'b'])
        self.assertEqual((champs['note']['min'], champs['note']['max']), (0, 5))
        self.assertEqual(champs['scan']['accept'], ['image/png', 'image/jpeg'])
        self.assertEqual((champs['zone']['srid'], champs['cle']['secret_scope']), (2154, 'user'))

    def test_references_v2_introduites_refusees(self):
        cas = {
            "l'état « livree »": {'data_models': [{'name': 'Commande', 'states': {
                'values': ['brouillon'], 'transitions': [{'from': ['brouillon'], 'to': 'livree'}]}}]},
            '« Fantome » (input_model)': {'jobs': [{'name': 'J', 'kind': 'async', 'input_model': 'Fantome'}]},
            'la relation « parent »': {'data_models': [{'name': 'Produit', 'access': {'scope': 'parent', 'parent': 'parent'}}]},
            'modèle de partage « Partage »': {'data_models': [{'name': 'Produit', 'access': {'scope': 'shared',
                                                                                              'share_model': 'Partage'}}]},
            "l'endpoint « DELETE /api/x/ »": {'business_rules': [{'title': 'R', 'enforced_by': ['DELETE /api/x/']}]},
        }
        for attendu, patch in cas.items():
            with self.subTest(attendu), self.assertRaises(patching.PatchRefuse) as refus:
                patching.fusionner(spec_v2(), patch)
            self.assertIn(attendu, ' '.join(refus.exception.erreurs))

    def test_role_inconnu_accepte_mais_signale(self):
        apres = patching.fusionner(spec_v2(), {'pages': [{'name': 'Gestion', 'required_roles': ['comptable']}]})
        codes = [a['code'] for a in conformite.verifier(apres)['avertissements']]
        self.assertIn('role_hors_porte', codes)

    def test_renommer_un_modele_et_un_role_propage_les_references_v2(self):
        avant = spec_v2()
        avant['data_models'].append({'name': 'Partage', 'fields': []})
        avant['data_models'][0]['access'] = {'scope': 'shared', 'share_model': 'Partage',
                                             'rules': [{'action': 'update', 'who': ['role:manager']}]}
        apres = patching.fusionner(avant, {'data_models': [{'name': 'Achat', 'rename_from': 'Commande'},
                                                           {'name': 'Acces', 'rename_from': 'Partage'}],
                                           'roles': [{'name': 'chef', 'rename_from': 'manager'}]})
        self.assertEqual((apres['jobs'][0]['input_model'], apres['jobs'][0]['tracked_by']), ('Achat', 'Achat'))
        produit = next(m for m in apres['data_models'] if m['name'] == 'Produit')
        self.assertEqual(produit['access']['share_model'], 'Acces')
        self.assertEqual(produit['access']['rules'][0]['who'], ['role:chef'])
        self.assertEqual(next(p for p in apres['pages'] if p['name'] == 'Gestion')['required_roles'], ['chef'])
        self.assertEqual(apres['extensions']['notifications'][0]['event'], 'Achat.payee')

    def test_renommer_un_champ_suit_les_etats_et_l_acces(self):
        apres = patching.fusionner(spec_v2(), {'data_models': [{'name': 'Commande', 'fields': [
            {'name': 'etat', 'rename_from': 'statut'}, {'name': 'proprietaire', 'rename_from': 'owner_email'}]}]})
        commande = next(m for m in apres['data_models'] if m['name'] == 'Commande')
        self.assertEqual([f['name'] for f in commande['fields']], ['etat', 'proprietaire'])
        self.assertEqual((commande['states']['field'], commande['access']['owner_field']), ('etat', 'proprietaire'))

    def test_endpoint_non_jwt_devient_sans_jeton(self):
        apres = patching.fusionner(spec_v2(), {'endpoint_groups': [{'name': 'Commandes', 'endpoints': [
            {'method': 'POST', 'path': '/api/commandes/', 'auth': {'mode': 'api_key', 'reason': 'borne'}}]}]})
        point = apres['endpoint_groups'][0]['endpoints'][0]
        self.assertEqual((point['auth_required'], point['public_reason'], point['auth']['mode']), (False, 'borne', 'api_key'))

    def test_valeur_fermee_inconnue_dans_un_patch_refusee(self):
        for patch in ({'integrations': [{'type': 'redis'}]},
                      {'data_models': [{'name': 'X', 'access': {'scope': 'tous'}}]},
                      {'extensions': {'autre': [{'name': 'x'}]}}):
            with self.subTest(patch), self.assertRaises(patching.PatchRefuse):
                patching.fusionner(spec_v2(), patch)


class VerifierTests(SimpleTestCase):

    def test_blocages_inchanges_et_avertissements(self):
        spec = spec_v2()
        self.assertEqual(conformite.verifier(spec)['blocages'], conformite.blocages(spec))

    def test_chaque_avertissement_du_contrat(self):
        spec = spec_v2()
        spec['data_models'].append({'name': 'Lieu', 'fields': [{'name': 'g', 'type': 'enum'},
                                                               {'name': 'zone', 'type': 'geometry'}],
                                    'states': {'field': 'x', 'values': ['a']}})
        spec['endpoint_groups'][0]['endpoints'].append({'method': 'GET', 'path': '/api/hook/', 'auth_required': False,
                                                        'required_roles': ['fantome']})
        spec['business_rules'].append({'title': 'Valide', 'kind': 'validation'})
        spec['jobs'].append({'name': 'Sans', 'kind': 'async'})
        spec['data_models'][0]['access']['rules'].append({'action': 'delete', 'who': ['role:inconnu']})
        codes = {a['code'] for a in conformite.verifier(spec)['avertissements']}
        self.assertEqual(codes, {'modele_sans_access', 'role_hors_porte', 'role_inconnu', 'regle_sans_endpoint',
                                 'enum_sans_values', 'etat_sans_transition', 'job_sans_declencheur',
                                 'endpoint_non_jwt_sans_raison', 'geometry_sans_postgis'})
        for a in conformite.verifier(spec)['avertissements']:
            self.assertEqual(set(a), {'code', 'message', 'element'})

    def test_spec_bien_decrite_sans_avertissement(self):
        self.assertEqual(conformite.verifier(spec_v2())['avertissements'], [])


class MigrationMetamodeleV2Tests(TransactionTestCase):
    """La migration 0011 n'ajoute que des colonnes : les specs d'avant migrent intactes."""

    def test_les_specs_d_avant_survivent(self):
        executeur = MigrationExecutor(connection)
        try:
            executeur.migrate([('api', '0010_ai_key_vault')])
            apps = executeur.loader.project_state([('api', '0010_ai_key_vault')]).apps
            Spec, Modele = apps.get_model('api', 'AppSpec'), apps.get_model('api', 'DataModel')
            Groupe, Point = apps.get_model('api', 'EndpointGroup'), apps.get_model('api', 'Endpoint')
            Page = apps.get_model('api', 'Page')
            spec = Spec.objects.create(name='Avant', project_name='avant', app_type='django', owner_email='alice@ssolab.local',
                                       required_groups=['famille'], business_rules=[{'title': 'R', 'description': 'd'}],
                                       uses_email=True, chat_history=[{'role': 'user', 'content': 'x'}])
            Modele.objects.create(app=spec, name='Plat', fields=[{'name': 'nom', 'type': 'string'}],
                                  relationships=[{'name': 'r', 'rel_type': 'FK', 'to_model': 'Plat'}])
            groupe = Groupe.objects.create(app=spec, name='Plats')
            Point.objects.create(group=groupe, method='GET', path='/api/plats/', auth_required=False,
                                 public_reason='carte')
            Page.objects.create(app=spec, name='Carte', route='/carte', layout='list', components=[{'type': 'table'}])
            avant = patching.version_de({
                'name': 'Avant', 'project_name': 'avant', 'app_type': 'django', 'required_groups': ['famille'],
                'business_rules': [{'title': 'R', 'description': 'd'}], 'uses_email': True})

            executeur = MigrationExecutor(connection)
            executeur.migrate(executeur.loader.graph.leaf_nodes())
            apres = AppSpec.objects.get(pk=spec.pk)
            self.assertEqual((apres.name, apres.project_name, apres.app_type, apres.required_groups, apres.uses_email,
                              apres.business_rules, apres.chat_history),
                             ('Avant', 'avant', 'django', ['famille'], True, [{'title': 'R', 'description': 'd'}],
                              [{'role': 'user', 'content': 'x'}]))
            self.assertEqual((apres.roles, apres.jobs, apres.integrations, apres.external_apis, apres.extensions),
                             ([], [], [], [], {}))
            modele = apres.data_models.get()
            self.assertEqual((modele.fields, modele.relationships, modele.kind, modele.access, modele.states,
                              modele.constraints),
                             ([{'name': 'nom', 'type': 'string'}], [{'name': 'r', 'rel_type': 'FK', 'to_model': 'Plat'}],
                              'entity', {}, {}, []))
            point = apres.endpoint_groups.get().endpoints.get()
            self.assertEqual((point.auth_required, point.public_reason, point.auth), (False, 'carte', {}))
            page = apres.pages.get()
            self.assertEqual((page.layout, page.components, page.public, page.public_reason, page.required_roles),
                             ('list', [{'type': 'table'}], False, '', []))
            self.assertTrue(avant.startswith('v:'))
        finally:
            MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
