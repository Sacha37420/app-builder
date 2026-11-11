"""Chantier app-builder-v2 — lecture compacte de la spec pour l'IA et le MCP (I3, `api/lecture.py`)."""
import json

from django.test import SimpleTestCase

from api import lecture
from api.budget import estimer_jetons

from .metamodele import spec_v2

__all__ = ['LectureTests']


def _grosse_spec(n=30) -> dict:
    modeles, groupes, pages = [], [], []
    for i in range(n):
        modeles.append({'id': i + 1, 'name': f'Modele{i}', 'order': i,
                        'description': 'Une description assez longue pour peser dans le JSON complet. ' * 3,
                        'fields': [{'name': f'champ{j}', 'type': 'string', 'required': True, 'unique': False,
                                    'max_length': 200, 'help_text': 'aide détaillée du champ'} for j in range(6)],
                        'relationships': [{'name': 'parent', 'rel_type': 'FK', 'to_model': f'Modele{max(i - 1, 0)}',
                                           'related_name': 'enfants', 'on_delete': 'CASCADE'}],
                        'access': {'scope': 'owner', 'owner_field': 'owner_email'}, 'states': {}, 'constraints': []})
        groupes.append({'id': 100 + i, 'name': f'Groupe{i}', 'order': i, 'description': 'groupe',
                        'endpoints': [{'id': 1000 + i * 10 + k, 'method': m, 'path': f'/api/m{i}/' + ('{id}/' if k > 1 else ''),
                                       'description': 'route documentée', 'operation': 'custom', 'linked_model_name': f'Modele{i}',
                                       'auth_required': True, 'required_roles': [], 'query_params': [],
                                       'steps': [{'label': 'lire', 'type': 'db_query', 'description': 'lecture en base'}]}
                                      for k, m in enumerate(('GET', 'POST', 'GET', 'PATCH', 'DELETE'))]})
        pages.append({'id': 200 + i, 'name': f'Page{i}', 'route': f'/p{i}', 'layout': 'list', 'order': i,
                      'service_ids': [], 'components': [{'type': 'table', 'linked_model': f'Modele{i}',
                                                         'fields': [f'champ{j}' for j in range(6)], 'config': {'pagination': 20}}],
                      'interactions': [{'name': 'Clic', 'type': 'click', 'description': 'ouvre'}],
                      'pipelines': [{'name': 'Charger', 'trigger_interaction': 'Clic',
                                     'steps': [{'label': 'appel', 'type': 'service_call', 'description': 'charge'}] * 4}]})
    return {'name': 'Grosse', 'project_name': 'grosse', 'app_type': 'django-angular', 'required_groups': ['g'],
            'data_models': modeles, 'endpoint_groups': groupes, 'services': [], 'pages': pages}


class LectureTests(SimpleTestCase):

    def test_index_deterministe_une_ligne_par_section(self):
        texte = lecture.index_spec(spec_v2())
        self.assertEqual(texte, lecture.index_spec(spec_v2()))
        self.assertEqual([ligne.split(':')[0] for ligne in texte.split('\n')], list(lecture.SECTIONS))
        self.assertIn('Produit(nom:string!,categorie:enum!) <reference> [group]', texte)
        self.assertIn('{statut: brouillon|payee}', texte)
        self.assertIn('Commandes[POST /api/commandes/ · POST /api/stripe/webhook/]', texte)
        self.assertIn('storage(user_token)', texte)
        self.assertIn('data_io[Import CSV]', texte)
        self.assertNotIn('"id"', texte)

    def test_index_independant_de_l_ordre_recu_et_des_ids(self):
        a, b = spec_v2(), spec_v2()
        b['data_models'].reverse()
        for i, m in enumerate(b['data_models']):
            m['id'] = 900 + i
        self.assertEqual(lecture.index_spec(a), lecture.index_spec(b))

    def test_index_compact_sur_30_modeles(self):
        spec = _grosse_spec(30)
        index = estimer_jetons(lecture.index_spec(spec))
        complet = estimer_jetons(json.dumps(spec, ensure_ascii=False))
        self.assertLess(index * 5, complet, (index, complet))
        # Environ 40 jetons au plus par élément de premier niveau (30 modèles, 30 groupes, 30 pages).
        self.assertLess(index, 40 * 90 + 200)

    def test_index_d_une_spec_vide(self):
        texte = lecture.index_spec({})
        self.assertIn('modeles: aucun', texte)
        self.assertIn('pages: aucun', texte)

    def test_lire_elements_sans_ids_ni_vides(self):
        r = lecture.lire_elements(spec_v2(), 'modeles', ['Commande', 'Fantome'])
        self.assertEqual(r['inconnus'], ['Fantome'])
        self.assertEqual([m['name'] for m in r['elements']], ['Commande'])
        texte = json.dumps(r)
        self.assertNotIn('"id"', texte)
        for vide in ('""', '[]', '{}', 'null'):
            self.assertNotIn(vide, texte)
        services = lecture.lire_elements(spec_v2(), 'services', [])['elements']
        self.assertEqual(services, [{'name': 'CommandeService', 'endpoint_group_names': ['Commandes']}])

    def test_chaque_section_se_lit(self):
        attendu = {'meta': 1, 'regles': 1, 'roles': 2, 'jobs': 1, 'integrations': 2, 'api_externes': 1,
                   'extensions': 2, 'modeles': 2, 'groupes': 1, 'services': 1, 'pages': 2}
        for section, n in attendu.items():
            with self.subTest(section):
                self.assertEqual(len(lecture.lire_elements(spec_v2(), section, [])['elements']), n)
        ext = lecture.lire_elements(spec_v2(), 'extensions', ['data_io:Import CSV'])
        self.assertEqual(ext['elements'][0]['liste'], 'data_io')
        self.assertEqual(lecture.lire_elements(spec_v2(), 'integrations', ['email'])['elements'], [{'type': 'email'}])
        self.assertEqual(lecture.lire_elements(spec_v2(), 'regles', ['Stock positif'])['elements'][0]['kind'], 'invariant')

    def test_trop_gros_refuse(self):
        r = lecture.lire_elements(_grosse_spec(30), 'groupes', [])
        self.assertEqual(r['erreur'], 'trop_gros')
        self.assertIn('moins', r['message'])
        petit = lecture.lire_elements(_grosse_spec(30), 'groupes', ['Groupe3'])
        self.assertEqual(len(petit['elements']), 1)

    def test_section_inconnue(self):
        self.assertEqual(lecture.lire_elements(spec_v2(), 'tables', [])['erreur'], 'section_inconnue')
