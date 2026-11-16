"""Validité métier (relecture « metier-ux » du 2026-11-17) : enregistrement
tout ou rien de la spécification, corps de requête mal formé."""
from unittest import mock

from django.db import DatabaseError

from api.models import AppSpec, EndpointGroup
from .socle import Base, _spec_complete

__all__ = ['EnregistrementAtomiqueTests', 'PatchPartielLiensTests', 'CorpsMalFormeTests']


class EnregistrementAtomiqueTests(Base):
    """PUT /api/apps/<id>/ efface puis recrée chaque liste : une panne en cours
    de route ne doit rien laisser à moitié fait."""

    def setUp(self):
        super().setUp()
        self.alice = self.client_de('alice')
        self.spec = self.alice.post('/api/apps/', _spec_complete(), format='json').json()

    def comptes(self):
        app = AppSpec.objects.get(pk=self.spec['id'])
        return (app.name, app.data_models.count(), app.endpoint_groups.count(),
                app.services.count(), app.pages.count())

    def test_une_panne_pendant_l_enregistrement_ne_perd_rien(self):
        avant = self.comptes()
        self.assertEqual(avant, ('Boutique', 1, 2, 2, 1))
        envoi = {**self.spec, 'name': 'Boutique v2'}
        with mock.patch('api.serializers.Page.objects.create', side_effect=DatabaseError('panne simulée')):
            with self.assertRaises(DatabaseError):
                self.alice.put(f"/api/apps/{self.spec['id']}/", envoi, format='json')
        self.assertEqual(self.comptes(), avant)

    def test_une_panne_a_la_creation_ne_laisse_pas_de_spec_amputee(self):
        with mock.patch('api.serializers.Page.objects.create', side_effect=DatabaseError('panne simulée')):
            with self.assertRaises(DatabaseError):
                self.alice.post('/api/apps/', {**_spec_complete(), 'name': 'Autre'}, format='json')
        self.assertFalse(AppSpec.objects.filter(name='Autre').exists())


class PatchPartielLiensTests(Base):
    """PATCH /api/apps/<id>/ d'une seule liste : les éléments des listes non
    envoyées restent, avec leurs liens vers les éléments recréés."""

    def setUp(self):
        super().setUp()
        self.alice = self.client_de('alice')
        self.spec = self.alice.post('/api/apps/', _spec_complete(), format='json').json()
        self.url = f"/api/apps/{self.spec['id']}/"

    def liens(self, spec):
        groupes = {g['id']: g['name'] for g in spec['endpoint_groups']}
        services = {s['id']: s['name'] for s in spec['services']}
        return ({s['name']: sorted(groupes[i] for i in s['endpoint_group_ids']) for s in spec['services']},
                {p['name']: sorted(services[i] for i in p['service_ids']) for p in spec['pages']})

    def test_patch_des_seuls_groupes_garde_les_liens_des_services(self):
        avant = self.liens(self.spec)
        resp = self.alice.patch(self.url, {'endpoint_groups': self.spec['endpoint_groups']}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self.liens(resp.json()), avant)

    def test_patch_des_seuls_services_garde_les_liens_des_pages(self):
        avant = self.liens(self.spec)
        resp = self.alice.patch(self.url, {'services': self.spec['services']}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self.liens(resp.json()), avant)

    def test_un_groupe_retire_par_le_patch_n_est_plus_lie(self):
        groupes = [g for g in self.spec['endpoint_groups'] if g['name'] == 'Produits']
        resp = self.alice.patch(self.url, {'endpoint_groups': groupes}, format='json')
        services, _ = self.liens(resp.json())
        self.assertEqual(services, {'ProduitService': ['Produits'], 'ToutService': ['Produits']})

    def test_le_groupe_d_un_autre_n_est_jamais_lie(self):
        autre = AppSpec.objects.create(name='Bob', owner_email='bob@ssolab.local')
        groupe_bob = EndpointGroup.objects.create(app=autre, name='Secret')
        services = [{**s, 'endpoint_group_ids': [groupe_bob.pk]} for s in self.spec['services']]
        resp = self.alice.patch(self.url, {'services': services}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(all(s['endpoint_group_ids'] == [] for s in resp.json()['services']))
        self.assertEqual(groupe_bob.services.count(), 0)


class CorpsMalFormeTests(Base):

    def test_patch_dont_le_corps_n_est_pas_un_objet_est_refuse(self):
        alice = self.client_de('alice')
        spec = alice.post('/api/apps/', _spec_complete(), format='json').json()
        resp = alice.post(f"/api/apps/{spec['id']}/patch/", [1, 2], format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(AppSpec.objects.get(pk=spec['id']).data_models.count(), 1)
