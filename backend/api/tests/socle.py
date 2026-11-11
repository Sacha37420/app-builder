"""Tests backend d'app-builder.

    python manage.py test            (dans /app ; base PostgreSQL jetable, aucun réseau)

Trois familles :
  1. la serrure de l'API (Verrou 2) — de VRAIS jetons RS256 signés par une clé
     locale traversent `KeycloakJWTAuthentication` ; seul le téléchargement du
     JWKS de Keycloak est remplacé ;
  2. les règles d'autorisation de l'app — une spécification n'appartient qu'à
     son auteur (`owner_email`) ;
  3. les règles métier — résolution des identifiants temporaires du frontend,
     remplacement complet à l'enregistrement (le chat IA est testé dans
     `tests/ia.py`) ;
  4. l'application des patchs IA côté serveur (api/patching.py) — fusion par
     élément, suppressions et renommages, références, historique et annulation.

Aucun appel sortant : Anthropic et Mistral sont simulés.
"""
import json
import time
from unittest import mock

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.db import connection
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from api import patching
from api.authentication import KeycloakJWTAuthentication
from api.models import AiKeyVault, AppSpec, EndpointGroup, FrontendService, Page, PatchApplication

CLIENT_ID = 'app-builder'
_RSA = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_AUTRE_RSA = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _JwksLocal:
    """Remplace le TÉLÉCHARGEMENT du JWKS par une clé locale. Signature,
    expiration, azp, groupes et email sont vérifiés par le vrai code."""

    class _Cle:
        key = _RSA.public_key()

    def get_signing_key_from_jwt(self, token):
        return self._Cle()


_ABSENT = object()


def jeton(uid='alice', groups=('developers',), azp=CLIENT_ID, email=_ABSENT,
          exp=300, cle=_RSA, algorithm='RS256') -> str:
    claims = {'preferred_username': uid, 'azp': azp, 'exp': int(time.time()) + exp}
    if groups is not None:
        claims['groups'] = list(groups)
    if email is _ABSENT:
        email = f'{uid}@ssolab.local'
    if email is not None:
        claims['email'] = email
    return jwt.encode(claims, cle, algorithm=algorithm)


@override_settings(KEYCLOAK_CLIENT_ID=CLIENT_ID, KEYCLOAK_REQUIRED_GROUPS='developers,admins',
                   ANTHROPIC_API_KEY='cle-serveur-anthropic', MISTRAL_API_KEY='cle-serveur-mistral')
class Base(TestCase):

    def setUp(self):
        p = mock.patch.object(KeycloakJWTAuthentication, '_get_jwks_client',
                              classmethod(lambda cls: _JwksLocal()))
        p.start()
        self.addCleanup(p.stop)

    @staticmethod
    def coffre(uid='alice', claude='', mistral='', albert='') -> AiKeyVault:
        """Pose directement les clés d'un compte dans le coffre (comme le ferait PUT /api/ai-keys/)."""
        return AiKeyVault.objects.update_or_create(
            owner_email=f'{uid}@ssolab.local',
            defaults={'claude_key': claude, 'mistral_key': mistral, 'albert_key': albert})[0]

    def client_de(self, uid='alice', **kw) -> APIClient:
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {jeton(uid, **kw)}')
        return c

    def avec(self, tok: str) -> APIClient:
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {tok}')
        return c


# ═══ 1. Serrure de l'API ═══════════════════════════════════════════════════════

class SerrureTests(Base):

    def test_sans_jeton_tout_est_refuse(self):
        spec = AppSpec.objects.create(name='x', owner_email='alice@ssolab.local')
        anonyme = APIClient()
        appels = [
            ('get', '/api/me/'), ('get', '/api/apps/'), ('post', '/api/apps/'),
            ('get', f'/api/apps/{spec.pk}/'), ('put', f'/api/apps/{spec.pk}/'),
            ('delete', f'/api/apps/{spec.pk}/'), ('patch', f'/api/apps/{spec.pk}/chat/'),
            ('post', '/api/chat/'),
        ]
        for methode, chemin in appels:
            with self.subTest(appel=f'{methode} {chemin}'):
                resp = getattr(anonyme, methode)(chemin, {}, format='json')
                self.assertIn(resp.status_code, (401, 403))
        self.assertTrue(AppSpec.objects.filter(pk=spec.pk).exists())

    def test_en_tete_qui_n_est_pas_bearer_est_refuse(self):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Basic {jeton()}')
        self.assertIn(c.get('/api/me/').status_code, (401, 403))

    def test_membre_accepte_et_identite_tiree_du_jeton(self):
        resp = self.client_de('alice', groups=['amis', 'developers']).get('/api/me/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'email': 'alice@ssolab.local', 'username': 'alice',
                                       'groups': ['amis', 'developers']})

    def test_azp_etranger_refuse(self):
        # admin-cli : client public du realm avec password grant. Sans ce
        # contrôle, tout compte du realm appelle l'API sans croiser le flow.
        for azp in ('admin-cli', 'lab-admin', 'storage', '', None):
            with self.subTest(azp=azp):
                resp = self.client_de('alice', groups=['developers', 'admins'], azp=azp).get('/api/me/')
                self.assertEqual(resp.status_code, 403)
                self.assertIn('client non autorisé', resp.json()['detail'])

    def test_hors_groupe_refuse(self):
        for groups in (['inconnus'], [], None):
            with self.subTest(groups=groups):
                resp = self.client_de('lea', groups=groups).get('/api/me/')
                self.assertEqual(resp.status_code, 403)
                self.assertIn('groupe(s)', resp.json()['detail'])

    def test_nom_de_groupe_approchant_refuse(self):
        # Intersection d'ensembles, pas une recherche de sous-chaîne.
        for groups in (['developer'], ['developers-junior'], ['/developers'], ['Developers']):
            with self.subTest(groups=groups):
                self.assertEqual(self.client_de('lea', groups=groups).get('/api/me/').status_code, 403)

    def test_jeton_expire_refuse(self):
        resp = self.client_de('alice', exp=-60).get('/api/me/')
        self.assertEqual(resp.status_code, 403)
        self.assertIn('Token invalide', resp.json()['detail'])

    def test_signature_d_une_autre_cle_refusee(self):
        resp = self.avec(jeton('alice', cle=_AUTRE_RSA)).get('/api/me/')
        self.assertEqual(resp.status_code, 403)
        self.assertIn('Token invalide', resp.json()['detail'])

    def test_contenu_modifie_apres_signature_refuse(self):
        entete, _, signature = jeton('lea', groups=[]).split('.')
        charge = jwt.utils.base64url_encode(json.dumps({
            'preferred_username': 'lea', 'azp': CLIENT_ID, 'groups': ['developers'],
            'email': 'lea@ssolab.local', 'exp': int(time.time()) + 300,
        }).encode()).decode()
        self.assertEqual(self.avec(f'{entete}.{charge}.{signature}').get('/api/me/').status_code, 403)

    def test_algorithme_autre_que_rs256_refuse(self):
        claims = {'preferred_username': 'alice', 'azp': CLIENT_ID, 'groups': ['developers'],
                  'email': 'alice@ssolab.local', 'exp': int(time.time()) + 300}
        sans_signature = jwt.encode(claims, None, algorithm='none')
        symetrique = jwt.encode(claims, 'secret-partage-suffisamment-long-pour-hs256', algorithm='HS256')
        for nom, tok in (('none', sans_signature), ('HS256', symetrique), ('charabia', 'pas.un.jeton')):
            with self.subTest(jeton=nom):
                self.assertEqual(self.avec(tok).get('/api/me/').status_code, 403)

    def test_jeton_sans_email_refuse(self):
        # Toute la propriété des données repose sur l'email : un jeton sans
        # email posséderait les spécifications dont owner_email est vide.
        AppSpec.objects.create(name='orpheline', owner_email='')
        for email in (None, ''):
            with self.subTest(email=email):
                resp = self.client_de('alice', email=email).get('/api/apps/')
                self.assertEqual(resp.status_code, 403)

    @override_settings(KEYCLOAK_REQUIRED_GROUPS='')
    def test_sans_groupe_requis_l_azp_reste_controle(self):
        self.assertEqual(self.client_de('lea', groups=[]).get('/api/me/').status_code, 200)
        self.assertEqual(self.client_de('lea', groups=[], azp='admin-cli').get('/api/me/').status_code, 403)

    def test_documentation_de_l_api_absente_en_service(self):
        # Règle de gabarit : /api/schema/ et /api/docs/ n'existent qu'en DEBUG.
        for c in (APIClient(), self.client_de('alice')):
            for chemin in ('/api/schema/', '/api/docs/', '/'):
                with self.subTest(chemin=chemin):
                    self.assertEqual(c.get(chemin).status_code, 404)


# ═══ 2. Autorisation : une spécification n'appartient qu'à son auteur ═════════

class ProprieteTests(Base):

    def setUp(self):
        super().setUp()
        self.alice = self.client_de('alice')
        self.bob = self.client_de('bob')
        self.spec_bob = AppSpec.objects.create(
            name='Secret de Bob', owner_email='bob@ssolab.local',
            chat_history=[{'role': 'user', 'content': 'confidentiel'}])
        EndpointGroup.objects.create(app=self.spec_bob, name='Groupe de Bob')

    def test_la_liste_ne_rend_que_ses_propres_specifications(self):
        AppSpec.objects.create(name='À Alice', owner_email='alice@ssolab.local')
        noms = [s['name'] for s in self.alice.get('/api/apps/').json()]
        self.assertEqual(noms, ['À Alice'])
        self.assertEqual([s['name'] for s in self.bob.get('/api/apps/').json()], ['Secret de Bob'])

    def test_appartenir_au_meme_groupe_ne_donne_aucun_droit(self):
        admin = self.client_de('chef', groups=['admins', 'developers'])
        self.assertEqual(admin.get('/api/apps/').json(), [])
        self.assertEqual(admin.get(f'/api/apps/{self.spec_bob.pk}/').status_code, 404)

    def test_lecture_modification_suppression_d_autrui_impossibles(self):
        url = f'/api/apps/{self.spec_bob.pk}/'
        self.assertEqual(self.alice.get(url).status_code, 404)
        self.assertEqual(self.alice.put(url, {'name': 'volé'}, format='json').status_code, 404)
        self.assertEqual(self.alice.patch(url, {'name': 'volé', 'endpoint_groups': []},
                                          format='json').status_code, 404)
        self.assertEqual(self.alice.delete(url).status_code, 404)
        self.spec_bob.refresh_from_db()
        self.assertEqual(self.spec_bob.name, 'Secret de Bob')
        self.assertEqual(self.spec_bob.endpoint_groups.count(), 1)

    def test_historique_de_conversation_d_autrui_intouchable(self):
        resp = self.alice.patch(f'/api/apps/{self.spec_bob.pk}/chat/', {'chat_history': []}, format='json')
        self.assertEqual(resp.status_code, 404)
        self.spec_bob.refresh_from_db()
        self.assertEqual(self.spec_bob.chat_history, [{'role': 'user', 'content': 'confidentiel'}])

    def test_le_proprietaire_fait_tout_sur_la_sienne(self):
        url = f'/api/apps/{self.spec_bob.pk}/'
        self.assertEqual(self.bob.get(url).json()['chat_history'],
                         [{'role': 'user', 'content': 'confidentiel'}])
        self.assertEqual(self.bob.patch(url, {'name': 'Renommée'}, format='json').status_code, 200)
        self.assertEqual(self.bob.patch(f'{url}chat/', {'chat_history': [{'role': 'user', 'content': 'a'}]},
                                        format='json').json(), {'ok': True})
        self.spec_bob.refresh_from_db()
        self.assertEqual((self.spec_bob.name, len(self.spec_bob.chat_history)), ('Renommée', 1))
        self.assertEqual(self.bob.delete(url).status_code, 204)
        self.assertFalse(AppSpec.objects.filter(pk=self.spec_bob.pk).exists())

    def test_creation_le_proprietaire_est_l_appelant_quoi_que_dise_la_requete(self):
        resp = self.alice.post('/api/apps/', {'name': 'Mienne', 'owner_email': 'bob@ssolab.local'},
                               format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(AppSpec.objects.get(pk=resp.json()['id']).owner_email, 'alice@ssolab.local')
        self.assertEqual(len(self.bob.get('/api/apps/').json()), 1)

    def test_modification_ne_change_pas_le_proprietaire(self):
        # `owner_email` est en lecture seule : un PATCH ne dépose pas sa
        # spécification (contenu libre, `required_groups` compris) dans le
        # catalogue d'un autre compte, que lab-admin lui attribuerait.
        resp = self.alice.post('/api/apps/', {'name': 'Cheval de Troie'}, format='json')
        pk = resp.json()['id']
        for methode in (self.alice.patch, self.alice.put):
            resp = methode(f'/api/apps/{pk}/', {'name': 'Cheval de Troie', 'owner_email': 'bob@ssolab.local'},
                           format='json')
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(AppSpec.objects.get(pk=pk).owner_email, 'alice@ssolab.local')
        self.assertEqual(len(self.bob.get('/api/apps/').json()), 1)

    def test_l_enregistrement_complet_n_ecrase_pas_la_conversation(self):
        # chat_history est en lecture seule dans la spec : il ne s'écrit que
        # par /chat/, pour que l'autosave (PUT) ne l'efface pas.
        url = f'/api/apps/{self.spec_bob.pk}/'
        self.bob.put(url, {'name': 'Secret de Bob', 'chat_history': []}, format='json')
        self.spec_bob.refresh_from_db()
        self.assertEqual(len(self.spec_bob.chat_history), 1)

    def test_un_service_ne_peut_pas_se_lier_au_groupe_d_un_autre(self):
        # Les identifiants de groupes envoyés ne sont résolus que parmi les
        # groupes de la requête elle-même : l'id réel d'un groupe d'autrui
        # n'est jamais relié.
        groupe_bob = self.spec_bob.endpoint_groups.get()
        resp = self.alice.post('/api/apps/', {
            'name': 'Curieuse',
            'services': [{'id': -1, 'name': 'Svc', 'endpoint_group_ids': [groupe_bob.pk]}],
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['services'][0]['endpoint_group_ids'], [])
        self.assertEqual(groupe_bob.services.count(), 0)


# ═══ 3. Règles métier : la spécification ══════════════════════════════════════

def _spec_complete() -> dict:
    return {
        'name': 'Boutique', 'app_type': 'django-angular', 'required_groups': ['famille'],
        'data_models': [{'name': 'Produit', 'fields': [{'name': 'nom', 'type': 'string'}]}],
        'endpoint_groups': [
            {'id': -1, 'name': 'Produits', 'endpoints': [
                {'method': 'GET', 'path': '/api/produits/', 'operation': 'list',
                 'steps': [{'label': 'Requête', 'type': 'db_query'}]}]},
            {'id': -2, 'name': 'Commandes', 'endpoints': []},
        ],
        'services': [
            {'id': -10, 'name': 'ProduitService', 'endpoint_group_ids': [-1]},
            {'id': -11, 'name': 'ToutService', 'endpoint_group_ids': [-1, -2, -99]},
        ],
        'pages': [{
            'name': 'Liste', 'route': '/produits', 'layout': 'kanban', 'service_ids': [-10],
            'interactions': [{'name': 'Glisser', 'type': 'drag_and_drop'}],
            'pipelines': [{'name': 'Chargement', 'trigger_interaction': 'Glisser',
                           'steps': [{'label': 'init', 'type': 'trigger'}]}],
        }],
    }


class SpecificationTests(Base):

    def setUp(self):
        super().setUp()
        self.alice = self.client_de('alice')

    def test_les_identifiants_temporaires_sont_resolus_a_la_creation(self):
        resp = self.alice.post('/api/apps/', _spec_complete(), format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        spec = resp.json()
        groupes = {g['name']: g['id'] for g in spec['endpoint_groups']}
        services = {s['name']: s for s in spec['services']}
        self.assertTrue(all(i > 0 for i in groupes.values()))
        self.assertEqual(services['ProduitService']['endpoint_group_ids'], [groupes['Produits']])
        # -99 ne désigne aucun groupe de la requête : ignoré, pas d'erreur.
        self.assertCountEqual(services['ToutService']['endpoint_group_ids'], list(groupes.values()))
        page = spec['pages'][0]
        self.assertEqual(page['service_ids'], [services['ProduitService']['id']])
        produits = next(g for g in spec['endpoint_groups'] if g['name'] == 'Produits')
        self.assertEqual(produits['endpoints'][0]['steps'][0]['type'], 'db_query')
        self.assertEqual(spec['required_groups'], ['famille'])

    def test_types_libres_emis_par_l_ia_acceptes(self):
        # layout et type d'interaction ne sont pas restreints aux choix du
        # modèle : l'IA émet kanban, calendar, drag_and_drop…
        spec = self.alice.post('/api/apps/', _spec_complete(), format='json').json()
        self.assertEqual(spec['pages'][0]['layout'], 'kanban')
        self.assertEqual(spec['pages'][0]['interactions'][0]['type'], 'drag_and_drop')
        self.assertEqual(spec['pages'][0]['pipelines'][0]['trigger_interaction'], 'Glisser')

    def test_valeurs_refusees(self):
        for champ, valeur in (('app_type', 'rails'), ('name', '')):
            with self.subTest(champ=champ):
                resp = self.alice.post('/api/apps/', {**_spec_complete(), champ: valeur}, format='json')
                self.assertEqual(resp.status_code, 400)
                self.assertIn(champ, resp.json())
        mauvaise = _spec_complete()
        mauvaise['endpoint_groups'][0]['endpoints'][0]['method'] = 'TRACE'
        self.assertEqual(self.alice.post('/api/apps/', mauvaise, format='json').status_code, 400)
        self.assertEqual(AppSpec.objects.count(), 0)

    def test_reenregistrer_la_spec_complete_remplace_sans_dupliquer(self):
        # L'autosave renvoie la spec telle que reçue (identifiants RÉELS) :
        # tout est recréé, et les liens sont refaits vers les nouveaux objets.
        spec = self.alice.post('/api/apps/', _spec_complete(), format='json').json()
        url = f"/api/apps/{spec['id']}/"
        spec['name'] = 'Boutique v2'
        resp = self.alice.put(url, spec, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        apres = resp.json()
        self.assertEqual(apres['name'], 'Boutique v2')
        app = AppSpec.objects.get(pk=spec['id'])
        self.assertEqual((app.data_models.count(), app.endpoint_groups.count(),
                          app.services.count(), app.pages.count()), (1, 2, 2, 1))
        self.assertEqual(EndpointGroup.objects.count(), 2)
        self.assertEqual(FrontendService.objects.count(), 2)
        self.assertEqual(Page.objects.count(), 1)
        groupes = {g['name']: g['id'] for g in apres['endpoint_groups']}
        services = {s['name']: s for s in apres['services']}
        self.assertEqual(services['ProduitService']['endpoint_group_ids'], [groupes['Produits']])
        self.assertEqual(apres['pages'][0]['service_ids'], [services['ProduitService']['id']])
        self.assertEqual(len(apres['pages'][0]['interactions']), 1)

    def test_modification_partielle_ne_touche_que_ce_qui_est_envoye(self):
        spec = self.alice.post('/api/apps/', _spec_complete(), format='json').json()
        resp = self.alice.patch(f"/api/apps/{spec['id']}/", {'data_models': []}, format='json')
        self.assertEqual(resp.status_code, 200)
        apres = resp.json()
        self.assertEqual(apres['data_models'], [])
        self.assertEqual(len(apres['endpoint_groups']), 2)
        self.assertEqual(len(apres['pages']), 1)

    def test_layout_trop_long_refuse_proprement(self):
        # Le sérialiseur est aligné sur la colonne `pages.layout` (20
        # caractères, comme le miroir de lab-admin) : au-delà, 400 et non une
        # erreur de base rendue en 500.
        spec = _spec_complete()
        spec['pages'][0]['layout'] = 'tableau-de-bord-personnalise'
        resp = self.alice.post('/api/apps/', spec, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('layout', str(resp.json()))
        self.assertEqual(AppSpec.objects.count(), 0)
        spec['pages'][0]['layout'] = 'x' * 20
        self.assertEqual(self.alice.post('/api/apps/', spec, format='json').status_code, 201)

    def test_tables_lues_par_lab_admin(self):
        # lab-admin lit ces tables directement (api/models_appbuilder.py,
        # modèles non gérés recopiés à la main) : renommer une table ou une
        # colonne ici casse sa page « Projets » sans qu'aucun test ne le voie.
        attendu = {
            'app_specs': {'id', 'name', 'description', 'app_type', 'owner_email', 'created_at', 'updated_at'},
            'data_models': {'id', 'app_id', 'name', 'description', 'fields', 'relationships', 'order'},
            'endpoint_groups': {'id', 'app_id', 'name', 'description', 'order'},
            'endpoints': {'id', 'group_id', 'method', 'path', 'description', 'order', 'operation',
                          'linked_model_name', 'auth_required', 'required_roles', 'query_params', 'steps'},
            'frontend_services': {'id', 'app_id', 'name', 'order'},
            'frontend_services_endpoint_groups': {'id', 'frontendservice_id', 'endpointgroup_id'},
            'pages': {'id', 'app_id', 'name', 'route', 'order', 'layout', 'components'},
            'pages_services': {'id', 'page_id', 'frontendservice_id'},
            'interactions': {'id', 'page_id', 'name', 'type', 'description', 'order'},
            'pipelines': {'id', 'page_id', 'name', 'description', 'trigger_interaction', 'steps', 'order'},
        }
        with connection.cursor() as cur:
            tables = set(connection.introspection.table_names(cur))
            for table, colonnes in attendu.items():
                with self.subTest(table=table):
                    self.assertIn(table, tables)
                    presentes = {c.name for c in connection.introspection.get_table_description(cur, table)}
                    self.assertEqual(colonnes - presentes, set())


# ═══ 4. Patchs IA appliqués côté serveur ══════════════════════════════════════

class _PatchBase(Base):

    def setUp(self):
        super().setUp()
        self.alice = self.client_de('alice')
        self.spec = self.alice.post('/api/apps/', _spec_complete(), format='json').json()
        self.url = f"/api/apps/{self.spec['id']}/patch/"

    def patcher(self, patch, mode='merge', attendu=200):
        resp = self.alice.post(self.url, {'patch': patch, 'mode': mode}, format='json')
        self.assertEqual(resp.status_code, attendu, resp.content)
        return resp.json()['spec'] if attendu == 200 else resp.json()

    def relire(self):
        return self.alice.get(f"/api/apps/{self.spec['id']}/").json()

    @staticmethod
    def nomme(elements, nom):
        return next(e for e in elements if e['name'] == nom)


class PatchFusionTests(_PatchBase):

    def test_ajouter_un_endpoint_a_un_groupe_garde_les_autres(self):
        spec = self.patcher({'endpoint_groups': [{'name': 'Produits', 'endpoints': [
            {'method': 'post', 'path': '/api/produits/', 'operation': 'create', 'linked_model_name': 'Produit',
             'steps': [{'label': 'Valider', 'type': 'validate', 'description': 'nom requis'}]}]}]})
        endpoints = {(e['method'], e['path']): e for e in self.nomme(spec['endpoint_groups'], 'Produits')['endpoints']}
        self.assertEqual(set(endpoints), {('GET', '/api/produits/'), ('POST', '/api/produits/')})
        # Les étapes de traitement : celles de l'existant restent, celles du patch sont gardées.
        self.assertEqual(endpoints[('GET', '/api/produits/')]['steps'], [{'label': 'Requête', 'type': 'db_query'}])
        self.assertEqual(endpoints[('POST', '/api/produits/')]['steps'],
                         [{'label': 'Valider', 'type': 'validate', 'description': 'nom requis'}])
        self.assertEqual(self.relire()['endpoint_groups'], spec['endpoint_groups'])

    def test_modifier_un_endpoint_ne_touche_que_les_cles_envoyees(self):
        spec = self.patcher({'endpoint_groups': [{'name': 'Produits', 'endpoints': [
            {'method': 'GET', 'path': '/api/produits/', 'required_roles': ['manager']}]}]})
        endpoint, = self.nomme(spec['endpoint_groups'], 'Produits')['endpoints']
        self.assertEqual(endpoint['required_roles'], ['manager'])
        self.assertEqual(endpoint['operation'], 'list')
        self.assertEqual(endpoint['steps'], [{'label': 'Requête', 'type': 'db_query'}])

    def test_patch_de_page_sans_service_names_garde_ses_liens_et_ses_voisins(self):
        spec = self.patcher({'pages': [{'name': 'Liste',
                                        'interactions': [{'name': 'Cliquer', 'type': 'click'}],
                                        'pipelines': [{'name': 'Ouverture', 'trigger_interaction': 'Cliquer',
                                                       'steps': [{'label': 'aller', 'type': 'navigate'}]}]}]})
        page = self.nomme(spec['pages'], 'Liste')
        self.assertEqual(page['service_ids'], [self.nomme(spec['services'], 'ProduitService')['id']])
        self.assertEqual(page['layout'], 'kanban')
        self.assertEqual([i['name'] for i in page['interactions']], ['Glisser', 'Cliquer'])
        self.assertEqual([p['name'] for p in page['pipelines']], ['Chargement', 'Ouverture'])
        self.assertEqual(self.nomme(page['pipelines'], 'Chargement')['steps'], [{'label': 'init', 'type': 'trigger'}])

    def test_ajouter_un_champ_garde_les_autres_et_leurs_reglages(self):
        self.patcher({'data_models': [{'name': 'Produit', 'fields': [
            {'name': 'nom', 'type': 'string', 'max_length': 80, 'unique': True}]}]})
        spec = self.patcher({'data_models': [{'name': 'Produit', 'fields': [
            {'name': 'prix', 'type': 'float'}, {'name': 'nom', 'required': False}]}]})
        champs = {c['name']: c for c in self.nomme(spec['data_models'], 'Produit')['fields']}
        self.assertEqual(list(champs), ['nom', 'prix'])
        self.assertEqual(champs['nom'], {'name': 'nom', 'type': 'string', 'max_length': 80,
                                         'unique': True, 'required': False})
        self.assertEqual(champs['prix'], {'name': 'prix', 'type': 'decimal', 'required': True, 'unique': False})

    def test_une_liste_de_liens_envoyee_remplace_absente_ne_change_rien(self):
        spec = self.patcher({'services': [{'name': 'ToutService', 'endpoint_group_names': ['Commandes']},
                                          {'name': 'ProduitService', 'order': 5}]})
        groupes = {g['name']: g['id'] for g in spec['endpoint_groups']}
        self.assertEqual(self.nomme(spec['services'], 'ToutService')['endpoint_group_ids'], [groupes['Commandes']])
        self.assertEqual(self.nomme(spec['services'], 'ProduitService')['endpoint_group_ids'], [groupes['Produits']])

    def test_elements_nouveaux_crees_et_relies_par_nom(self):
        spec = self.patcher({
            'data_models': [{'name': 'Client', 'fields': [{'name': 'nom', 'type': 'string'}],
                             'relationships': [{'name': 'favori', 'rel_type': 'foreign_key', 'to_model': 'Produit'}]}],
            'endpoint_groups': [{'name': 'Clients', 'endpoints': [
                {'method': 'GET', 'path': '/api/clients/', 'linked_model_name': 'Client'}]}],
            'services': [{'name': 'ClientService', 'endpoint_group_names': ['Clients']}],
            'pages': [{'name': 'Fiche client', 'service_names': ['ClientService', 'ProduitService'],
                       'components': [{'type': 'card', 'linked_model': 'Client', 'fields': ['nom']}]}],
        })
        relation, = self.nomme(spec['data_models'], 'Client')['relationships']
        self.assertEqual(relation, {'name': 'favori', 'rel_type': 'FK', 'to_model': 'Produit',
                                    'related_name': '', 'on_delete': 'CASCADE'})
        service = self.nomme(spec['services'], 'ClientService')
        self.assertEqual(service['endpoint_group_ids'], [self.nomme(spec['endpoint_groups'], 'Clients')['id']])
        page = self.nomme(spec['pages'], 'Fiche client')
        self.assertEqual(page['route'], '/fiche-client')
        self.assertCountEqual(page['service_ids'],
                              [service['id'], self.nomme(spec['services'], 'ProduitService')['id']])
        self.assertEqual(len(spec['pages']), 2)

    def test_groupes_requis_ajoutes_sans_perdre_les_anciens_retires_sur_demande(self):
        spec = self.patcher({'set_meta': {'required_groups': ['amis']}})
        self.assertEqual(spec['required_groups'], ['famille', 'amis'])
        self.assertEqual(spec['name'], 'Boutique')
        spec = self.patcher({'set_meta': {'name': 'Boutique v2', 'remove_required_groups': ['famille']}})
        self.assertEqual((spec['name'], spec['required_groups']), ('Boutique v2', ['amis']))

    def test_remplacer_repart_d_une_spec_vide_en_gardant_les_groupes(self):
        spec = self.patcher({'data_models': [{'name': 'Client'}]}, mode='replace')
        self.assertEqual([m['name'] for m in spec['data_models']], ['Client'])
        self.assertEqual((spec['endpoint_groups'], spec['services'], spec['pages']), ([], [], []))
        self.assertEqual(spec['required_groups'], ['famille'])

    def test_patch_refuse_la_spec_n_est_pas_touchee(self):
        avant = self.relire()
        for patch, mode in (('pas un objet', 'merge'), ({'data_models': [{'name': 'X'}]}, 'ecraser'),
                            ({'pages': [{'name': 'Liste', 'layout': 'x' * 30}]}, 'merge'),
                            ({'endpoint_groups': [{'name': 'Produits', 'endpoints': [
                                {'method': 'GET', 'path': '/' + 'x' * 600}]}]}, 'merge')):
            with self.subTest(patch=patch, mode=mode):
                refus = self.patcher(patch, mode=mode, attendu=400)
                self.assertTrue(refus['details'])
                self.assertEqual(self.relire(), avant)
        self.assertEqual(PatchApplication.objects.count(), 0)

    def test_la_spec_d_autrui_ne_se_patche_pas(self):
        bob = self.client_de('bob')
        resp = bob.post(self.url, {'patch': {'remove_models': ['Produit']}}, format='json')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(len(self.relire()['data_models']), 1)
        self.assertEqual(APIClient().post(self.url, {'patch': {}}, format='json').status_code, 403)

    def test_la_fusion_ne_modifie_pas_la_spec_recue(self):
        avant = self.relire()
        copie = json.loads(json.dumps(avant))
        patching.fusionner(avant, {'remove_pages': ['Liste'], 'data_models': [{'name': 'Produit', 'remove_fields': ['nom']}]})
        self.assertEqual(avant, copie)


class PatchSuppressionTests(_PatchBase):

    def test_suppressions_ciblees(self):
        self.patcher({'data_models': [{'name': 'Produit', 'fields': [{'name': 'prix', 'type': 'decimal'}]}],
                      'pages': [{'name': 'Liste', 'interactions': [{'name': 'Cliquer', 'type': 'click'}]}]})
        spec = self.patcher({
            'data_models': [{'name': 'Produit', 'remove_fields': ['nom']}],
            'endpoint_groups': [{'name': 'Produits', 'remove_endpoints': ['GET /api/produits/']}],
            'pages': [{'name': 'Liste', 'remove_interactions': ['Cliquer'], 'remove_pipelines': ['Chargement']}],
        })
        self.assertEqual([c['name'] for c in spec['data_models'][0]['fields']], ['prix'])
        self.assertEqual(self.nomme(spec['endpoint_groups'], 'Produits')['endpoints'], [])
        page = self.nomme(spec['pages'], 'Liste')
        self.assertEqual([i['name'] for i in page['interactions']], ['Glisser'])
        self.assertEqual(page['pipelines'], [])

    def test_supprimer_un_groupe_ou_un_service_defait_ses_liens(self):
        spec = self.patcher({'remove_endpoint_groups': ['Commandes'], 'remove_services': ['ProduitService']})
        self.assertEqual([g['name'] for g in spec['endpoint_groups']], ['Produits'])
        tout, = spec['services']
        self.assertEqual(tout['endpoint_group_ids'], [spec['endpoint_groups'][0]['id']])
        self.assertEqual(spec['pages'][0]['service_ids'], [])

    def test_supprimer_un_element_absent_est_sans_effet(self):
        avant = self.relire()
        spec = self.patcher({'remove_models': ['Fantome'], 'remove_pages': ['Nulle part']})
        self.assertEqual([m['name'] for m in spec['data_models']], [m['name'] for m in avant['data_models']])
        self.assertEqual(len(spec['pages']), 1)

    def test_renommer_un_modele_sans_doublon_et_les_references_suivent(self):
        self.patcher({
            'data_models': [{'name': 'Stock', 'relationships': [{'name': 'produit', 'to_model': 'Produit'}]}],
            'endpoint_groups': [{'name': 'Produits', 'endpoints': [
                {'method': 'GET', 'path': '/api/produits/', 'linked_model_name': 'Produit'}]}],
            'pages': [{'name': 'Liste', 'components': [{'type': 'table', 'linked_model': 'Produit'}]}],
        })
        spec = self.patcher({'data_models': [{'name': 'Article', 'rename_from': 'Produit',
                                              'description': 'Ce qui se vend'}]})
        self.assertCountEqual([m['name'] for m in spec['data_models']], ['Article', 'Stock'])
        article = self.nomme(spec['data_models'], 'Article')
        self.assertEqual((article['description'], [c['name'] for c in article['fields']]), ('Ce qui se vend', ['nom']))
        self.assertEqual(self.nomme(spec['data_models'], 'Stock')['relationships'][0]['to_model'], 'Article')
        self.assertEqual(self.nomme(spec['endpoint_groups'], 'Produits')['endpoints'][0]['linked_model_name'], 'Article')
        self.assertEqual(spec['pages'][0]['components'][0]['linked_model'], 'Article')

    def test_renommer_un_groupe_un_service_une_page_garde_les_liens(self):
        spec = self.patcher({
            'endpoint_groups': [{'name': 'Catalogue', 'rename_from': 'Produits'}],
            'services': [{'name': 'CatalogueService', 'rename_from': 'ProduitService'}],
            'pages': [{'name': 'Catalogue', 'rename_from': 'Liste'}],
        })
        self.assertCountEqual([g['name'] for g in spec['endpoint_groups']], ['Catalogue', 'Commandes'])
        self.assertEqual(len(self.nomme(spec['endpoint_groups'], 'Catalogue')['endpoints']), 1)
        service = self.nomme(spec['services'], 'CatalogueService')
        self.assertEqual(service['endpoint_group_ids'], [self.nomme(spec['endpoint_groups'], 'Catalogue')['id']])
        self.assertEqual(len(spec['services']), 2)
        page, = spec['pages']
        self.assertEqual((page['name'], page['service_ids'], page['route']), ('Catalogue', [service['id']], '/produits'))

    def test_renommer_vers_un_nom_pris_est_refuse(self):
        refus = self.patcher({'endpoint_groups': [{'name': 'Commandes', 'rename_from': 'Produits'}]}, attendu=400)
        self.assertIn('déjà pris', refus['details'][0])
        self.assertEqual(len(self.relire()['endpoint_groups']), 2)

    def test_renommer_deux_fois_ne_cree_pas_de_doublon(self):
        patch = {'data_models': [{'name': 'Article', 'rename_from': 'Produit'}]}
        self.patcher(patch)
        spec = self.patcher(patch)
        self.assertEqual([m['name'] for m in spec['data_models']], ['Article'])


class PatchReferencesTests(_PatchBase):

    def test_reference_vers_un_element_absent_refusee_spec_inchangee(self):
        avant = self.relire()
        cas = {
            'modèle « Fantome »': {'endpoint_groups': [{'name': 'Produits', 'endpoints': [
                {'method': 'POST', 'path': '/api/x/', 'linked_model_name': 'Fantome'}]}]},
            'modèle « Ailleurs »': {'data_models': [{'name': 'Produit', 'relationships': [
                {'name': 'lien', 'to_model': 'Ailleurs'}]}]},
            "groupe d'endpoints « Inconnu »": {'services': [{'name': 'ProduitService',
                                                             'endpoint_group_names': ['Produits', 'Inconnu']}]},
            'service « AucunService »': {'pages': [{'name': 'Liste', 'service_names': ['AucunService']}]},
            'interaction « Survol »': {'pages': [{'name': 'Liste', 'pipelines': [
                {'name': 'Aide', 'trigger_interaction': 'Survol'}]}]},
            'le service « Absent »': {'pages': [{'name': 'Liste', 'pipelines': [
                {'name': 'Chargement', 'steps': [{'label': 'appel', 'type': 'service_call', 'service_name': 'Absent'}]}]}]},
            'un composant': {'pages': [{'name': 'Liste', 'components': [{'type': 'table', 'linked_model': 'Rien'}]}]},
        }
        for attendu, patch in cas.items():
            with self.subTest(attendu=attendu):
                refus = self.patcher(patch, attendu=400)
                self.assertIn(attendu, ' '.join(refus['details']))
                self.assertEqual(self.relire(), avant)
        self.assertEqual(PatchApplication.objects.count(), 0)

    def test_supprimer_un_element_encore_reference_est_refuse(self):
        self.patcher({'endpoint_groups': [{'name': 'Produits', 'endpoints': [
            {'method': 'GET', 'path': '/api/produits/', 'linked_model_name': 'Produit'}]}]})
        refus = self.patcher({'remove_models': ['Produit']}, attendu=400)
        self.assertIn('GET /api/produits/', refus['details'][0])
        refus = self.patcher({'pages': [{'name': 'Liste', 'remove_interactions': ['Glisser']}]}, attendu=400)
        self.assertIn('Glisser', refus['details'][0])
        # Le même retrait passe quand le patch corrige ce qui le référençait.
        spec = self.patcher({'remove_models': ['Produit'], 'endpoint_groups': [{'name': 'Produits', 'endpoints': [
            {'method': 'GET', 'path': '/api/produits/', 'linked_model_name': ''}]}]})
        self.assertEqual(spec['data_models'], [])

    def test_reference_satisfaite_dans_le_meme_patch_acceptee(self):
        spec = self.patcher({
            'pages': [{'name': 'Panier', 'service_names': ['PanierService'],
                       'interactions': [{'name': 'Valider', 'type': 'form'}],
                       'pipelines': [{'name': 'Commande', 'trigger_interaction': 'Valider', 'steps': [
                           {'label': 'envoi', 'type': 'service_call', 'service_name': 'PanierService'}]}]}],
            'services': [{'name': 'PanierService', 'endpoint_group_names': ['Panier']}],
            'endpoint_groups': [{'name': 'Panier', 'endpoints': [
                {'method': 'POST', 'path': '/api/panier/', 'linked_model_name': 'Ligne'}]}],
            'data_models': [{'name': 'Ligne'}],
        })
        self.assertEqual(self.nomme(spec['pages'], 'Panier')['service_ids'],
                         [self.nomme(spec['services'], 'PanierService')['id']])

    def test_une_incoherence_deja_presente_ne_bloque_pas_les_patchs_suivants(self):
        # Une spec éditée à la main peut déjà porter une référence morte :
        # seul ce que le patch ajoute d'incohérent le fait refuser.
        spec = self.relire()
        self.nomme(spec['endpoint_groups'], 'Produits')['endpoints'][0]['linked_model_name'] = 'Disparu'
        self.assertEqual(self.alice.put(f"/api/apps/{spec['id']}/", spec, format='json').status_code, 200)
        apres = self.patcher({'data_models': [{'name': 'Client'}]})
        self.assertEqual(len(apres['data_models']), 2)


class PatchHistoriqueTests(_PatchBase):

    def setUp(self):
        super().setUp()
        self.historique = f"/api/apps/{self.spec['id']}/patches/"

    def appliquer(self, patch):
        resp = self.alice.post(self.url, {'patch': patch}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()['application']

    def test_chaque_application_est_enregistree_et_relisible(self):
        premiere = self.appliquer({'data_models': [{'name': 'Client'}]})
        seconde = self.appliquer({'remove_models': ['Client']})
        self.assertEqual((premiere['mode'], premiere['summary'], premiere['undone_at']),
                         ('merge', '1 modèle(s)', None))
        liste = self.alice.get(self.historique).json()
        self.assertEqual([a['id'] for a in liste], [seconde['id'], premiere['id']])
        self.assertEqual(liste[0]['summary'], '−1 modèle(s)')
        self.assertNotIn('snapshot_before', liste[0])
        self.assertEqual(PatchApplication.objects.get(pk=premiere['id']).patch, {'data_models': [{'name': 'Client'}]})

    def test_annuler_rend_la_spec_d_avant(self):
        avant = self.relire()
        application = self.appliquer({
            'remove_services': ['ToutService'], 'set_meta': {'name': 'Autre', 'required_groups': ['amis']},
            'endpoint_groups': [{'name': 'Produits', 'remove_endpoints': ['GET /api/produits/']}],
            'pages': [{'name': 'Liste', 'layout': 'list', 'remove_pipelines': ['Chargement']}]})
        resp = self.alice.post(f"{self.historique}{application['id']}/undo/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIsNotNone(resp.json()['application']['undone_at'])
        rendue = resp.json()['spec']

        def sans_identifiants(spec):
            texte = json.dumps({c: spec[c] for c in ('name', 'description', 'app_type', 'required_groups',
                                                     'data_models', 'endpoint_groups', 'services', 'pages')})
            spec = json.loads(texte)
            groupes = {g['id']: g['name'] for g in spec['endpoint_groups']}
            services = {s['id']: s['name'] for s in spec['services']}
            for s in spec['services']:
                s['endpoint_group_ids'] = sorted(groupes[i] for i in s['endpoint_group_ids'])
            for p in spec['pages']:
                p['service_ids'] = sorted(services[i] for i in p['service_ids'])

            def retirer(v):
                if isinstance(v, dict):
                    return {k: retirer(x) for k, x in v.items() if k != 'id'}
                return [retirer(x) for x in v] if isinstance(v, list) else v
            return retirer(spec)

        self.assertEqual(sans_identifiants(rendue), sans_identifiants(avant))
        self.assertEqual(sans_identifiants(self.relire()), sans_identifiants(avant))

    def test_seul_le_dernier_patch_en_vigueur_s_annule_et_une_seule_fois(self):
        premiere = self.appliquer({'data_models': [{'name': 'Client'}]})
        seconde = self.appliquer({'data_models': [{'name': 'Facture'}]})
        resp = self.alice.post(f"{self.historique}{premiere['id']}/undo/")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(len(self.relire()['data_models']), 3)
        self.assertEqual(self.alice.post(f"{self.historique}{seconde['id']}/undo/").status_code, 200)
        self.assertEqual(self.alice.post(f"{self.historique}{seconde['id']}/undo/").status_code, 409)
        # Le précédent redevient le dernier en vigueur.
        self.assertEqual(self.alice.post(f"{self.historique}{premiere['id']}/undo/").status_code, 200)
        self.assertEqual([m['name'] for m in self.relire()['data_models']], ['Produit'])

    def test_l_historique_d_autrui_est_ferme(self):
        application = self.appliquer({'data_models': [{'name': 'Client'}]})
        bob = self.client_de('bob')
        self.assertEqual(bob.get(self.historique).status_code, 404)
        self.assertEqual(bob.post(f"{self.historique}{application['id']}/undo/").status_code, 404)
        sienne = bob.post('/api/apps/', {'name': 'À Bob'}, format='json').json()
        # L'identifiant d'un patch d'Alice sous la spec de Bob ne mène nulle part.
        self.assertEqual(bob.post(f"/api/apps/{sienne['id']}/patches/{application['id']}/undo/").status_code, 404)
        self.assertEqual(len(self.relire()['data_models']), 2)

    def test_l_historique_est_borne(self):
        with mock.patch.object(patching, 'HISTORIQUE_MAX', 3):
            ids = [self.appliquer({'data_models': [{'name': f'M{i}'}]})['id'] for i in range(5)]
        self.assertEqual([a['id'] for a in self.alice.get(self.historique).json()], ids[:1:-1])

    def test_supprimer_la_spec_supprime_son_historique(self):
        self.appliquer({'data_models': [{'name': 'Client'}]})
        self.alice.delete(f"/api/apps/{self.spec['id']}/")
        self.assertEqual(PatchApplication.objects.count(), 0)
