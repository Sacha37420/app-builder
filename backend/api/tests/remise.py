"""Lot 5 — cahier des charges, feuille de route et remise au lab (`/api/handoff/…`)."""
import copy
import json
import re
from unittest import mock

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

from api import remise, views
from api.ia import fournisseurs
from api.budget import LOT_BUDGET_JETONS, estimer_jetons
from api.models import AppSpec, PatchApplication

from .socle import Base, jeton

__all__ = ['FeuilleDeRouteGenereeTests', 'RemiseV2Tests', 'CahierDesChargesTests', 'RemiseAuLabTests']

# Expression de scripts/validate-app.sh (porte de qualité du déploiement), traduite de POSIX.
VALIDATE_APP = re.compile(r'^## Lot [0-9]+ — .+·[ \t\n\r\f\v]*statut : (à faire|en cours|livré)[ \t\n\r\f\v]*$')

# Tête de la feuille de route que pose le gabarit du lab (_templates/regles/FEUILLE_DE_ROUTE.md),
# une fois ses jokers remplacés par new-app.sh : c'est sur elle que le moteur greffe `lots_md`.
GABARIT = """# Feuille de route — ma-boutique

Ce fichier est lu par une machine : `validate-app.sh` refuse de déployer s'il manque ou s'il ne
contient aucun lot au format ci-dessous. Garder les titres tels quels.

## Commande de test
python manage.py test

## Lot 1 — Socle livré par le gabarit   ·   statut : livré
**Objectif :** partir d'une app qui démarre, s'authentifie par Keycloak et refuse qui n'est pas du groupe requis.
**Tâches :**
- [x] Scaffold par `new-app.sh` (aucune ligne modifiée à la main)
**Tests à passer avant de clore le lot :**
- [x] Tests backend du gabarit (commande ci-dessus)
**Vérifié le :** 2026-10-13 — scaffold généré.

## Lot 2 — <titre du premier lot métier>   ·   statut : à faire
**Objectif :** <ce que l'utilisateur pourra faire à la fin du lot, en une phrase>
**Vérifié le :** <date>
"""


def greffer(gabarit: str, lots_md: str) -> str:
    """Ce que fait le moteur (contrat I2) : garder tout ce qui précède la première
    ligne « ## Lot 2 — », remplacer le reste par la graine."""
    lignes = gabarit.split('\n')
    coupe = next(i for i, ligne in enumerate(lignes) if ligne.startswith('## Lot 2 — '))
    return '\n'.join(lignes[:coupe]) + '\n' + lots_md


def spec_riche() -> dict:
    """Une spec sérialisée (identifiants réels), comme la rend l'API."""
    return {
        'name': 'Gestion de stock', 'project_name': 'gestion-stock', 'app_type': 'django-angular',
        'description': 'Suivre les produits et les mouvements.\nAlerter sous le seuil.',
        'required_groups': ['developers', 'famille'], 'uses_email': True,
        'business_rules': [{'title': 'Stock jamais négatif', 'description': 'Une sortie supérieure au stock est refusée.'}],
        'data_models': [
            {'id': 1, 'name': 'Produit', 'description': 'Ce qui est stocké', 'order': 0,
             'fields': [{'name': 'nom', 'type': 'string', 'required': True, 'unique': True, 'max_length': 200},
                        {'name': 'photo', 'type': 'storage_file', 'required': False}],
             'relationships': []},
            {'id': 2, 'name': 'Mouvement', 'description': '', 'order': 1,
             'fields': [{'name': 'quantite', 'type': 'int', 'required': True}],
             'relationships': [{'name': 'produit', 'rel_type': 'FK', 'to_model': 'Produit',
                                'related_name': 'mouvements', 'on_delete': 'PROTECT'}]},
        ],
        'endpoint_groups': [
            {'id': 10, 'name': 'Produits', 'description': 'Le catalogue', 'order': 0, 'endpoints': [
                {'method': 'GET', 'path': '/api/produits/', 'operation': 'list', 'linked_model_name': 'Produit',
                 'auth_required': True, 'required_roles': [], 'description': 'Liste', 'public_reason': '',
                 'query_params': [{'name': 'q', 'type': 'string', 'required': False}],
                 'request_schema': None, 'response_schema': {'nom': 'string'},
                 'steps': [{'label': 'Requête', 'type': 'db_query', 'description': 'tri par nom'}]},
                {'method': 'POST', 'path': '/api/produits/', 'operation': 'create', 'linked_model_name': 'Produit',
                 'auth_required': True, 'required_roles': ['manager'], 'description': '', 'public_reason': '',
                 'query_params': [], 'request_schema': {'nom': 'string'}, 'response_schema': None, 'steps': []},
                {'method': 'GET', 'path': '/api/vitrine/', 'operation': 'custom', 'linked_model_name': '',
                 'auth_required': False, 'required_roles': [], 'description': '',
                 'public_reason': 'La vitrine se consulte sans compte.',
                 'query_params': [], 'request_schema': None, 'response_schema': None, 'steps': []},
            ]},
            {'id': 11, 'name': 'Mouvements', 'description': '', 'order': 1, 'endpoints': [
                {'method': 'GET', 'path': '/api/ouvert/', 'operation': 'list', 'linked_model_name': 'Mouvement',
                 'auth_required': False, 'required_roles': [], 'description': '', 'public_reason': '',
                 'query_params': [], 'request_schema': None, 'response_schema': None, 'steps': []}]},
        ],
        'services': [{'id': 20, 'name': 'ProduitService', 'order': 0, 'endpoint_group_ids': [10]}],
        'pages': [{
            'id': 30, 'name': 'ListeProduits', 'route': '/produits', 'layout': 'list', 'order': 0, 'service_ids': [20],
            'components': [{'type': 'table', 'label': 'Tableau', 'linked_model': 'Produit', 'fields': ['nom']}],
            'interactions': [{'name': 'Page chargée', 'type': 'display', 'description': 'au chargement', 'order': 0}],
            'pipelines': [{'name': 'Chargement', 'description': '', 'trigger_interaction': 'Page chargée', 'order': 0,
                           'steps': [{'label': 'Appel', 'type': 'service_call', 'service_name': 'ProduitService',
                                      'service_method': 'ProduitService.getAll()', 'on_error': 'bandeau'}]}],
        }],
    }


def spec_v2() -> dict:
    """`spec_riche` enrichie des structures du métamodèle v2 (contrat app-builder-v2, I1)."""
    spec = spec_riche()
    spec['roles'] = [
        {'name': 'manager', 'kind': 'keycloak_group', 'description': 'Gère le catalogue.', 'implies': ['magasinier']},
        {'name': 'magasinier', 'kind': 'keycloak_group', 'description': ''},
        {'name': 'editeur', 'kind': 'object_role', 'on_model': 'Partage', 'description': 'Peut modifier un produit partagé.'}]
    produit, mouvement = spec['data_models']
    produit.update(kind='entity', access={
        'scope': 'shared', 'owner_field': 'owner_email', 'share_model': 'Partage', 'public_flag': 'publie',
        'rules': [{'action': 'read', 'who': ['owner']}, {'action': 'delete', 'who': ['role:manager']},
                  {'action': 'update', 'who': ['owner', 'share:editeur']}],
        'hidden_fields': [{'field': 'prix_achat', 'unless': 'role:manager'}], 'reason': 'Le prix d\'achat est confidentiel.'},
        constraints=[{'kind': 'unique', 'fields': ['nom', 'owner_email'], 'name': 'nom_par_proprietaire'}])
    produit['fields'] += [
        {'name': 'statut', 'type': 'enum', 'values': ['brouillon', 'publie', 'archive'], 'required': True},
        {'name': 'stock', 'type': 'int', 'min': 0, 'max': 10000},
        {'name': 'reference', 'type': 'string', 'pattern': '^[A-Z]{3}-[0-9]+$', 'unique_ci': True},
        {'name': 'notice', 'type': 'storage_file', 'max_bytes': 5_000_000, 'accept': ['application/pdf']},
        {'name': 'zone', 'type': 'geometry', 'srid': 2154, 'geometry_kind': 'Polygon'},
        {'name': 'cle_fournisseur', 'type': 'secret', 'secret_scope': 'user'}]
    produit['states'] = {
        'field': 'statut', 'initial': 'brouillon', 'values': ['brouillon', 'publie', 'archive'],
        'transitions': [{'from': ['brouillon'], 'to': 'publie', 'by': ['owner', 'role:manager'],
                         'action': 'POST /api/produits/{id}/publier/', 'side_effects': ['notify:owner']},
                        {'from': ['publie'], 'to': 'archive', 'by': ['role:manager']}],
        'frozen_in': ['archive']}
    mouvement.update(kind='log', access={'scope': 'owner'})
    spec['business_rules'][0].update(applies_to='Mouvement', kind='invariant', enforced_by=['POST /api/mouvements/'])
    spec['endpoint_groups'][1]['endpoints'][0].update(
        auth={'mode': 'hmac_signature', 'caller': 'stripe', 'key_source': 'STRIPE_WEBHOOK_SECRET', 'reason': 'Webhook signé'})
    spec['pages'][0].update(public=False, required_roles=['manager'])
    spec['pages'][0]['components'][0]['config'] = {'pagination': 25, 'tri': {'champ': 'nom', 'sens': 'asc'}, 'titre': 'Catalogue'}
    spec['pages'].append({'id': 31, 'name': 'Vitrine', 'route': '/vitrine', 'layout': 'list', 'order': 1, 'service_ids': [],
                          'public': True, 'public_reason': 'Les clients consultent sans compte.',
                          'components': [], 'interactions': [], 'pipelines': []})
    spec['jobs'] = [{'name': 'Inventaire', 'kind': 'scheduled', 'trigger': 'every:30min', 'input_model': 'Produit',
                     'tracked_by': 'Mouvement', 'concurrency': 'one_per:Produit', 'heavy': False,
                     'description': 'Recalcule les seuils.'}]
    spec['integrations'] = [{'type': 'storage', 'mode': 'user_token', 'description': 'Notices des produits.'},
                            {'type': 'email', 'mode': '', 'description': 'Alertes de seuil.'}]
    spec['external_apis'] = [{'name': 'Stripe', 'purpose': 'paiement', 'auth': 'app_key', 'called_from': 'backend',
                              'description': 'Encaisse les commandes.'}]
    spec['extensions'] = {
        'data_io': [{'direction': 'import', 'format': 'csv', 'model': 'Produit', 'mode': 'upsert', 'async': True}],
        'realtime': [{'name': 'Stock en direct', 'transport': 'poll', 'description': 'Toutes les 10 s.'}],
        'computations': [{'name': 'Valeur du stock', 'inputs': ['Produit.stock'], 'output': 'euros', 'run': 'sync',
                          'verification': '3 × 4 € = 12 €'}],
        'notifications': [{'event': 'Produit.publie', 'channel': 'email', 'to': 'role:manager'}]}
    return spec


def graine(spec: dict) -> dict:
    liv = remise.livrables(spec, 12, '2026-10-13T09:20:11+02:00')
    return {'lots_md': liv['lots_md'], 'cahier_des_charges_md': liv['cahier_des_charges_md']}


class FeuilleDeRouteGenereeTests(SimpleTestCase):

    def test_la_graine_d_une_spec_prete_satisfait_les_regles_du_moteur(self):
        liv = remise.livrables(spec_riche(), 12, '2026-10-13T09:20:11+02:00')
        self.assertTrue(liv['ready'], liv['blockers'])
        self.assertEqual(remise.valider_graine(graine(spec_riche())), [])
        familles = [lot['family'] for lot in liv['lots']]
        self.assertEqual(familles, ['modeles', 'api', 'regles', 'services', 'pages', 'pipelines', 'recette'])
        self.assertEqual([lot['number'] for lot in liv['lots']], list(range(2, 9)))
        self.assertEqual(liv['counts'], {'data_models': 2, 'endpoints': 4, 'pages': 1, 'lots': 7})

    def test_ni_en_tete_ni_commande_de_test_ni_lot_1(self):
        texte = graine(spec_riche())['lots_md']
        lignes = texte.split('\n')
        self.assertTrue(lignes[0].startswith('## Lot 2 — Modèles de données'))
        self.assertTrue(lignes[0].endswith('   ·   statut : à faire'))
        self.assertNotIn('Commande de test\n', texte)
        self.assertNotIn('## Commande', texte)
        self.assertNotIn('## Lot 1 ', texte)
        self.assertNotIn('# Feuille de route', texte)
        # Toute ligne commençant par « # » est un titre de lot, « à faire ».
        for ligne in lignes:
            if ligne.startswith('#'):
                self.assertRegex(ligne, remise.TITRE_DE_LOT)

    def test_greffee_sur_le_gabarit_elle_passe_la_porte_de_validate_app(self):
        fichier = greffer(GABARIT, graine(spec_riche())['lots_md'])
        titres = [ligne for ligne in fichier.split('\n') if ligne.startswith('## Lot ')]
        self.assertEqual(len(titres), 8)
        for titre in titres:
            self.assertRegex(titre, VALIDATE_APP)
        self.assertEqual([int(re.match(r'## Lot (\d+)', t).group(1)) for t in titres], list(range(1, 9)))
        self.assertIn('statut : livré', titres[0])
        self.assertNotIn('<titre du premier lot métier>', fichier)
        # Une seule commande de test, d'une ligne, et c'est celle du lab.
        self.assertEqual(fichier.count('## Commande de test'), 1)
        self.assertIn('## Commande de test\npython manage.py test\n\n## Lot 1', fichier)

    def test_chaque_lot_a_des_taches_et_au_moins_un_test_nomme(self):
        liv = remise.livrables(spec_riche(), 12, 'x')
        for lot in liv['lots']:
            with self.subTest(lot=lot['title']):
                self.assertTrue(lot['tasks'])
                self.assertTrue(lot['tests'])
                self.assertTrue(lot['objective'])
                self.assertEqual(lot['tokens'], estimer_jetons(remise._rendre(lot)))
        par_famille = {lot['family']: lot for lot in liv['lots']}
        self.assertIn('`python manage.py test api.tests.ProduitModelTests` passe', par_famille['modeles']['tests'][0])
        self.assertIn('`python manage.py test api.tests.MouvementModelTests` passe', par_famille['modeles']['tests'][1])
        api = '\n'.join(par_famille['api']['tests'])
        self.assertIn('api.tests.ProduitsApiTests', api)
        self.assertIn('api.tests.MouvementsApiTests', api)
        self.assertIn('api.tests.StockJamaisNegatifRuleTests', par_famille['regles']['tests'][0])
        self.assertIn({'kind': 'endpoint_group', 'name': 'Produits'}, par_famille['api']['elements'])
        self.assertIn({'kind': 'pipeline', 'name': 'Chargement', 'page': 'ListeProduits'}, par_famille['pipelines']['elements'])

    def test_les_tests_d_api_derivent_des_endpoints_et_des_roles(self):
        api = next(lot for lot in remise.lots(spec_riche()) if lot['family'] == 'api')
        tests = '\n'.join(api['tests'])
        self.assertIn('`GET /api/produits/` : réponse attendue pour un membre du groupe developers ou famille', tests)
        self.assertIn("refus (403) d'un jeton émis pour un autre client (`azp`)", tests)
        self.assertIn("refus (403) d'un compte hors des groupes requis", tests)
        # Le rôle requis d'un endpoint donne son cas de refus.
        post = tests[tests.index('`POST /api/produits/`'):].split(' | ')[0]
        self.assertIn("refus (403) d'un membre qui n'est pas dans manager", post)
        self.assertNotIn('manager', tests[:tests.index('`POST /api/produits/`')])
        taches = '\n'.join(api['tasks'])
        self.assertIn('réservé aux groupes manager', taches)
        self.assertIn('paramètres : q (string)', taches)
        self.assertIn('étapes : Requête (tri par nom)', taches)

    def test_route_publique_decision_reportee_dans_la_feuille_de_route(self):
        api = next(lot for lot in remise.lots(spec_riche()) if lot['family'] == 'api')
        taches = '\n'.join(api['tasks'])
        self.assertIn('Décision explicite — route publique `GET /api/vitrine/` : La vitrine se consulte sans compte.', taches)
        self.assertIn('Décision explicite — route publique `GET /api/ouvert/` : JUSTIFICATION ABSENTE', taches)
        self.assertIn('`GET /api/vitrine/` répond sans jeton', '\n'.join(api['tests']))
        recette = remise.lots(spec_riche())[-1]
        self.assertIn('`GET /api/vitrine/`, `GET /api/ouvert/`', '\n'.join(recette['tasks']))

    def test_storage_et_email_reportes(self):
        lots = remise.lots(spec_riche())
        modeles = '\n'.join(lots[0]['tasks'])
        self.assertIn("Fichier `Produit.photo` : le modèle garde le chemin", modeles)
        self.assertIn('service storage', modeles)
        recette = '\n'.join(lots[-1]['tasks'])
        self.assertIn('`send_mail`', recette)
        self.assertIn('Storage : demander au lab', recette)

    def test_les_lots_suivent_le_type_d_app(self):
        spec = spec_riche()
        spec['app_type'] = 'django'
        self.assertEqual([lot['family'] for lot in remise.lots(spec)], ['modeles', 'api', 'regles', 'recette'])
        spec['app_type'] = 'angular'
        lots = remise.lots(spec)
        self.assertEqual([lot['family'] for lot in lots], ['services', 'pages', 'pipelines', 'recette'])
        # Sans serveur, la règle métier se vérifie à la recette.
        self.assertIn('Règle « Stock jamais négatif »', '\n'.join(lots[-1]['tasks']))
        for app_type in ('django', 'angular', 'django-angular'):
            spec['app_type'] = app_type
            self.assertEqual(remise.valider_graine(graine(spec)), [], app_type)
        # Une spec prête a toujours au moins un lot, même si rien ne relève de son type.
        seulement_des_pages = {**spec_riche(), 'app_type': 'django', 'data_models': [], 'endpoint_groups': [],
                               'services': [], 'business_rules': [],
                               'pages': [{'id': 30, 'name': 'Accueil', 'route': '/', 'layout': 'mixed', 'service_ids': [],
                                          'components': [], 'interactions': [], 'pipelines': []}]}
        liv = remise.livrables(seulement_des_pages, 1, 'x')
        self.assertEqual(([lot['family'] for lot in liv['lots']], liv['ready']), (['recette'], True))
        self.assertEqual(remise.valider_graine({'lots_md': liv['lots_md'], 'cahier_des_charges_md': 'x'}), [])

    def test_spec_vide_aucun_lot(self):
        vide = {'name': 'Vide', 'project_name': 'vide', 'app_type': 'django-angular', 'required_groups': ['famille']}
        liv = remise.livrables(vide, 1, 'x')
        self.assertEqual((liv['lots'], liv['lots_md'], liv['counts']['lots']), ([], '', 0))
        self.assertEqual([b['code'] for b in liv['blockers']], ['empty'])
        self.assertEqual(liv['context']['largest_lot_tokens'], 0)

    def test_un_texte_saisi_ne_peut_pas_casser_le_format(self):
        poison = 'x\n## Lot 99 — Pirate   ·   statut : livré\r\n# Titre\x00 `code` \u2028# autre\x85## Lot 1 — y · statut : à faire'
        spec = spec_riche()
        spec['name'] = spec['description'] = poison
        spec['business_rules'] = [{'title': poison, 'description': poison}]
        for m in spec['data_models']:
            m['name'] = m['name'] + poison
            m['description'] = poison
            m['fields'][0].update(name=poison, help_text=poison, default=poison)
        spec['data_models'][1]['relationships'][0].update(to_model=spec['data_models'][0]['name'], name=poison, related_name=poison)
        for g in spec['endpoint_groups']:
            g['name'] = g['description'] = poison + str(g['id'])
            for e in g['endpoints']:
                e.update(path='/api/' + poison, description=poison, public_reason=poison, required_roles=[poison],
                         linked_model_name='', steps=[{'label': poison, 'description': poison}],
                         query_params=[{'name': poison, 'type': poison}], request_schema={poison: poison})
        spec['services'][0]['name'] = poison
        page = spec['pages'][0]
        page.update(name=poison, route=poison, layout=poison)
        page['components'][0].update(label=poison, linked_model='', fields=[poison], type=poison)
        page['interactions'][0].update(name=poison, description=poison, type=poison)
        page['pipelines'][0].update(name=poison, description=poison, trigger_interaction=poison)
        page['pipelines'][0]['steps'][0].update(label=poison, service_method=poison, on_error=poison, service_name='')
        spec['required_groups'] = ['famille', poison]

        avant = len(remise.lots(spec_riche()))
        g = graine(spec)
        self.assertEqual(remise.valider_graine(g), [])
        self.assertEqual(len(re.findall(r'^## Lot ', g['lots_md'], flags=re.M)), avant)
        for texte in g.values():
            for interdit in ('\r', '\x00', '\u2028', '\x85'):
                self.assertNotIn(interdit, texte)
        for ligne in g['lots_md'].split('\n'):
            self.assertFalse(ligne.startswith('#') and not remise.TITRE_DE_LOT.match(ligne), ligne)
        # Les clés du métamodèle v2 ne cassent rien non plus.
        v2 = spec_v2()
        v2['roles'] = [{'name': poison, 'kind': poison, 'description': poison, 'implies': [poison], 'on_model': poison}]
        v2['jobs'] = [{k: poison for k in ('name', 'kind', 'trigger', 'input_model', 'tracked_by', 'concurrency', 'description')}]
        v2['integrations'] = [{'type': poison, 'mode': poison, 'description': poison}]
        v2['external_apis'] = [{k: poison for k in ('name', 'purpose', 'auth', 'called_from', 'description')}]
        v2['extensions'] = {'data_io': [{k: poison for k in ('direction', 'format', 'model', 'mode')}],
                            'realtime': [{'name': poison, 'transport': poison, 'description': poison}],
                            'computations': [{'name': poison, 'inputs': [poison], 'output': poison, 'run': poison,
                                              'verification': poison}],
                            'notifications': [{'event': poison, 'channel': poison, 'to': poison}]}
        for m in v2['data_models']:
            m.update(kind=poison, description=poison, constraints=[{'kind': poison, 'fields': [poison], 'condition': poison,
                                                                    'name': poison}],
                     access={'scope': 'owner', 'owner_field': poison, 'parent': poison, 'share_model': poison,
                             'public_flag': poison, 'reason': poison,
                             'rules': [{'action': poison, 'who': [poison, 'role:' + poison]}, {'action': 'read', 'who': [poison]}],
                             'hidden_fields': [{'field': poison, 'unless': poison}]},
                     states={'field': poison, 'initial': poison, 'values': [poison], 'frozen_in': [poison],
                             'transitions': [{'from': [poison], 'to': poison, 'by': [poison], 'action': poison,
                                              'side_effects': [poison]}]})
            for f in m['fields']:
                f.update(values=[poison], pattern=poison, accept=poison, geometry_kind=poison, secret_scope=poison)
        v2['business_rules'][0].update(title=poison, description=poison, applies_to=poison, kind=poison, enforced_by=[poison])
        for gr in v2['endpoint_groups']:
            for e in gr['endpoints']:
                e['auth'] = {'mode': poison, 'caller': poison, 'key_source': poison, 'reason': poison}
                e['steps'] = [{'type': poison, 'label': poison, 'description': poison}]
        for p in v2['pages']:
            p.update(public=True, public_reason=poison, required_roles=[poison], description=poison)
            for c in p['components']:
                c['config'] = {poison: poison, 'x': [poison]}
        g2 = graine(v2)
        self.assertEqual(remise.valider_graine(g2), [])
        for ligne in g2['lots_md'].split('\n'):
            self.assertFalse(ligne.startswith('#') and not remise.TITRE_DE_LOT.match(ligne), ligne)
        for texte in g2.values():
            for interdit in ('\r', '\x00', '\u2028', '\x85'):
                self.assertNotIn(interdit, texte)
        for ligne in g2['cahier_des_charges_md'].split('\n'):
            self.assertFalse(ligne.lstrip().startswith('#') and 'Pirate' in ligne, ligne)
        self.assertEqual(g['cahier_des_charges_md'].split('\n')[0],
                         '# Cahier des charges — x ## Lot 99 — Pirate · statut : livré # Titre `code` # autre ## Lot 1 — y · statut : à faire')

    def test_valeurs_de_types_inattendus_ne_font_pas_tomber_la_generation(self):
        spec = spec_riche()
        spec['data_models'].append({'name': None, 'fields': 'pas une liste', 'relationships': [None, 3]})
        spec['data_models'][0]['fields'] += [None, 'texte', {'name': 12, 'type': None, 'max_length': 'x'}]
        spec['endpoint_groups'].append({'name': 5, 'endpoints': [{'method': None, 'path': None, 'required_roles': 'x',
                                                                  'query_params': [3], 'steps': None, 'request_schema': []}]})
        spec['pages'].append({'name': None, 'route': None, 'service_ids': 'x', 'components': [{}], 'interactions': [{}],
                              'pipelines': [{'name': 'P', 'steps': [{}]}]})
        spec['business_rules'] = [None, {'title': None}, {'title': 'R'}]
        spec['required_groups'] = ['famille', None, 3]
        self.assertEqual(remise.valider_graine(graine(spec)), [])

    def test_noms_de_classes_de_test_uniques_et_valides(self):
        spec = spec_riche()
        spec['endpoint_groups'][1]['name'] = 'produits !'
        spec['endpoint_groups'].append({'id': 12, 'name': '§§§', 'endpoints': []})
        spec['endpoint_groups'].append({'id': 13, 'name': '2 étapes à l\'entrée', 'endpoints': []})
        api = '\n'.join(next(lot for lot in remise.lots(spec) if lot['family'] == 'api')['tests'])
        classes = re.findall(r'api\.tests\.(\w+)', api)
        self.assertEqual(classes, ['ProduitsApiTests', 'Produits2ApiTests', 'ElementApiTests', 'Element2EtapesALEntreeApiTests'])
        for c in classes:
            self.assertTrue(c.isidentifier() and c.isascii(), c)

    def test_generation_deterministe_et_sans_effet_sur_la_spec(self):
        spec = spec_riche()
        copie = copy.deepcopy(spec)
        self.assertEqual(remise.livrables(spec, 12, 'x'), remise.livrables(spec, 12, 'x'))
        self.assertEqual(spec, copie)

    # ── Découpe et budget de contexte ─────────────────────────────────────────

    def _groupes(self, nombre, endpoints, description=''):
        return [{'id': 100 + i, 'name': f'Groupe{i}', 'description': '', 'order': i, 'endpoints': [
            {'method': 'GET', 'path': f'/api/g{i}/e{j}/', 'operation': 'list', 'linked_model_name': '',
             'auth_required': True, 'required_roles': [], 'description': description} for j in range(endpoints)]}
                for i in range(nombre)]

    def test_les_petits_elements_sont_regroupes_les_gros_separes(self):
        spec = {**spec_riche(), 'endpoint_groups': self._groupes(6, 2), 'services': [], 'pages': []}
        self.assertEqual([lot['title'] for lot in remise.lots(spec) if lot['family'] == 'api'],
                         ['API — Groupe0, Groupe1, Groupe2…'])
        spec['endpoint_groups'] = self._groupes(4, 12, 'd' * 380)
        api = [lot for lot in remise.lots(spec) if lot['family'] == 'api']
        self.assertGreater(len(api), 1)
        for lot in api:
            self.assertLessEqual(lot['tokens'], LOT_BUDGET_JETONS)
        liv = remise.livrables(spec, 1, 'x')
        self.assertTrue(liv['ready'], liv['blockers'])
        self.assertEqual(liv['context']['largest_lot_tokens'], max(lot['tokens'] for lot in liv['lots']))

    def test_un_lot_qui_depasse_le_budget_rend_la_spec_non_prete(self):
        spec = {**spec_riche(), 'endpoint_groups': self._groupes(1, 200, 'd' * 380), 'services': [], 'pages': []}
        liv = remise.livrables(spec, 1, 'x')
        self.assertFalse(liv['ready'])
        self.assertEqual([b['code'] for b in liv['blockers']], ['context_budget'])
        self.assertIn('API — Groupe0', liv['blockers'][0]['message'])
        self.assertGreater(liv['context']['largest_lot_tokens'], LOT_BUDGET_JETONS)
        self.assertEqual(liv['context']['lot_budget_tokens'], 20000)

    def test_jamais_plus_de_quarante_lots_sinon_non_prete(self):
        # Beaucoup de groupes moyens : la taille visée est relevée pour tenir en 40 lots.
        spec = {**spec_riche(), 'endpoint_groups': self._groupes(120, 6, 'd' * 380), 'services': [], 'pages': []}
        liv = remise.livrables(spec, 1, 'x')
        self.assertLessEqual(len(liv['lots']), 40)
        self.assertTrue(all(lot['tokens'] <= LOT_BUDGET_JETONS for lot in liv['lots']))
        if liv['ready']:
            self.assertEqual(remise.valider_graine({'lots_md': liv['lots_md'],
                                                    'cahier_des_charges_md': liv['cahier_des_charges_md']}), [])
        else:
            self.assertEqual([b['code'] for b in liv['blockers']], ['context_budget'])
        # Trop vaste pour 40 lots de taille tenable : bloquée, jamais une graine que le moteur refuserait.
        spec['endpoint_groups'] = self._groupes(60, 40, 'd' * 380)
        liv = remise.livrables(spec, 1, 'x')
        self.assertFalse(liv['ready'])
        self.assertEqual([b['code'] for b in liv['blockers']], ['context_budget'])

    # ── Le contrôle lui-même (mêmes règles que le moteur) ─────────────────────

    def test_le_controle_de_graine_refuse_ce_que_le_moteur_refuse(self):
        bon = graine(spec_riche())
        lot = '## Lot {n} — Titre   ·   statut : à faire\n**Objectif :** x\n'
        refuses = {
            'pas un objet': 'texte',
            'clé manquante': {'lots_md': bon['lots_md']},
            'clé en trop': {**bon, 'path': '../x'},
            'vide': {**bon, 'cahier_des_charges_md': ''},
            'pas une chaîne': {**bon, 'lots_md': ['## Lot 2']},
            'retour chariot': {**bon, 'cahier_des_charges_md': 'a\r\nb'},
            'octet nul': {**bon, 'lots_md': bon['lots_md'] + '\x00'},
            'trop long': {**bon, 'lots_md': bon['lots_md'] + 'x' * 100_001},
            'cahier trop long': {**bon, 'cahier_des_charges_md': 'x' * 200_001},
            'titre libre': {**bon, 'lots_md': bon['lots_md'] + '\n# Annexe\n'},
            'commande de test': {**bon, 'lots_md': bon['lots_md'] + '\n## Commande de test\nrm -rf /\n'},
            'lot déjà livré': {**bon, 'lots_md': lot.format(n=2).replace('à faire', 'livré')},
            'commence par du texte': {**bon, 'lots_md': 'Bonjour\n' + lot.format(n=2)},
            'commence au lot 1': {**bon, 'lots_md': lot.format(n=1) + lot.format(n=2)},
            'commence au lot 3': {**bon, 'lots_md': lot.format(n=3)},
            'trou': {**bon, 'lots_md': lot.format(n=2) + lot.format(n=4)},
            'aucun lot': {**bon, 'lots_md': 'du texte seulement\n'},
            'plus de 40': {**bon, 'lots_md': ''.join(lot.format(n=n) for n in range(2, 43))},
        }
        for nom, g in refuses.items():
            with self.subTest(cas=nom):
                self.assertTrue(remise.valider_graine(g))
        self.assertEqual(remise.valider_graine(bon), [])
        self.assertEqual(remise.valider_graine({**bon, 'lots_md': ''.join(lot.format(n=n) for n in range(2, 42))}), [])

    def test_l_estimation_ne_depend_d_aucun_appel(self):
        with mock.patch('socket.socket', side_effect=AssertionError('appel réseau')):
            self.assertEqual(estimer_jetons(''), 0)
            self.assertEqual(estimer_jetons('abc'), 1)
            self.assertEqual(estimer_jetons('abcd'), 2)
            self.assertGreater(estimer_jetons('é' * 30), estimer_jetons('e' * 30))
            remise.livrables(spec_riche(), 1, 'x')


class RemiseV2Tests(SimpleTestCase):
    """Remise v2 (contrat app-builder-v2, I7) : cahier entier, structures I1, empreinte, lots dérivés."""

    def cahier(self, spec, etat='2026-11-11T10:00:00+01:00'):
        return remise.livrables(spec, 7, etat)['cahier_des_charges_md']

    def test_cahier_rend_description_de_plus_de_400_caracteres(self):
        spec = spec_v2()
        longue = 'Début. ' + 'mot ' * 300 + 'FIN-DE-LA-DESCRIPTION'
        spec['description'] = spec['data_models'][0]['description'] = longue
        spec['business_rules'][0]['description'] = longue
        spec['endpoint_groups'][0]['endpoints'][0]['description'] = longue
        spec['data_models'][0]['fields'][0]['help_text'] = longue
        spec['pages'][0]['interactions'][0]['description'] = longue
        spec['pages'][0]['pipelines'][0]['description'] = longue
        spec['roles'][0]['description'] = spec['jobs'][0]['description'] = longue
        self.assertGreater(len(longue), 1000)
        cahier = self.cahier(spec)
        self.assertGreaterEqual(cahier.count('FIN-DE-LA-DESCRIPTION'), 9)
        self.assertIn(longue.strip(), cahier)
        self.assertNotIn('…', cahier)
        # Dans la feuille de route, les plafonds restent (budget de contexte).
        lots_md = remise.livrables(spec, 7, 'x')['lots_md']
        self.assertIn('…', lots_md)
        self.assertEqual(remise.valider_graine(graine(spec)), [])

    def test_cahier_rend_config_des_composants(self):
        cahier = self.cahier(spec_v2())
        self.assertIn('- Composant : table « Tableau » sur `Produit` (champs : nom)', cahier)
        self.assertIn('  - pagination : 25', cahier)
        self.assertIn('  - titre : Catalogue', cahier)
        self.assertIn('  - tri : {"champ":"nom","sens":"asc"}', cahier)
        # Le type de chaque étape est toujours rendu.
        self.assertIn('Appel (type service_call ; ProduitService.getAll()', cahier)
        self.assertIn('Requête [db_query] (tri par nom)', cahier)

    def test_cahier_rend_les_structures_v2(self):
        cahier = self.cahier(spec_v2())
        for attendu in (
            # rôles
            '### Rôles de l\'app',
            '- `manager` (groupe Keycloak) ; inclut : `magasinier` — Gère le catalogue.',
            '- `editeur` (rôle sur un objet, porté par `Partage`) — Peut modifier un produit partagé.',
            # accès, nature, contraintes, attributs de champ
            '- Nature : entity',
            '- Accès : portée shared ; champ propriétaire `owner_email` ; partages par `Partage` ; '
            'lecture anonyme si `publie` ; read : owner ; delete : role:manager ; update : owner, share:editeur ; '
            '`prix_achat` masqué sauf pour role:manager ; raison : Le prix d\'achat est confidentiel.',
            '- Accès : portée owner',
            '- contrainte : unique sur `nom`, `owner_email` (nom `nom_par_proprietaire`)',
            '`statut` (enum, requis, valeurs : brouillon, publie, archive)',
            '`stock` (int, requis, minimum 0, maximum 10000)',
            '`reference` (string, requis, unique sans tenir compte de la casse, motif `^[A-Z]{3}-[0-9]+$`)',
            '`notice` (storage_file, requis, 5000000 octets au plus, types acceptés : application/pdf)',
            '`zone` (geometry, requis, géométrie Polygon, SRID 2154)',
            '`cle_fournisseur` (secret, requis) — secret chiffré au coffre (portée user), jamais rendu par l\'API',
            # états
            '- Cycle de vie : états de `statut` : brouillon, publie, archive (initial `brouillon`)',
            '  - transition brouillon → publie par owner, role:manager (action `POST /api/produits/{id}/publier/`) ; '
            'effets : notify:owner',
            '  - gelé (plus aucune modification) dans : `archive`',
            # règles métier
            '- **Stock jamais négatif** (nature invariant ; porte sur `Mouvement` ; tenue par `POST /api/mouvements/`)',
            # auth des endpoints, pages
            'authentification hmac_signature, appelant stripe, clé : STRIPE_WEBHOOK_SECRET (Webhook signé)',
            '; réservée aux rôles manager',
            '; PAGE PUBLIQUE (sans connexion) : Les clients consultent sans compte.',
            # jobs, intégrations, API externes
            '- Tâche de fond `Inventaire` (scheduled, déclenchée par `every:30min`, sur `Produit`, suivie dans '
            '`Mouvement`, concurrence one_per:Produit) : Recalcule les seuils.',
            '- `storage` (mode user_token) — Notices des produits.',
            '- `email` — Alertes de seuil.',
            '- **Stripe** (usage : paiement ; authentification : app_key ; appelée depuis : backend) — Encaisse les commandes.',
            # extensions
            '- import csv de `Produit` (mode upsert), en tâche de fond',
            '- « Stock en direct » (poll) — Toutes les 10 s.',
            '- « Valeur du stock » à partir de `Produit.stock` → euros (sync) ; vérification : 3 × 4 € = 12 €',
            '- sur `Produit.publie` : email au rôle manager',
        ):
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, cahier)
        # Accès non décrit : la règle par défaut est écrite.
        self.assertIn('- Accès : non décrit : par défaut, propriétaire seul', self.cahier(spec_riche()))

    def test_types_inattendus_des_cles_v2_ne_font_rien_tomber(self):
        spec = spec_riche()
        spec.update(roles='x', jobs=[None, 3, {'name': 4}], integrations={'a': 1}, external_apis=[[]], extensions=[1])
        spec['data_models'][0].update(access='owner', states=[1], constraints={'a': 1}, kind=['x'])
        spec['data_models'][1].update(access={'rules': 'x', 'hidden_fields': [None], 'scope': 3},
                                      states={'transitions': [None, {'from': 'a', 'to': None}], 'frozen_in': 'x'})
        spec['data_models'][0]['fields'][0].update(values='x', min='1', max=None, accept=3, srid='x', max_bytes=True)
        spec['endpoint_groups'][0]['endpoints'][0]['auth'] = 'jwt'
        spec['pages'][0].update(public='oui', required_roles='manager')
        spec['pages'][0]['components'][0]['config'] = ['pas', 'un', 'objet']
        spec['business_rules'][0].update(enforced_by='x', applies_to=[1])
        spec['extensions'] = {'data_io': 'x', 'realtime': [None], 'computations': [{'name': 'c', 'inputs': 'x'}],
                              'notifications': [{'event': 'e', 'to': 3}]}
        self.assertEqual(remise.valider_graine(graine(spec)), [])

    # ── Empreinte ─────────────────────────────────────────────────────────────

    def test_empreinte_stable_si_seul_updated_at_change(self):
        spec = spec_v2()
        a = remise.livrables(spec, 7, '2026-11-11T10:00:00+01:00')
        b = remise.livrables(spec, 7, '2026-12-25T23:59:59+01:00')
        self.assertRegex(a['fingerprint'], r'^sha256:[0-9a-f]{64}$')
        self.assertEqual(a['fingerprint'], b['fingerprint'])
        self.assertNotEqual(a['cahier_des_charges_md'], b['cahier_des_charges_md'])
        lignes = a['cahier_des_charges_md'].split('\n')
        self.assertEqual(lignes[2], 'Spécification App Builder n° 7, état du 2026-11-11T10:00:00+01:00.')
        self.assertEqual(lignes[3], f"Empreinte de la spécification : {a['fingerprint']}.")
        self.assertEqual(remise.empreinte(a['lots_md'], a['cahier_des_charges_md']), a['fingerprint'])
        # Recalcul indépendant : sha256 de lots_md + « \n » + cahier privé de ses lignes d'état et d'empreinte.
        import hashlib
        prive = '\n'.join(lignes[:2] + lignes[4:])
        self.assertEqual(a['fingerprint'],
                         'sha256:' + hashlib.sha256((a['lots_md'] + '\n' + prive).encode('utf-8')).hexdigest())

    def test_empreinte_change_si_un_champ_change(self):
        base = remise.livrables(spec_v2(), 7, 'x')['fingerprint']
        variantes = []
        s = spec_v2(); s['data_models'][0]['fields'][0]['max_length'] = 201; variantes.append(s)
        s = spec_v2(); s['data_models'][0]['access']['rules'][0]['who'] = ['member']; variantes.append(s)
        s = spec_v2(); s['pages'][0]['components'][0]['config']['pagination'] = 50; variantes.append(s)
        s = spec_v2(); s['jobs'][0]['description'] = 'Autre chose.'; variantes.append(s)
        s = spec_v2(); s['description'] += ' Une phrase de plus.'; variantes.append(s)
        vus = {base}
        for v in variantes:
            e = remise.livrables(v, 7, 'x')['fingerprint']
            self.assertNotIn(e, vus)
            vus.add(e)

    # ── Lots ──────────────────────────────────────────────────────────────────

    def test_lots_derivent_des_regles_d_acces_et_des_transitions(self):
        lots = remise.lots(spec_v2())
        modeles = next(lot for lot in lots if lot['family'] == 'modeles')
        tests = '\n'.join(modeles['tests'])
        acces = next(t for t in modeles['tests'] if 'api.tests.ProduitAccessTests' in t)
        for attendu in ("lecture d'un `Produit` permise au propriétaire",
                        "un non-propriétaire ne lit pas les `Produit` d'un autre",
                        'un membre sans le rôle manager ne supprime pas un `Produit`',
                        "un compte qui n'est ni le propriétaire ni un partage « editeur » ne modifie pas un `Produit`",
                        "lecture anonyme d'un `Produit` seulement si `publie` est vrai",
                        "`prix_achat` n'est pas rendu sauf au rôle manager"):
            self.assertIn(attendu, acces)
        self.assertIn("`python manage.py test api.tests.MouvementAccessTests` passe (un autre compte ne voit pas les "
                      "`Mouvement` de l'autre)", tests)
        etats = next(t for t in modeles['tests'] if 'api.tests.ProduitStateTests' in t)
        for attendu in ("un `Produit` créé est à l'état `brouillon`",
                        'transition brouillon → publie permise au propriétaire, au rôle manager',
                        "transition brouillon → publie refusée à un compte qui n'est ni le propriétaire ni le rôle manager",
                        'transition publie → archive refusée à un membre sans le rôle manager',
                        'une transition non déclarée de `statut` est refusée',
                        "un `Produit` à l'état `archive` n'est plus modifiable"):
            self.assertIn(attendu, etats)
        self.assertIn('unique sur `nom`, `owner_email` (nom `nom_par_proprietaire`) : violation refusée', tests)
        # Les tâches de fond ont leur lot (backend seulement).
        self.assertEqual([lot['family'] for lot in lots],
                         ['modeles', 'api', 'regles', 'jobs', 'services', 'pages', 'pipelines', 'recette'])
        jobs = next(lot for lot in lots if lot['family'] == 'jobs')
        self.assertEqual(jobs['elements'], [{'kind': 'job', 'name': 'Inventaire'}])
        self.assertIn('api.tests.InventaireJobTests', jobs['tests'][0])
        self.assertIn('un second lancement concurrent est refusé', jobs['tests'][0])
        self.assertEqual([lot['number'] for lot in lots], list(range(2, 2 + len(lots))))
        for lot in lots:
            self.assertEqual(set(lot), {'number', 'family', 'title', 'objective', 'tasks', 'tests', 'elements', 'tokens'})
        angular = {**spec_v2(), 'app_type': 'angular'}
        self.assertNotIn('jobs', [lot['family'] for lot in remise.lots(angular)])
        # Sans `access`, rien de nouveau : spec_riche garde ses lots.
        self.assertEqual(len(remise.lots(spec_riche())), 7)

    def test_titre_injecte_dans_une_description_neutralise_dans_le_cahier(self):
        spec = spec_v2()
        injecte = 'Première ligne.\n## Lot 99 — Pirate   ·   statut : à faire\n   # Titre indenté\nSous-titre\n===\n```\nfin'
        spec['description'] = spec['data_models'][0]['description'] = spec['endpoint_groups'][0]['description'] = injecte
        spec['business_rules'][0]['description'] = spec['roles'][0]['description'] = injecte
        spec['integrations'][0]['description'] = spec['external_apis'][0]['description'] = injecte
        cahier = self.cahier(spec)
        self.assertIn('\\## Lot 99 — Pirate', cahier)
        self.assertIn('   \\# Titre indenté', cahier)
        for ligne in cahier.split('\n'):
            nu = ligne.lstrip()
            self.assertFalse(nu.startswith('#') and ('Pirate' in ligne or 'indenté' in ligne), ligne)
            self.assertFalse(nu.startswith('```') or nu.startswith('==='), ligne)
        titres = [ligne for ligne in cahier.split('\n') if ligne.startswith('#')]
        self.assertFalse(any('Lot 99' in t for t in titres))
        self.assertEqual(remise.valider_graine(graine(spec)), [])

    def test_graine_d_une_spec_v2_riche_satisfait_le_moteur(self):
        liv = remise.livrables(spec_v2(), 12, '2026-11-11T10:00:00+01:00')
        self.assertTrue(liv['ready'], liv['blockers'])
        self.assertEqual(remise.valider_graine(graine(spec_v2())), [])
        fichier = greffer(GABARIT, liv['lots_md'])
        for titre in (ligne for ligne in fichier.split('\n') if ligne.startswith('## Lot ')):
            self.assertRegex(titre, VALIDATE_APP)

    def test_v2_deterministe_et_sans_effet_sur_la_spec(self):
        spec = spec_v2()
        copie = copy.deepcopy(spec)
        self.assertEqual(remise.livrables(spec, 12, 'x'), remise.livrables(spec, 12, 'x'))
        self.assertEqual(spec, copie)


# ── Par l'API ─────────────────────────────────────────────────────────────────

def _a_creer() -> dict:
    """La même spec, sous la forme que le frontend envoie (identifiants temporaires)."""
    spec = spec_riche()
    for g in spec['endpoint_groups']:
        g['id'] = -g['id']
    for s in spec['services']:
        s['id'], s['endpoint_group_ids'] = -s['id'], [-i for i in s['endpoint_group_ids']]
    for p in spec['pages']:
        p.pop('id')
        p['service_ids'] = [-i for i in p['service_ids']]
    for m in spec['data_models']:
        m.pop('id')
    return spec


SECRET = 'CONVERSATION-CONFIDENTIELLE sk-ant-api03-CLE-SECRETE'


class _AvecSpecs(Base):

    def setUp(self):
        super().setUp()
        self.alice = self.client_de('alice')
        resp = self.alice.post('/api/apps/', _a_creer(), format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.prete = resp.json()
        AppSpec.objects.filter(pk=self.prete['id']).update(
            chat_history=[{'role': 'user', 'content': SECRET, 'spec_patch': {'set_meta': {'name': SECRET}}}])
        self.spec_bob = AppSpec.objects.create(name='À Bob', project_name='a-bob', owner_email='bob@ssolab.local',
                                               required_groups=['famille'])


class CahierDesChargesTests(_AvecSpecs):

    def livrables(self):
        resp = self.alice.get(f"/api/apps/{self.prete['id']}/livrables/")
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()

    def test_groupes_regles_routes_publiques_et_stockage_y_figurent(self):
        liv = self.livrables()
        cahier = liv['cahier_des_charges_md']
        lignes = cahier.split('\n')
        self.assertEqual(lignes[0], '# Cahier des charges — Gestion de stock')
        self.assertIn(f"Spécification App Builder n° {self.prete['id']}, état du {liv['spec']['updated_at']}.", lignes)
        self.assertRegex(liv['spec']['updated_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$')
        for attendu in (
            'Groupes autorisés : `developers`, `famille`.',
            '`azp`',
            '- **Stock jamais négatif** — Une sortie supérieure au stock est refusée.',
            '- `GET /api/vitrine/` — La vitrine se consulte sans compte.',
            '- `GET /api/ouvert/` — JUSTIFICATION ABSENTE',
            'Fichiers des utilisateurs : `Produit.photo`',
            'service storage du lab',
            "Emails : l'app en envoie — `send_mail` de Django",
            'Nom du projet dans le lab : `gestion-stock`',
            "Type d'app : Django + Angular",
            '- `nom` (string, requis, unique, 200 caractères au plus)',
            '- relation `produit` → `Produit` (plusieurs vers un, à la suppression : PROTECT, accès inverse `mouvements`)',
            '### Page ListeProduits',
            'Conteneurs : gestion-stock-backend, gestion-stock-frontend',
            'Suivre les produits et les mouvements.\nAlerter sous le seuil.',
            '- Lot 2 — Modèles de données',
            'Identité « Foyer »',
        ):
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, cahier)
        self.assertNotIn('FileField(', cahier)
        self.assertEqual(liv['context']['cahier_tokens'], estimer_jetons(cahier))

    def test_les_livrables_decrivent_les_lots_et_l_etat(self):
        liv = self.livrables()
        self.assertEqual(set(liv), {'spec', 'ready', 'blockers', 'create', 'counts', 'context', 'lots', 'lots_md',
                                    'cahier_des_charges_md'})
        self.assertTrue(liv['ready'])
        self.assertEqual(liv['create'], {'name': 'gestion-stock', 'type': 'django-angular',
                                         'required_groups': ['developers', 'famille']})
        self.assertEqual(set(liv['lots'][0]), {'number', 'family', 'title', 'objective', 'tasks', 'tests', 'elements', 'tokens'})
        self.assertEqual(liv['lots'][0]['number'], 2)
        # Une spec pas encore prête se prévisualise quand même, avec ce qui la bloque.
        self.alice.patch(f"/api/apps/{self.prete['id']}/", {'required_groups': []}, format='json')
        liv = self.livrables()
        self.assertEqual((liv['ready'], [b['code'] for b in liv['blockers']]), (False, ['required_groups']))
        self.assertIn('Groupes autorisés : AUCUN', liv['cahier_des_charges_md'])
        self.assertTrue(liv['lots'])

    def test_export_d_autrui_impossible(self):
        bob = self.client_de('bob')
        for chemin in (f"/api/apps/{self.prete['id']}/livrables/", f"/api/handoff/specs/{self.prete['id']}/",
                       f"/api/handoff/specs/{self.prete['id']}/kit/"):
            with self.subTest(chemin=chemin):
                self.assertEqual(bob.get(chemin).status_code, 404)
        self.assertIn(APIClient().get(f"/api/apps/{self.prete['id']}/livrables/").status_code, (401, 403))
        self.assertEqual(self.alice.post(f"/api/apps/{self.prete['id']}/livrables/", {}, format='json').status_code, 405)
        # Un jeton lab-admin n'ouvre pas la prévisualisation de l'éditeur, seulement la remise.
        with override_settings(KEYCLOAK_HANDOFF_CLIENTS='lab-admin'):
            lab = self.client_de('alice', azp='lab-admin')
            self.assertEqual(lab.get(f"/api/apps/{self.prete['id']}/livrables/").status_code, 403)

    def test_la_conversation_n_entre_jamais_dans_les_livrables(self):
        self.assertNotIn('CONFIDENTIELLE', json.dumps(self.livrables(), ensure_ascii=False))


@override_settings(KEYCLOAK_HANDOFF_CLIENTS='lab-admin')
class RemiseAuLabTests(_AvecSpecs):

    def setUp(self):
        super().setUp()
        self.lab = self.client_de('alice', azp='lab-admin')
        pk = self.prete['id']
        self.routes = ['/api/handoff/specs/', f'/api/handoff/specs/{pk}/', f'/api/handoff/specs/{pk}/kit/']

    # ── Qui entre ─────────────────────────────────────────────────────────────

    def test_jeton_lab_admin_accepte_sur_les_routes_de_remise(self):
        for chemin in self.routes:
            with self.subTest(chemin=chemin):
                self.assertEqual(self.lab.get(chemin).status_code, 200)
                # Le client d'App Builder lui-même y entre aussi.
                self.assertEqual(self.alice.get(chemin).status_code, 200)

    def test_jeton_lab_admin_refuse_partout_ailleurs(self):
        pk = self.prete['id']
        ailleurs = [('get', '/api/me/'), ('get', '/api/apps/'), ('post', '/api/apps/'), ('get', f'/api/apps/{pk}/'),
                    ('put', f'/api/apps/{pk}/'), ('patch', f'/api/apps/{pk}/'), ('delete', f'/api/apps/{pk}/'),
                    ('patch', f'/api/apps/{pk}/chat/'), ('post', f'/api/apps/{pk}/patch/'),
                    ('get', f'/api/apps/{pk}/patches/'), ('post', f'/api/apps/{pk}/patches/1/undo/'),
                    ('get', f'/api/apps/{pk}/lab/'), ('get', f'/api/apps/{pk}/livrables/'), ('post', '/api/chat/')]
        for methode, chemin in ailleurs:
            with self.subTest(appel=f'{methode} {chemin}'):
                resp = getattr(self.lab, methode)(chemin, {'name': 'volé'}, format='json')
                self.assertEqual(resp.status_code, 403)
                self.assertIn('client non autorisé', resp.json()['detail'])
        self.assertEqual(AppSpec.objects.get(pk=pk).name, 'Gestion de stock')

    @override_settings(KEYCLOAK_HANDOFF_CLIENTS='')
    def test_sans_configuration_seul_le_client_de_l_app_entre(self):
        for chemin in self.routes:
            with self.subTest(chemin=chemin):
                self.assertEqual(self.lab.get(chemin).status_code, 403)
                self.assertEqual(self.alice.get(chemin).status_code, 200)

    def test_jeton_d_un_autre_client_refuse(self):
        for azp in ('storage', 'lab-mcp', 'lab-admin-admin', 'LAB-ADMIN', 'lab-admin ', '', None):
            for chemin in self.routes:
                with self.subTest(azp=azp, chemin=chemin):
                    resp = self.client_de('alice', azp=azp).get(chemin)
                    self.assertEqual(resp.status_code, 403)
                    self.assertIn('detail', resp.json())

    def test_clients_integres_du_realm_refuses_meme_listes(self):
        integres = ['admin-cli', 'account', 'account-console', 'broker', 'realm-management', 'security-admin-console']
        with override_settings(KEYCLOAK_HANDOFF_CLIENTS='lab-admin, ' + ','.join(integres)):
            for azp in integres:
                for chemin in self.routes + ['/api/me/', '/api/apps/']:
                    with self.subTest(azp=azp, chemin=chemin):
                        self.assertEqual(self.client_de('alice', groups=['developers', 'admins'], azp=azp).get(chemin).status_code, 403)
            self.assertEqual(self.lab.get(self.routes[0]).status_code, 200)

    def test_sans_jeton_401_jeton_refuse_403(self):
        from .socle import _AUTRE_RSA
        for chemin in self.routes:
            with self.subTest(chemin=chemin):
                resp = APIClient().get(chemin)
                self.assertEqual(resp.status_code, 401)
                self.assertIn('detail', resp.json())
                # Jeton qui n'en est pas un, expiré ou signé par une autre clé : pas de jeton valable.
                self.assertEqual(self.avec('pas.un.jeton').get(chemin).status_code, 401)
                self.assertEqual(self.client_de('alice', azp='lab-admin', exp=-60).get(chemin).status_code, 401)
                self.assertEqual(self.avec(jeton('alice', azp='lab-admin', cle=_AUTRE_RSA)).get(chemin).status_code, 401)
                # Jeton valable mais refusé ici : hors groupe, sans email.
                for refuse in (self.client_de('lea', azp='lab-admin', groups=['inconnus']),
                               self.client_de('lea', azp='lab-admin', groups=[]),
                               self.client_de('alice', azp='lab-admin', email=None)):
                    resp = refuse.get(chemin)
                    self.assertEqual(resp.status_code, 403)
                    self.assertIn('detail', resp.json())

    # ── Ce qu'on y voit ───────────────────────────────────────────────────────

    def test_specs_d_autrui_invisibles_et_indistinctes_d_une_spec_absente(self):
        self.assertEqual([s['id'] for s in self.lab.get(self.routes[0]).json()], [self.prete['id']])
        absente = self.lab.get('/api/handoff/specs/999999/')
        for suffixe in ('', 'kit/'):
            resp = self.lab.get(f'/api/handoff/specs/{self.spec_bob.pk}/{suffixe}')
            self.assertEqual((resp.status_code, resp.json()), (404, absente.json()))
            self.assertEqual(set(resp.json()), {'detail'})
        # Être admin du lab ne change rien : chacun ne voit que les siennes.
        chef = self.client_de('chef', azp='lab-admin', groups=['admins', 'developers'])
        self.assertEqual(chef.get(self.routes[0]).json(), [])
        self.assertEqual(chef.get(self.routes[1]).status_code, 404)
        bob = self.client_de('bob', azp='lab-admin')
        self.assertEqual([s['name'] for s in bob.get(self.routes[0]).json()], ['À Bob'])

    def test_aucune_ecriture(self):
        avant = (AppSpec.objects.count(), AppSpec.objects.get(pk=self.prete['id']).updated_at)
        for client in (self.lab, self.alice):
            for chemin in self.routes:
                for methode in ('post', 'put', 'patch', 'delete', 'head', 'options'):
                    with self.subTest(appel=f'{methode} {chemin}'):
                        resp = getattr(client, methode)(chemin, {'name': 'x'}, format='json')
                        self.assertEqual(resp.status_code, 405)
        for chemin in self.routes:
            self.lab.get(chemin)
        self.assertEqual((AppSpec.objects.count(), AppSpec.objects.get(pk=self.prete['id']).updated_at), avant)
        self.assertEqual(PatchApplication.objects.count(), 0)

    def test_liste_forme_exacte_et_plus_recent_d_abord(self):
        seconde = self.alice.post('/api/apps/', {'name': 'Brouillon'}, format='json').json()
        liste = self.lab.get(self.routes[0]).json()
        self.assertEqual([s['id'] for s in liste], [seconde['id'], self.prete['id']])
        prete = liste[1]
        self.assertEqual(set(prete), {'id', 'name', 'project_name', 'app_type', 'required_groups', 'updated_at',
                                      'ready', 'blockers', 'counts', 'fingerprint'})
        self.assertEqual(prete, {
            'id': self.prete['id'], 'name': 'Gestion de stock', 'project_name': 'gestion-stock',
            'app_type': 'django-angular', 'required_groups': ['developers', 'famille'],
            'updated_at': prete['updated_at'], 'ready': True, 'blockers': [],
            'counts': {'data_models': 2, 'endpoints': 4, 'pages': 1, 'lots': 7}, 'fingerprint': prete['fingerprint']})
        self.assertRegex(prete['fingerprint'], r'^sha256:[0-9a-f]{64}$')
        self.assertRegex(prete['updated_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$')
        brouillon = liste[0]
        self.assertEqual((brouillon['project_name'], brouillon['ready'], brouillon['counts']),
                         ('', False, {'data_models': 0, 'endpoints': 0, 'pages': 0, 'lots': 0}))
        self.assertEqual([b['code'] for b in brouillon['blockers']], ['project_name', 'required_groups', 'empty'])
        self.assertEqual(brouillon['blockers'][1], {
            'code': 'required_groups', 'message': "Aucun groupe requis : l'app serait ouverte à tout compte du lab."})
        for b in brouillon['blockers']:
            self.assertEqual(set(b), {'code', 'message'})
        self.assertEqual(self.client_de('personne', azp='lab-admin').get(self.routes[0]).json(), [])

    def test_ready_equivaut_a_blockers_vide_et_les_codes_sont_ceux_du_contrat(self):
        codes_du_contrat = {'project_name', 'app_type', 'required_groups', 'empty', 'file_field',
                            'orphan_reference', 'context_budget'}
        AppSpec.objects.create(name='Spring', app_type='spring', project_name='vieux', owner_email='alice@ssolab.local',
                               required_groups=['famille'])
        fichier = AppSpec.objects.create(name='Fichier', project_name='fichier', owner_email='alice@ssolab.local',
                                         required_groups=['famille'])
        fichier.data_models.create(name='Plat', fields=[{'name': 'photo', 'type': 'file'}],
                                   relationships=[{'name': 'x', 'to_model': 'Fantome'}])
        vus = set()
        for s in self.lab.get(self.routes[0]).json():
            self.assertEqual(s['ready'], s['blockers'] == [])
            vus |= {b['code'] for b in s['blockers']}
            if s['name'] == 'Spring':
                self.assertEqual((s['app_type'], [b['code'] for b in s['blockers']]), ('spring', ['app_type', 'empty']))
        self.assertLessEqual(vus, codes_du_contrat)
        self.assertGreaterEqual(vus, {'app_type', 'empty', 'file_field', 'orphan_reference'})

    def test_detail_ajoute_la_description_et_le_contexte(self):
        resume = self.lab.get(self.routes[0]).json()[0]
        detail = self.lab.get(self.routes[1]).json()
        self.assertEqual(set(detail) - set(resume), {'description', 'context'})
        self.assertEqual({c: detail[c] for c in resume}, resume)
        self.assertEqual(detail['description'], 'Suivre les produits et les mouvements.\nAlerter sous le seuil.')
        self.assertEqual(set(detail['context']), {'cahier_tokens', 'largest_lot_tokens', 'lot_budget_tokens'})
        for v in detail['context'].values():
            self.assertIs(type(v), int)
        self.assertEqual(detail['context']['lot_budget_tokens'], 20000)
        self.assertGreater(detail['context']['cahier_tokens'], detail['context']['largest_lot_tokens'] // 10)

    def test_kit_d_une_spec_non_prete_409(self):
        brouillon = self.alice.post('/api/apps/', {'name': 'Brouillon', 'project_name': 'brouillon'}, format='json').json()
        resp = self.lab.get(f"/api/handoff/specs/{brouillon['id']}/kit/")
        self.assertEqual(resp.status_code, 409)
        attendus = self.lab.get(f"/api/handoff/specs/{brouillon['id']}/").json()['blockers']
        self.assertEqual(resp.json(), {'error': 'not_ready', 'blockers': attendus})
        self.assertEqual([b['code'] for b in attendus], ['required_groups', 'empty'])

    def test_kit_d_une_spec_prete(self):
        resp = self.lab.get(self.routes[2])
        self.assertEqual(resp.status_code, 200)
        kit = resp.json()
        detail = self.lab.get(self.routes[1]).json()
        self.assertEqual(set(kit), {'spec', 'create', 'seed', 'context'})
        self.assertEqual(kit['spec'], {'id': self.prete['id'], 'name': 'Gestion de stock', 'updated_at': detail['updated_at'],
                                       'fingerprint': detail['fingerprint']})
        # `create` : exactement les champs du POST /projects du moteur.
        self.assertEqual(kit['create'], {'name': 'gestion-stock', 'type': 'django-angular',
                                         'required_groups': ['developers', 'famille']})
        self.assertEqual(set(kit['seed']), {'lots_md', 'cahier_des_charges_md'})
        self.assertEqual(remise.valider_graine(kit['seed']), [])
        self.assertTrue(kit['seed']['lots_md'].startswith('## Lot 2 — '))
        cahier = kit['seed']['cahier_des_charges_md'].split('\n')
        self.assertEqual(cahier[0], '# Cahier des charges — Gestion de stock')
        self.assertIn(f"Spécification App Builder n° {self.prete['id']}, état du {kit['spec']['updated_at']}.", cahier)
        self.assertEqual(kit['context'], detail['context'])
        self.assertEqual(self.lab.get(self.routes[2]).json(), kit)

    def test_empreinte_identique_liste_detail_kit_et_cahier(self):
        pk = self.prete['id']
        liste = next(s for s in self.lab.get(self.routes[0]).json() if s['id'] == pk)
        detail = self.lab.get(self.routes[1]).json()
        kit = self.lab.get(self.routes[2]).json()
        livrables = self.alice.get(f'/api/apps/{pk}/livrables/').json()
        empreinte = liste['fingerprint']
        self.assertRegex(empreinte, r'^sha256:[0-9a-f]{64}$')
        self.assertEqual({detail['fingerprint'], kit['spec']['fingerprint'], livrables['spec']['fingerprint']}, {empreinte})
        lignes = kit['seed']['cahier_des_charges_md'].split('\n')
        self.assertTrue(lignes[2].startswith(f'Spécification App Builder n° {pk}, état du '))
        self.assertEqual(lignes[3], f'Empreinte de la spécification : {empreinte}.')
        self.assertEqual(remise.empreinte(kit['seed']['lots_md'], kit['seed']['cahier_des_charges_md']), empreinte)
        # Seul updated_at change : même empreinte ; un champ change : autre empreinte.
        AppSpec.objects.filter(pk=pk).update(updated_at=AppSpec.objects.get(pk=pk).updated_at.replace(year=2030))
        apres = self.lab.get(self.routes[1]).json()
        self.assertNotEqual(apres['updated_at'], detail['updated_at'])
        self.assertEqual(apres['fingerprint'], empreinte)
        AppSpec.objects.filter(pk=pk).update(description='Une autre description.')
        self.assertNotEqual(self.lab.get(self.routes[1]).json()['fingerprint'], empreinte)

    def test_ni_conversation_ni_cle_dans_aucune_reponse(self):
        with override_settings(ANTHROPIC_API_KEY='cle-serveur-anthropic-SECRETE', MISTRAL_API_KEY='cle-serveur-mistral-SECRETE'):
            for chemin in self.routes:
                with self.subTest(chemin=chemin):
                    texte = self.lab.get(chemin).content.decode()
                    for interdit in ('chat_history', 'CONFIDENTIELLE', 'sk-ant', 'SECRETE', 'api_key', 'owner_email'):
                        self.assertNotIn(interdit, texte)

    def test_la_remise_n_appelle_aucune_ia(self):
        interdit = AssertionError('appel sortant')
        # Points d'appel des fournisseurs (api/ia/fournisseurs.py depuis app-builder-v2).
        with mock.patch('anthropic.Anthropic', side_effect=interdit), \
                mock.patch.object(views.http_requests, 'post', side_effect=interdit), \
                mock.patch.object(fournisseurs.http_requests, 'post', side_effect=interdit), \
                mock.patch.object(fournisseurs, 'appeler_anthropic', side_effect=interdit), \
                mock.patch.object(fournisseurs, 'appeler_mistral', side_effect=interdit):
            for chemin in self.routes:
                self.assertEqual(self.lab.get(chemin).status_code, 200)
