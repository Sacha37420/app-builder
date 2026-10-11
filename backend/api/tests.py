"""Tests backend d'app-builder.

    python manage.py test            (dans /app ; base PostgreSQL jetable, aucun réseau)

Trois familles :
  1. la serrure de l'API (Verrou 2) — de VRAIS jetons RS256 signés par une clé
     locale traversent `KeycloakJWTAuthentication` ; seul le téléchargement du
     JWKS de Keycloak est remplacé ;
  2. les règles d'autorisation de l'app — une spécification n'appartient qu'à
     son auteur (`owner_email`) ;
  3. les règles métier — résolution des identifiants temporaires du frontend,
     remplacement complet à l'enregistrement, protocole du chat IA (blocs
     CHOICES, sentinelle PATCH_READY, second échange dédié au patch JSON).

Aucun appel sortant : Anthropic et Mistral sont simulés.
"""
import json
import time
import unittest
from unittest import mock

import jwt
import requests
from cryptography.hazmat.primitives.asymmetric import rsa
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from api import views
from api.authentication import KeycloakJWTAuthentication
from api.models import AppSpec, EndpointGroup, FrontendService, Page

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

    @unittest.expectedFailure
    def test_layout_trop_long_refuse_proprement(self):
        # DÉFAUT (rapport chantier « tests ») : PageSerializer accepte un
        # `layout` de 50 caractères, la colonne `pages.layout` en tient 20
        # (comme le miroir de lab-admin). Entre 21 et 50 caractères, la
        # validation passe et PostgreSQL lève « value too long » : erreur 500
        # au lieu d'un 400. Correctif : max_length=20 dans le sérialiseur, ou
        # colonne élargie (et miroir de lab-admin avec).
        spec = _spec_complete()
        spec['pages'][0]['layout'] = 'tableau-de-bord-personnalise'
        resp = self.alice.post('/api/apps/', spec, format='json')
        self.assertEqual(resp.status_code, 400)

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


# ═══ 3 bis. Règles métier : protocole du chat IA ══════════════════════════════

class ExtractionTests(SimpleTestCase):

    def test_bloc_de_choix_extrait_et_retire_du_texte(self):
        texte = 'Quel type ?\nCHOICES_START\n{"multiple": false, "items": ["A", "B"]}\nCHOICES_END\nMerci.'
        propre, choix = views._extract_choices(texte)
        self.assertEqual(choix, {'multiple': False, 'items': ['A', 'B']})
        self.assertNotIn('CHOICES', propre)
        self.assertIn('Quel type ?', propre)
        self.assertIn('Merci.', propre)

    def test_bloc_de_choix_abime_laisse_le_texte_intact(self):
        for texte in ('rien du tout',
                      'CHOICES_START {"items": ["A"]}',                # jamais refermé
                      'CHOICES_START pas de json CHOICES_END',
                      'CHOICES_START {"items": [} CHOICES_END'):       # JSON invalide
            with self.subTest(texte=texte):
                self.assertEqual(views._extract_choices(texte), (texte, None))

    def test_sentinelle_patch_ready_seule_sur_sa_ligne(self):
        self.assertEqual(views._extract_patch_ready('Voici.\n  PATCH_READY  \n'), ('Voici.', True))
        self.assertEqual(views._extract_patch_ready('Début\nPATCH_READY\nFin'), ('Début\n\nFin', True))
        for texte in ('Le marqueur PATCH_READY sera émis plus tard.', 'PATCH_READY.', 'rien'):
            with self.subTest(texte=texte):
                self.assertEqual(views._extract_patch_ready(texte), (texte, False))

    def test_json_isole_de_son_emballage(self):
        self.assertEqual(json.loads(views._isolate_json('```json\n{"a": 1}\n```')), {'a': 1})
        self.assertEqual(json.loads(views._isolate_json('Voici : {"a": {"b": 2}} voilà')), {'a': {'b': 2}})
        self.assertEqual(views._isolate_json('aucun objet'), 'aucun objet')

    def test_un_patch_sans_cle_reconnue_est_vide(self):
        self.assertFalse(views._patch_has_content({}))
        self.assertFalse(views._patch_has_content({'data_models': [], 'pages': [], 'commentaire': 'x'}))
        self.assertTrue(views._patch_has_content({'set_meta': {'required_groups': ['famille']}}))
        self.assertTrue(views._patch_has_content({'remove_pages': ['Liste']}))

    def test_le_contexte_de_la_spec_est_injecte_dans_les_deux_prompts(self):
        spec = {'name': 'Épicerie ⟨unique⟩'}
        for prompt in (views._build_system_prompt(spec), views._build_patch_system_prompt(spec)):
            self.assertIn('Épicerie ⟨unique⟩', prompt)
            self.assertNotIn('{APP_SPEC}', prompt)
            self.assertNotIn('{SCHEMA_DOC}', prompt)
        # La consigne de cloisonnement fait partie du prompt conversationnel.
        self.assertIn('required_groups', views._build_system_prompt(spec))


class GenerationDuPatchTests(SimpleTestCase):
    BON = '{"data_models": [{"name": "Produit"}]}'

    def _generer(self, reponses):
        appels = mock.Mock(side_effect=reponses)
        with mock.patch.object(views, '_call_claude_once', appels):
            resultat = views._generate_patch('claude', 'cle', None, {}, [{'role': 'user', 'content': 'x'}], 'ok')
        return resultat, appels

    def test_premier_essai_valide(self):
        (patch, erreur), appels = self._generer([self.BON])
        self.assertEqual((patch, erreur), ({'data_models': [{'name': 'Produit'}]}, None))
        self.assertEqual(appels.call_count, 1)

    def test_reessaie_en_renvoyant_l_erreur_au_modele(self):
        (patch, erreur), appels = self._generer(['pas du json', '{"commentaire": "vide"}', self.BON])
        self.assertIsNone(erreur)
        self.assertEqual(patch['data_models'][0]['name'], 'Produit')
        self.assertEqual(appels.call_count, 3)
        # Chaque essai raté ajoute la réponse fautive et la correction demandée.
        derniers = appels.call_args_list[-1].args[2]
        self.assertEqual([m['role'] for m in derniers[-4:]], ['assistant', 'user', 'assistant', 'user'])
        self.assertIn('JSON invalide', derniers[-3]['content'])
        self.assertIn('sans clé reconnue', derniers[-1]['content'])

    def test_abandonne_apres_trois_essais(self):
        (patch, erreur), appels = self._generer(['non', 'non', 'non', self.BON])
        self.assertIsNone(patch)
        self.assertIn('JSON invalide', erreur)
        self.assertEqual(appels.call_count, 3)

    def test_une_panne_du_fournisseur_compte_comme_un_essai(self):
        (patch, erreur), appels = self._generer([RuntimeError('503'), RuntimeError('503'), RuntimeError('503')])
        self.assertIsNone(patch)
        self.assertIn('appel API échoué', erreur)
        self.assertEqual(appels.call_count, 3)

    def test_un_tableau_json_n_est_pas_un_patch(self):
        (patch, erreur), _ = self._generer(['[1, 2]'] * 3)
        self.assertIsNone(patch)
        self.assertIn('vide ou sans clé reconnue', erreur)


class _FluxClaude:
    def __init__(self, texte):
        self.text_stream = iter([texte[:5], texte[5:]])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _client_claude(texte, patch_brut='{}'):
    client = mock.Mock()
    client.messages.stream.return_value = _FluxClaude(texte)
    client.messages.create.return_value = mock.Mock(content=[mock.Mock(type='text', text=patch_brut)])
    return client


class ChatTests(Base):

    def setUp(self):
        super().setUp()
        self.alice = self.client_de('alice')
        self.corps = {'provider': 'claude', 'api_key': 'cle-de-alice',
                      'messages': [{'role': 'user', 'content': 'Une boutique'}], 'app_spec': {'name': 'B'}}

    def test_sans_cle_personnelle_aucun_appel_la_cle_du_serveur_ne_sert_pas(self):
        # Le chat se fait avec la clé de l'utilisateur. Les clés du .env
        # (ANTHROPIC_API_KEY / MISTRAL_API_KEY) ne doivent jamais financer
        # les conversations de tout compte autorisé.
        for provider in ('claude', 'mistral'):
            for cle in ('', '   ', None):
                corps = {**self.corps, 'provider': provider}
                if cle is None:
                    corps.pop('api_key')
                else:
                    corps['api_key'] = cle
                with self.subTest(provider=provider, cle=cle), \
                        mock.patch('anthropic.Anthropic') as anthropic_ctor, \
                        mock.patch.object(views.http_requests, 'post') as post:
                    resp = self.alice.post('/api/chat/', corps, format='json')
                    self.assertEqual(resp.status_code, 400)
                    anthropic_ctor.assert_not_called()
                    post.assert_not_called()

    def test_question_simple_un_seul_echange(self):
        client = _client_claude('Phase 1.\nQuel type ?\nCHOICES_START\n{"multiple": false, "items": ["A"]}\nCHOICES_END')
        with mock.patch('anthropic.Anthropic', return_value=client) as ctor:
            resp = self.alice.post('/api/chat/', self.corps, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ctor.call_args.kwargs, {'api_key': 'cle-de-alice'})
        donnees = resp.json()
        self.assertEqual(donnees['choices'], {'multiple': False, 'items': ['A']})
        self.assertIsNone(donnees['spec_patch'])
        self.assertNotIn('CHOICES', donnees['content'])
        client.messages.create.assert_not_called()
        self.assertIn('"name": "B"', client.messages.stream.call_args.kwargs['system'])

    def test_patch_ready_declenche_le_second_echange(self):
        client = _client_claude('Voici le modèle.\nPATCH_READY',
                                '```json\n{"set_meta": {"required_groups": ["famille"]}}\n```')
        with mock.patch('anthropic.Anthropic', return_value=client):
            donnees = self.alice.post('/api/chat/', self.corps, format='json').json()
        self.assertEqual(donnees['content'], 'Voici le modèle.')
        self.assertEqual(donnees['spec_patch'], {'set_meta': {'required_groups': ['famille']}})
        second = client.messages.create.call_args.kwargs
        self.assertEqual(second['messages'][-2], {'role': 'assistant', 'content': 'Voici le modèle.'})
        self.assertIn('STRICTEMENT', second['system'])

    def test_patch_impossible_signale_dans_la_reponse(self):
        client = _client_claude('Voici.\nPATCH_READY', 'désolé, pas de JSON')
        with mock.patch('anthropic.Anthropic', return_value=client):
            resp = self.alice.post('/api/chat/', self.corps, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()['spec_patch'])
        self.assertIn("n'a pas pu être généré", resp.json()['content'])
        self.assertEqual(client.messages.create.call_count, 3)

    def test_mistral_flux_reassemble_avec_la_cle_de_l_utilisateur(self):
        lignes = [b'', b': commentaire', b'data: {"choices": [{"delta": {"content": "Bon"}}]}',
                  b'data: pas du json', b'data: {"choices": [{"delta": {}}]}',
                  b'data: {"choices": [{"delta": {"content": "jour"}}]}', b'data: [DONE]',
                  b'data: {"choices": [{"delta": {"content": " ignore"}}]}']
        flux = mock.MagicMock()
        flux.__enter__.return_value.iter_lines.return_value = iter(lignes)
        with mock.patch.object(views.http_requests, 'post', return_value=flux) as post:
            resp = self.alice.post('/api/chat/', {**self.corps, 'provider': 'mistral'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['content'], 'Bonjour')
        self.assertEqual(resp.json()['provider'], 'mistral')
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer cle-de-alice')

    def test_pannes_du_fournisseur_rendues_en_erreur_de_passerelle(self):
        with mock.patch.object(views.http_requests, 'post', side_effect=requests.exceptions.ConnectTimeout()):
            resp = self.alice.post('/api/chat/', {**self.corps, 'provider': 'mistral'}, format='json')
        self.assertEqual(resp.status_code, 504)
        with mock.patch('anthropic.Anthropic', side_effect=RuntimeError('clé refusée')):
            resp = self.alice.post('/api/chat/', self.corps, format='json')
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.json(), {'error': 'clé refusée'})
