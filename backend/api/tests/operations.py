"""Chantier app-builder-v2 — opérations atomiques (I2) et fonctions I3 de `patching`."""
from api import patching
from api.models import AppSpec, PatchApplication

from .metamodele import spec_v2
from .socle import Base

__all__ = ['OperationsTests', 'OperationsEnregistrementTests']


def up(t, nom='', data=None, **loc):
    o = {'op': 'upsert', 'cible': {'type': t, 'nom': nom, **loc}}
    if data is not None:
        o['data'] = data
    return o


def rm(t, nom, **loc):
    return {'op': 'remove', 'cible': {'type': t, 'nom': nom, **loc}}


def rn(t, nom, nouveau, **loc):
    return {'op': 'rename', 'cible': {'type': t, 'nom': nom, **loc}, 'nouveau_nom': nouveau}


def nomme(elements, nom, cle='name'):
    return next((e for e in elements if e.get(cle) == nom), None)


class _AvecSpec(Base):

    def setUp(self):
        super().setUp()
        self.alice = self.client_de('alice')
        resp = self.alice.post('/api/apps/', spec_v2(), format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.app = AppSpec.objects.get(pk=resp.json()['id'])
        self.spec = patching.spec_de(self.app)

    def essai(self, ops):
        return patching.essayer_operations(self.spec, ops)

    def refus(self, ops):
        with self.assertRaises(patching.PatchRefuse) as r:
            self.essai(ops)
        return r.exception.erreurs


class OperationsTests(_AvecSpec):

    def test_chaque_type_upsert_remove_rename(self):
        # (upsert, contrôle) puis (remove ou rename, contrôle) pour chaque type de cible.
        cas = [
            (up('meta', data={'name': 'Ventes 2', 'app_type': 'django', 'uses_email': False}),
             lambda s: (s['name'], s['app_type'], s['uses_email']) == ('Ventes 2', 'django', False)),
            (up('groupe_requis', 'compta'), lambda s: s['required_groups'] == ['vendeurs', 'compta']),
            (rm('groupe_requis', 'vendeurs'), lambda s: s['required_groups'] == []),
            (up('regle', 'Plafond', {'description': '100 €', 'kind': 'validation'}),
             lambda s: nomme(s['business_rules'], 'Plafond', 'title')['kind'] == 'validation'),
            (rn('regle', 'Stock positif', 'Stock jamais négatif'),
             lambda s: nomme(s['business_rules'], 'Stock jamais négatif', 'title') is not None),
            (rm('regle', 'Stock positif'), lambda s: s['business_rules'] == []),
            (up('role', 'auditeur', {'kind': 'keycloak_group'}), lambda s: nomme(s['roles'], 'auditeur')),
            (rn('role', 'manager', 'chef'), lambda s: nomme(s['roles'], 'chef') and not nomme(s['roles'], 'manager')),
            (rm('role', 'vendeur'), lambda s: not nomme(s['roles'], 'vendeur')),
            (up('job', 'Purge', {'kind': 'command', 'trigger': 'manual'}), lambda s: nomme(s['jobs'], 'Purge')),
            (rn('job', 'Relance', 'Rappel'), lambda s: nomme(s['jobs'], 'Rappel')),
            (rm('job', 'Relance'), lambda s: s['jobs'] == []),
            (up('integration', 'lab_media', {'mode': ''}), lambda s: nomme(s['integrations'], 'lab_media', 'type')),
            (rm('integration', 'email'), lambda s: not nomme(s['integrations'], 'email', 'type')),
            (up('api_externe', 'Brevo', {'auth': 'app_key'}), lambda s: nomme(s['external_apis'], 'Brevo')),
            (rn('api_externe', 'Stripe', 'Stripe EU'), lambda s: nomme(s['external_apis'], 'Stripe EU')),
            (rm('api_externe', 'Stripe'), lambda s: s['external_apis'] == []),
            (up('extension', 'realtime:Suivi', {'transport': 'poll'}),
             lambda s: s['extensions']['realtime'][0]['name'] == 'Suivi'),
            (rn('extension', 'data_io:Import CSV', 'data_io:Import tableur'),
             lambda s: s['extensions']['data_io'][0]['name'] == 'Import tableur'),
            (rm('extension', 'data_io:Import CSV'), lambda s: 'data_io' not in s['extensions']),
            (up('modele', 'Client', {'description': 'acheteur', 'kind': 'entity', 'access': {'scope': 'owner'}}),
             lambda s: nomme(s['data_models'], 'Client')['access'] == {'scope': 'owner'}),
            (rn('modele', 'Produit', 'Article'), lambda s: nomme(s['data_models'], 'Article')),
            (up('champ', 'prix', {'type': 'decimal'}, modele='Produit'),
             lambda s: nomme(nomme(s['data_models'], 'Produit')['fields'], 'prix')['type'] == 'decimal'),
            (rn('champ', 'nom', 'libelle', modele='Produit'),
             lambda s: nomme(nomme(s['data_models'], 'Produit')['fields'], 'libelle')),
            (rm('champ', 'nom', modele='Produit'),
             lambda s: not nomme(nomme(s['data_models'], 'Produit')['fields'], 'nom')),
            (up('relation', 'client', {'rel_type': 'FK', 'to_model': 'Produit'}, modele='Commande'),
             lambda s: nomme(nomme(s['data_models'], 'Commande')['relationships'], 'client')),
            (rn('relation', 'produit', 'article', modele='Commande'),
             lambda s: nomme(nomme(s['data_models'], 'Commande')['relationships'], 'article')),
            (rm('relation', 'produit', modele='Commande'),
             lambda s: nomme(s['data_models'], 'Commande')['relationships'] == []),
            (up('groupe_endpoints', 'Produits', {'description': 'catalogue'}),
             lambda s: nomme(s['endpoint_groups'], 'Produits')['description'] == 'catalogue'),
            (rn('groupe_endpoints', 'Commandes', 'Achats'), lambda s: nomme(s['endpoint_groups'], 'Achats')),
            (up('endpoint', 'GET /api/commandes/', {'operation': 'list', 'linked_model_name': 'Commande'},
                groupe='Commandes'),
             lambda s: len(nomme(s['endpoint_groups'], 'Commandes')['endpoints']) == 3),
            (rm('endpoint', 'POST /api/stripe/webhook/', groupe='Commandes'),
             lambda s: len(nomme(s['endpoint_groups'], 'Commandes')['endpoints']) == 1),
            (up('service', 'StatsService', {'endpoint_group_names': ['Commandes']}),
             lambda s: nomme(s['services'], 'StatsService')['endpoint_group_ids']),
            (rn('service', 'CommandeService', 'AchatService'), lambda s: nomme(s['services'], 'AchatService')),
            (rm('service', 'CommandeService'), lambda s: not nomme(s['services'], 'CommandeService')),
            (up('page', 'Stats', {'route': '/stats', 'layout': 'dashboard', 'required_roles': ['manager']}),
             lambda s: nomme(s['pages'], 'Stats')['required_roles'] == ['manager']),
            (rn('page', 'Vitrine', 'Accueil'), lambda s: nomme(s['pages'], 'Accueil')['public'] is True),
            (rm('page', 'Gestion'), lambda s: not nomme(s['pages'], 'Gestion')),
            (up('interaction', 'Cliquer', {'type': 'click'}, page='Vitrine'),
             lambda s: nomme(nomme(s['pages'], 'Vitrine')['interactions'], 'Cliquer')),
            (up('pipeline', 'Charger', {'steps': [{'label': 'a', 'type': 'poll_job'}]}, page='Vitrine'),
             lambda s: nomme(nomme(s['pages'], 'Vitrine')['pipelines'], 'Charger')['steps'][0]['type'] == 'poll_job'),
            (rm('modele', 'Client'), None),  # inexistant : voir test dédié
        ]
        for op, controle in cas:
            if controle is None:
                continue
            with self.subTest(op=op):
                self.assertTrue(controle(self.essai([op])))

    def test_interaction_et_pipeline_renommes_puis_retires(self):
        base = [up('interaction', 'Cliquer', {'type': 'click'}, page='Vitrine'),
                up('pipeline', 'Charger', {'trigger_interaction': 'Cliquer'}, page='Vitrine')]
        s = self.essai(base + [rn('interaction', 'Cliquer', 'Toucher', page='Vitrine'),
                               rn('pipeline', 'Charger', 'Rafraichir', page='Vitrine')])
        page = nomme(s['pages'], 'Vitrine')
        self.assertEqual(page['pipelines'][0]['name'], 'Rafraichir')
        self.assertEqual(page['pipelines'][0]['trigger_interaction'], 'Toucher')
        s = self.essai(base + [rm('pipeline', 'Charger', page='Vitrine'), rm('interaction', 'Cliquer', page='Vitrine')])
        self.assertEqual((nomme(s['pages'], 'Vitrine')['pipelines'], nomme(s['pages'], 'Vitrine')['interactions']), ([], []))

    def test_ordre_respecte_supprimer_puis_recreer(self):
        s = self.essai([rm('modele', 'Produit'), up('modele', 'Produit', {'description': 'neuf'}),
                        up('champ', 'code', {'type': 'string'}, modele='Produit')])
        produit = nomme(s['data_models'], 'Produit')
        self.assertEqual([f['name'] for f in produit['fields']], ['code'])
        self.assertEqual((produit['description'], produit['access']), ('neuf', {}))

    def test_reference_vers_un_element_cree_plus_tard_acceptee(self):
        s = self.essai([up('endpoint', 'GET /api/clients/', {'linked_model_name': 'Client'}, groupe='Commandes'),
                        up('modele', 'Client')])
        self.assertTrue(nomme(s['data_models'], 'Client'))

    def test_orphelin_final_refuse_sans_prefixe(self):
        erreurs = self.refus([up('endpoint', 'GET /api/clients/', {'linked_model_name': 'Client'}, groupe='Commandes')])
        self.assertEqual(len(erreurs), 1)
        self.assertFalse(erreurs[0].startswith('opération'))
        self.assertIn('« Client »', erreurs[0])

    def test_erreurs_indexees_et_refus_en_bloc(self):
        erreurs = self.refus([
            up('champ', 'x', modele='Produit'),
            rm('modele', 'Fantome'),
            up('champ', 'y', modele='Inconnu'),
            {'op': 'detruire', 'cible': {'type': 'modele', 'nom': 'Produit'}},
            up('truc', 'x'),
            rn('groupe_requis', 'vendeurs', 'autres'),
            rn('modele', 'Produit', 'Commande'),
            up('endpoint', 'pas une route', groupe='Commandes'),
            up('extension', 'sansliste'),
            'pas un objet',
        ])
        self.assertEqual([e.split(' : ')[0] for e in erreurs], [f'opération {i}' for i in range(2, 11)])
        self.assertIn('introuvable', erreurs[0])
        self.assertIn('« Inconnu »', erreurs[1])
        self.assertIn('déjà pris', erreurs[5])

    def test_valeur_refusee_dans_une_operation(self):
        erreurs = self.refus([up('modele', 'Produit', {'kind': 'table'})])
        self.assertTrue(erreurs[0].startswith('opération 1 : '), erreurs)
        erreurs = self.refus([up('meta', data={'app_type': 'spring'})])
        self.assertTrue(erreurs[0].startswith('opération 1 : '), erreurs)

    def test_l_essai_passe_par_le_serialiseur(self):
        erreurs = self.refus([up('page', 'Vitrine', {'layout': 'x' * 30})])
        self.assertTrue(any('layout' in e for e in erreurs), erreurs)

    def test_renommer_propage_les_references(self):
        s = self.essai([rn('modele', 'Commande', 'Achat'), rn('groupe_endpoints', 'Commandes', 'Achats'),
                        rn('role', 'manager', 'chef')])
        point = nomme(s['endpoint_groups'], 'Achats')['endpoints'][0]
        self.assertEqual(point['linked_model_name'], 'Achat')
        self.assertEqual(nomme(s['services'], 'CommandeService')['endpoint_group_ids'],
                         [nomme(s['endpoint_groups'], 'Achats')['id']])
        self.assertEqual(nomme(s['data_models'], 'Produit')['access']['rules'][0]['who'], ['role:chef'])
        self.assertEqual(nomme(s['pages'], 'Gestion')['required_roles'], ['chef'])
        self.assertEqual(s['jobs'][0]['input_model'], 'Achat')

    def test_l_essai_ne_modifie_rien(self):
        avant = patching.version_de(self.app)
        self.essai([rm('modele', 'Produit'), up('modele', 'Produit')])
        self.assertEqual(patching.version_de(AppSpec.objects.get(pk=self.app.pk)), avant)

    def test_resume(self):
        ops = [up('champ', 'prix', {'type': 'decimal'}, modele='Produit'),
               up('champ', 'stock', {'type': 'int'}, modele='Produit'),
               up('page', 'Vitrine', {'components': []})]
        r = patching.resume_operations(self.spec, ops, self.essai(ops))
        self.assertEqual(set(r), {'texte', 'destructive', 'details'})
        self.assertIn('2 champs ajoutés à Produit', r['texte'])
        self.assertFalse(r['destructive'])
        self.assertEqual([d['index'] for d in r['details']], [1, 2, 3])
        # Une liste complète raccourcie est destructive.
        self.essai([up('page', 'Vitrine', {'components': [{'type': 'table'}, {'type': 'map'}]})])
        spec = self.essai([up('page', 'Vitrine', {'components': [{'type': 'table'}, {'type': 'map'}]})])
        ops = [up('page', 'Vitrine', {'components': [{'type': 'map'}]})]
        r = patching.resume_operations(spec, ops, patching.essayer_operations(spec, ops))
        self.assertTrue(r['destructive'])
        self.assertIn('(2 → 1)', r['texte'])
        for op in (rm('role', 'vendeur'), rn('modele', 'Produit', 'Article')):
            self.assertTrue(patching.resume_operations(self.spec, [op], self.essai([op]))['destructive'])

    def test_patch_vers_operations_equivalent(self):
        patch = {'set_meta': {'name': 'Ventes 3', 'required_groups': ['compta'], 'remove_required_groups': ['vendeurs']},
                 'business_rules': [{'title': 'Neuve', 'description': 'x'}],
                 'roles': [{'name': 'auditeur', 'kind': 'keycloak_group'}], 'remove_jobs': ['Relance'],
                 'extensions': {'realtime': [{'name': 'Suivi', 'transport': 'poll'}]},
                 'data_models': [{'name': 'Article', 'rename_from': 'Produit',
                                  'fields': [{'name': 'prix', 'type': 'decimal'}], 'remove_fields': ['categorie']},
                                 {'name': 'Client', 'fields': [{'name': 'nom'}]}],
                 'endpoint_groups': [{'name': 'Commandes', 'remove_endpoints': ['POST /api/stripe/webhook/'],
                                      'endpoints': [{'method': 'GET', 'path': '/api/commandes/', 'operation': 'list'}]}],
                 'services': [{'name': 'ClientService', 'endpoint_group_names': ['Commandes']}],
                 'pages': [{'name': 'Clients', 'route': '/clients', 'service_names': ['ClientService'],
                            'interactions': [{'name': 'Voir', 'type': 'click'}]}],
                 'remove_pages': ['Gestion']}
        ops = patching.patch_vers_operations(patch)
        self.assertTrue(all(o['op'] in ('upsert', 'remove', 'rename') for o in ops))
        par_patch = patching.fusionner(self.spec, patch)
        par_ops = patching.essayer_operations(self.spec, ops)
        self.assertEqual(patching.version_de(par_ops), patching.version_de(par_patch))

    def test_version(self):
        v = patching.version_de(self.app)
        self.assertRegex(v, r'^v:[0-9a-f]{16}$')
        self.assertEqual(patching.version_de(self.spec), v)
        self.app.chat_history = [{'role': 'user', 'content': 'bonjour'}]
        self.app.save()
        self.assertEqual(patching.version_de(AppSpec.objects.get(pk=self.app.pk)), v)
        self.assertNotEqual(patching.version_de(self.essai([up('champ', 'x', modele='Produit')])), v)


class OperationsEnregistrementTests(_AvecSpec):

    def test_appliquer_historique_et_annuler(self):
        v = patching.version_de(self.app)
        ops = [up('modele', 'Client'), up('champ', 'nom', modele='Client')]
        application = patching.appliquer_operations(self.app, ops, v)
        self.assertEqual((application.mode, application.patch), ('ops', {'operations': ops}))
        self.assertIn('Client', application.summary)
        self.assertTrue(self.app.data_models.filter(name='Client').exists())
        self.assertNotEqual(patching.version_de(self.app), v)
        patching.annuler(PatchApplication.objects.get(pk=application.pk))
        self.assertFalse(self.app.data_models.filter(name='Client').exists())
        self.assertEqual(patching.version_de(AppSpec.objects.get(pk=self.app.pk)), v)

    def test_version_perimee(self):
        with self.assertRaises(patching.VersionPerimee):
            patching.appliquer_operations(self.app, [up('modele', 'Client')], 'v:0000000000000000')
        self.assertFalse(self.app.data_models.filter(name='Client').exists())
        self.assertEqual(PatchApplication.objects.count(), 0)
        # Sans version de base : appliqué.
        patching.appliquer_operations(self.app, [up('modele', 'Client')])
        self.assertTrue(self.app.data_models.filter(name='Client').exists())

    def test_refus_en_bloc_rien_n_est_ecrit(self):
        v = patching.version_de(self.app)
        with self.assertRaises(patching.PatchRefuse):
            patching.appliquer_operations(self.app, [up('modele', 'Client'), rm('page', 'Fantome')], v)
        self.assertEqual(patching.version_de(AppSpec.objects.get(pk=self.app.pk)), v)
        self.assertEqual(PatchApplication.objects.count(), 0)

    def test_structures_v2_enregistrees(self):
        patching.appliquer_operations(self.app, [
            up('modele', 'Commande', {'states': {'field': 'statut', 'values': ['brouillon', 'payee', 'annulee'],
                                                 'transitions': [{'from': ['brouillon'], 'to': 'annulee'}]}}),
            up('endpoint', 'POST /api/hook/', {'auth': {'mode': 'internal_key', 'reason': 'lab-media'}}, groupe='Commandes')])
        commande = self.app.data_models.get(name='Commande')
        self.assertEqual(commande.states['values'], ['brouillon', 'payee', 'annulee'])
        point = self.app.endpoint_groups.get(name='Commandes').endpoints.get(path='/api/hook/')
        self.assertEqual((point.auth_required, point.public_reason, point.auth['mode']), (False, 'lab-media', 'internal_key'))
