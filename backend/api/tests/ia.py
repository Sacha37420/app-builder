"""Chantier app-builder-v2, secteur B — couche IA : chat à outils (I4), boucle bornée,
adaptateur Anthropic / Mistral, repli sans outils, vues d'opérations.

Aucun appel réseau : Anthropic est remplacé par un faux client (`FauxClaude`),
Mistral par un faux `requests.post`. Les jetons sont de vrais RS256 (socle.Base).

Doublures I3 : tant qu'une fonction du secteur A (api.patching / api.lecture /
api.conformite) lève encore `NotImplementedError`, `doubler_i3` la remplace par
une doublure de même signature ; dès qu'elle existe, c'est la vraie qui sert.
"""
import copy
import hashlib
import json
from types import SimpleNamespace
from unittest import mock

import requests
from django.test import SimpleTestCase

from api import budget, conformite, lecture, patching
from api.ia import boucle, fournisseurs, outils, prompt
from api.models import AppSpec, PatchApplication

from .socle import Base, _spec_complete

__all__ = ['ChatOutilsClaudeTests', 'ChatOutilsMistralTests', 'ChatGardeFousTests', 'PromptTests',
           'OperationsVuesTests']


# ═══ Doublures des fonctions I3 ═══════════════════════════════════════════════

def _canon(spec: dict) -> str:
    propre = {k: v for k, v in spec.items() if k not in ('id', 'chat_history', 'created_at', 'updated_at')}
    return json.dumps(propre, sort_keys=True, default=str)


def version_de(app_or_spec) -> str:
    spec = patching.spec_de(app_or_spec) if isinstance(app_or_spec, AppSpec) else app_or_spec
    return 'v:' + hashlib.sha256(_canon(spec).encode()).hexdigest()[:16]


def essayer_operations(spec: dict, operations: list) -> dict:
    etat = copy.deepcopy(spec)
    modeles = {m.get('name') for m in etat.get('data_models') or []}
    erreurs = []
    for i, op in enumerate(operations, 1):
        cible = op.get('cible') or {}
        if op.get('op') not in ('upsert', 'remove', 'rename') or not cible.get('type'):
            erreurs.append(f'opération {i} : opération mal formée.')
        elif op['op'] == 'remove' and cible['type'] == 'modele' and cible.get('nom') not in modeles:
            erreurs.append(f"opération {i} : le modèle « {cible.get('nom')} » n'existe pas.")
        elif op['op'] == 'upsert' and cible['type'] == 'modele':
            modeles.add(cible.get('nom'))
            if cible.get('nom') not in {m.get('name') for m in etat.get('data_models') or []}:
                etat.setdefault('data_models', []).append({'name': cible.get('nom'), 'fields': []})
    if erreurs:
        raise patching.PatchRefuse(erreurs)
    return etat


def resume_operations(avant: dict, operations: list, apres: dict) -> dict:
    details = [{'index': i, 'texte': f"{op.get('op')} {(op.get('cible') or {}).get('type')}",
                'destructive': op.get('op') in ('remove', 'rename')} for i, op in enumerate(operations, 1)]
    return {'texte': f'{len(operations)} opération(s)', 'destructive': any(d['destructive'] for d in details),
            'details': details}


def appliquer_operations(app, operations: list, base_version=None):
    if base_version is not None and base_version != version_de(app):
        raise patching.VersionPerimee()
    avant = patching.instantane(app)
    essayer_operations(avant, operations)
    app.description = (app.description or '') + '.'      # la version change
    app.save(update_fields=['description'])
    return PatchApplication.objects.create(app=app, mode='ops', patch={'operations': operations},
                                           summary=f'{len(operations)} opération(s)', snapshot_before=avant)


def index_spec(spec: dict) -> str:
    return f"meta: nom={spec.get('name') or ''} projet={spec.get('project_name') or ''}\n" + \
        'modeles: ' + ' · '.join(m.get('name', '') for m in spec.get('data_models') or [])


def lire_elements(spec: dict, section: str, noms: list) -> dict:
    cles = {'modeles': 'data_models', 'pages': 'pages', 'groupes': 'endpoint_groups', 'services': 'services'}
    elements = [e for e in spec.get(cles.get(section, ''), []) or [] if not noms or e.get('name') in noms]
    trouves = {e.get('name') for e in elements}
    return {'elements': elements, 'inconnus': [n for n in noms if n not in trouves]}


def verifier(spec: dict) -> dict:
    return {'blocages': conformite.blocages(spec), 'avertissements': []}


_DOUBLURES = (
    (patching, 'version_de', version_de, lambda f: f({})),
    (patching, 'essayer_operations', essayer_operations, lambda f: f({}, [])),
    (patching, 'resume_operations', resume_operations, lambda f: f({}, [], {})),
    (patching, 'appliquer_operations', appliquer_operations, lambda f: f(None, [])),
    (lecture, 'index_spec', index_spec, lambda f: f({})),
    (lecture, 'lire_elements', lire_elements, lambda f: f({}, 'meta', [])),
    (conformite, 'verifier', verifier, lambda f: f({})),
)


def _pas_implementee(sonde, fonction) -> bool:
    try:
        sonde(fonction)
    except NotImplementedError:
        return True
    except Exception:  # noqa: BLE001 — implémentée (elle refuse une entrée vide, c'est son droit)
        return False
    return False


def doubler_i3(cas) -> list[str]:
    """Remplace, pour la durée du test `cas`, les fonctions I3 encore absentes.
    Rend les noms doublés (pour le rapport)."""
    doubles = []
    for module, nom, doublure, sonde in _DOUBLURES:
        if _pas_implementee(sonde, getattr(module, nom)):
            p = mock.patch.object(module, nom, doublure)
            p.start()
            cas.addCleanup(p.stop)
            doubles.append(nom)
    return doubles


# ═══ Faux fournisseurs ═════════════════════════════════════════════════════════

def texte(t):
    return SimpleNamespace(type='text', text=t)


def outil(ident, nom, entree):
    return SimpleNamespace(type='tool_use', id=ident, name=nom, input=entree)


def rep_claude(*blocs, stop=None, entree=100, sortie=20, cache=0):
    if stop is None:
        stop = 'tool_use' if any(b.type == 'tool_use' for b in blocs) else 'end_turn'
    return SimpleNamespace(content=list(blocs), stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=entree, output_tokens=sortie,
                                                 cache_read_input_tokens=cache, cache_creation_input_tokens=0))


class FauxClaude:
    """Remplace `anthropic.Anthropic(...)` : rend les réponses dans l'ordre et
    garde une COPIE de chaque requête (la liste de messages grandit pendant le tour)."""

    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.requetes = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self.messages = SimpleNamespace(create=self._interdit)

    def _create(self, **kw):
        self.requetes.append(copy.deepcopy(kw))
        if not self.reponses:
            raise AssertionError('appel de trop')
        r = self.reponses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    @staticmethod
    def _interdit(**kw):
        raise AssertionError('le point non-beta ne doit pas servir')


def rep_mistral(contenu='', appels=(), fin=None):
    message = {'role': 'assistant', 'content': contenu}
    if appels:
        message['tool_calls'] = [{'id': i, 'type': 'function', 'function': {'name': n, 'arguments': a}}
                                 for i, n, a in appels]
    r = mock.Mock()
    r.raise_for_status.return_value = None
    r.json.return_value = {'choices': [{'message': message, 'finish_reason': fin or ('tool_calls' if appels else 'stop')}],
                           'usage': {'prompt_tokens': 50, 'completion_tokens': 10}}
    return r


def erreur_anthropic(classe, statut, message='refus interne cle-de-alice'):
    import anthropic
    import httpx2
    requete = httpx2.Request('POST', 'https://api.anthropic.com/v1/messages')
    if classe is anthropic.APITimeoutError:
        return classe(request=requete)
    return classe(message, response=httpx2.Response(statut, request=requete), body=None)


OP_VALIDE = {'op': 'upsert', 'cible': {'type': 'champ', 'modele': 'Produit', 'nom': 'prix'},
             'data': {'type': 'decimal', 'required': True}}
OP_INVALIDE = {'op': 'remove', 'cible': {'type': 'modele', 'nom': 'Fantome'}}


class _ChatBase(Base):

    def setUp(self):
        super().setUp()
        self.doublees = doubler_i3(self)
        self.alice = self.client_de('alice')
        self.coffre('alice', claude='cle-de-alice', mistral='cle-mistral-de-alice')
        resp = self.alice.post('/api/apps/', _spec_complete(), format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.app_id = resp.json()['id']
        self.corps = {'app_id': self.app_id, 'provider': 'claude', 'model': 'claude-sonnet-5-5',
                      'messages': [{'role': 'user', 'content': 'Une boutique'}]}

    def chat(self, faux=None, client=None, **corps):
        with mock.patch('anthropic.Anthropic', return_value=faux) as ctor:
            resp = (client or self.alice).post('/api/chat/', {**self.corps, **corps}, format='json')
        self.ctor = ctor
        return resp

    def chat_mistral(self, *reponses, **corps):
        with mock.patch.object(fournisseurs.http_requests, 'post', side_effect=list(reponses)) as post:
            resp = self.alice.post('/api/chat/', {**self.corps, 'provider': 'mistral',
                                                  'model': 'mistral-small-latest', **corps}, format='json')
        self.post = post
        return resp


# ═══ Boucle Anthropic ═════════════════════════════════════════════════════════

class ChatOutilsClaudeTests(_ChatBase):

    def test_lecture_puis_reponse_finale(self):
        faux = FauxClaude(
            rep_claude(texte('Je regarde.'), outil('t1', 'lire_elements', {'section': 'modeles', 'noms': ['Produit']})),
            rep_claude(texte('Produit a un champ nom.'), cache=80))
        resp = self.chat(faux)
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()
        self.assertEqual(d['content'], 'Produit a un champ nom.')
        self.assertEqual((d['provider'], d['model']), ('claude', 'claude-sonnet-5-5'))
        self.assertIsNone(d['choices'])
        self.assertIsNone(d['proposal'])
        self.assertFalse(d['truncated'])
        # input_tokens compte TOUTE l'entrée (lectures de cache comprises).
        self.assertEqual(d['usage'], {'calls': 2, 'input_tokens': 280, 'output_tokens': 40, 'cache_read_tokens': 80})
        self.assertEqual(self.ctor.call_args.kwargs['api_key'], 'cle-de-alice')
        premiere, seconde = faux.requetes
        # Bloc stable en cache, index après ; outils triés et non forcés ; repli serveur.
        self.assertEqual(premiere['system'][0], {'type': 'text', 'text': prompt.REGLES,
                                                 'cache_control': {'type': 'ephemeral'}})
        self.assertIn('## Spécification actuelle (index)', premiere['system'][1]['text'])
        self.assertNotIn('cache_control', premiere['system'][1])
        self.assertEqual(premiere['cache_control'], {'type': 'ephemeral'})
        self.assertEqual([t['name'] for t in premiere['tools']], sorted(t['name'] for t in premiere['tools']))
        self.assertEqual({t['name'] for t in premiere['tools']},
                         {'lire_elements', 'proposer_operations', 'proposer_choix', 'verifier_spec'})
        self.assertEqual(premiere['tool_choice'], {'type': 'auto'})
        self.assertEqual(premiere['output_config'], {'effort': 'medium'})
        self.assertNotIn('thinking', premiere)
        self.assertEqual((premiere['fallbacks'], premiere['betas']), ('default', ['server-side-fallback-2026-07-01']))
        self.assertLessEqual(premiere['max_tokens'], 16_000)
        self.assertLessEqual(premiere['timeout'], boucle.HORLOGE_S)
        for t in premiere['tools']:
            if t.get('strict'):
                self.assertNotIn('maxItems', json.dumps(t['input_schema']))
        # Réponse rejouée entière, puis UN message de résultats.
        self.assertEqual(seconde['messages'][0], {'role': 'user', 'content': 'Une boutique'})
        self.assertEqual(seconde['messages'][1]['role'], 'assistant')
        self.assertEqual([b.type for b in seconde['messages'][1]['content']], ['text', 'tool_use'])
        resultat = seconde['messages'][2]
        self.assertEqual(resultat['role'], 'user')
        self.assertEqual(len(resultat['content']), 1)
        self.assertEqual(resultat['content'][0]['type'], 'tool_result')
        self.assertEqual(resultat['content'][0]['tool_use_id'], 't1')
        self.assertNotIn('is_error', resultat['content'][0])
        self.assertIn('Produit', resultat['content'][0]['content'])
        # Même préfixe d'un appel à l'autre (le cache relit le précédent).
        self.assertEqual(premiere['system'], seconde['system'])
        self.assertEqual(premiere['tools'], seconde['tools'])
        # Le contexte rendu compte outils et index.
        self.assertGreater(d['context']['tools_tokens'], 0)
        self.assertGreater(d['context']['index_tokens'], 0)
        self.assertGreater(d['context']['tool_results_tokens'], 0)

    def test_proposer_choix_termine_le_tour(self):
        faux = FauxClaude(rep_claude(texte('Quel type ?'), outil('c1', 'proposer_choix', {
            'question': 'Quel type ?', 'multiple': False, 'options': ['Django + Angular', 'Django seul']})))
        d = self.chat(faux).json()
        self.assertEqual(len(faux.requetes), 1)
        self.assertEqual(d['choices'], {'question': 'Quel type ?', 'multiple': False,
                                        'items': ['Django + Angular', 'Django seul']})
        self.assertEqual(d['content'], 'Quel type ?')
        # Choix mal formé : erreur rendue au modèle, pas de choix.
        faux = FauxClaude(rep_claude(outil('c1', 'proposer_choix', {'question': 'Q', 'multiple': False, 'options': ['A']})),
                          rep_claude(texte('Question ouverte : lequel ?')))
        d = self.chat(faux).json()
        self.assertIsNone(d['choices'])
        self.assertTrue(faux.requetes[1]['messages'][-1]['content'][0]['is_error'])

    def test_operations_refusees_puis_corrigees(self):
        faux = FauxClaude(
            rep_claude(outil('o1', 'proposer_operations', {'operations': [OP_INVALIDE]})),
            rep_claude(outil('o2', 'proposer_operations', {'operations': [OP_VALIDE]})),
            rep_claude(texte("J'ajoute le prix au produit.")))
        d = self.chat(faux).json()
        self.assertEqual(len(faux.requetes), 3)
        refus = faux.requetes[1]['messages'][-1]['content'][0]
        self.assertTrue(refus['is_error'])
        self.assertIn('opération 1', refus['content'])
        self.assertNotIn('is_error', faux.requetes[2]['messages'][-1]['content'][0])
        prop = d['proposal']
        self.assertEqual(prop['operations'], [OP_VALIDE])
        self.assertEqual(prop['erreurs'], [])
        self.assertEqual(prop['base_version'], self.alice.get(f'/api/apps/{self.app_id}/').json()['version'])
        self.assertIn('texte', prop['resume'])
        self.assertIn('destructive', prop['resume'])
        self.assertEqual(d['content'], "J'ajoute le prix au produit.")
        # Rien n'est écrit en base par le chat.
        self.assertFalse(PatchApplication.objects.filter(app_id=self.app_id).exists())

    def test_les_propositions_du_tour_s_accumulent(self):
        autre = {'op': 'upsert', 'cible': {'type': 'modele', 'nom': 'Categorie'}, 'data': {'description': 'Rayon'}}
        faux = FauxClaude(
            rep_claude(outil('o1', 'proposer_operations', {'operations': [OP_VALIDE]})),
            rep_claude(outil('o2', 'proposer_operations', {'operations': [autre]})),
            rep_claude(texte('')))
        d = self.chat(faux).json()
        self.assertEqual(d['proposal']['operations'], [OP_VALIDE, autre])
        self.assertTrue(d['content'].startswith('Je propose'))

    def test_trois_echecs_de_suite_arretent_le_tour(self):
        faux = FauxClaude(*[rep_claude(outil(f'o{i}', 'proposer_operations', {'operations': [OP_INVALIDE]}))
                            for i in range(5)])
        d = self.chat(faux).json()
        self.assertEqual(len(faux.requetes), boucle.MAX_ECHECS)
        self.assertIn('refusées 3 fois', d['content'])
        self.assertEqual(d['proposal']['operations'], [])
        self.assertTrue(d['proposal']['erreurs'])

    def test_au_plus_six_appels_par_tour(self):
        faux = FauxClaude(*[rep_claude(outil(f'l{i}', 'lire_elements', {'section': 'modeles', 'noms': []}))
                            for i in range(10)])
        d = self.chat(faux).json()
        self.assertEqual(len(faux.requetes), boucle.MAX_APPELS)
        self.assertEqual(d['usage']['calls'], 6)
        self.assertIn("limite d'étapes", d['content'])

    def test_horloge_du_tour(self):
        faux = FauxClaude(*[rep_claude(outil(f'l{i}', 'lire_elements', {'section': 'modeles', 'noms': []}))
                            for i in range(3)])
        temps = iter([0.0, 0.0, 85.0, 85.0, 85.0])
        with mock.patch.object(boucle.time, 'monotonic', side_effect=lambda: next(temps, 85.0)):
            d = self.chat(faux).json()
        self.assertEqual(len(faux.requetes), 1)
        self.assertIn('trop de temps', d['content'])

    def test_reponse_tronquee_signalee(self):
        faux = FauxClaude(rep_claude(texte('Voici le début'), stop='max_tokens'))
        d = self.chat(faux).json()
        self.assertTrue(d['truncated'])
        self.assertIn('Réponse coupée', d['content'])
        # Un tool_use coupé n'est pas exécuté.
        faux = FauxClaude(rep_claude(outil('o1', 'proposer_operations', {'operations': [OP_VALIDE]}), stop='max_tokens'))
        d = self.chat(faux).json()
        self.assertEqual(len(faux.requetes), 1)
        self.assertIsNone(d['proposal'])

    def test_refus_du_modele(self):
        faux = FauxClaude(rep_claude(stop='refusal'))
        resp = self.chat(faux)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('refusé', resp.json()['content'])

    def test_arguments_illisibles_et_outil_inconnu_rendus_en_erreur(self):
        faux = FauxClaude(rep_claude(outil('x1', 'outil_pirate', {}), outil('x2', 'lire_elements', 'pas un objet')),
                          rep_claude(texte('Pardon.')))
        d = self.chat(faux).json()
        resultats = faux.requetes[1]['messages'][-1]['content']
        self.assertEqual([r['tool_use_id'] for r in resultats], ['x1', 'x2'])
        self.assertTrue(all(r['is_error'] for r in resultats))
        self.assertEqual(d['content'], 'Pardon.')

    def test_modeles_precedents_reflexion_explicite_sans_strict(self):
        faux = FauxClaude(rep_claude(texte('ok')))
        self.chat(faux, model='claude-sonnet-4-6')
        r = faux.requetes[0]
        self.assertEqual(r['thinking'], {'type': 'adaptive'})
        self.assertNotIn('fallbacks', r)
        self.assertFalse(any(t.get('strict') for t in r['tools']))
        faux = FauxClaude(rep_claude(texte('ok')))
        self.chat(faux, model='claude-haiku-4-5')
        self.assertNotIn('output_config', faux.requetes[0])


# ═══ Boucle Mistral ═══════════════════════════════════════════════════════════

class ChatOutilsMistralTests(_ChatBase):

    def test_appels_d_outils_et_arguments_chaine_json(self):
        resp = self.chat_mistral(
            rep_mistral('', [('a1', 'lire_elements', json.dumps({'section': 'modeles', 'noms': ['Produit']})),
                             ('a2', 'proposer_operations', '{pas du json')]),
            rep_mistral('', [('a3', 'proposer_operations', json.dumps({'operations': [OP_VALIDE]}))]),
            rep_mistral('Le prix est proposé.'))
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()
        self.assertEqual(d['content'], 'Le prix est proposé.')
        self.assertEqual(d['proposal']['operations'], [OP_VALIDE])
        self.assertEqual(d['usage']['calls'], 3)
        appels = self.post.call_args_list
        self.assertEqual(appels[0].args[0], 'https://api.mistral.ai/v1/chat/completions')
        self.assertEqual(appels[0].kwargs['headers']['Authorization'], 'Bearer cle-mistral-de-alice')
        p1 = appels[0].kwargs['json']
        self.assertEqual(p1['tool_choice'], 'auto')
        self.assertEqual(p1['tools'][0]['type'], 'function')
        self.assertIn('parameters', p1['tools'][0]['function'])
        self.assertEqual(p1['messages'][0]['role'], 'system')
        self.assertTrue(p1['messages'][0]['content'].startswith(prompt.REGLES))
        p2 = appels[1].kwargs['json']['messages']
        self.assertEqual(p2[-3]['role'], 'assistant')
        self.assertEqual(len(p2[-3]['tool_calls']), 2)
        self.assertEqual([(m['role'], m['tool_call_id'], m['name']) for m in p2[-2:]],
                         [('tool', 'a1', 'lire_elements'), ('tool', 'a2', 'proposer_operations')])
        self.assertIn('illisibles', p2[-1]['content'])

    def test_troncature_mistral(self):
        d = self.chat_mistral(rep_mistral('Début', fin='length')).json()
        self.assertTrue(d['truncated'])

    def test_repli_sans_outils_sortie_structuree(self):
        # Modèle inconnu de la table : pas d'outils, une sortie JSON.
        reponse = json.dumps({'reponse': 'Je propose le prix.', 'operations': [OP_VALIDE],
                              'choix': {'question': 'Devise ?', 'multiple': False, 'options': ['EUR', 'USD']}})
        resp = self.chat_mistral(rep_mistral(reponse), model='mistral-inconnu-latest')
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()
        payload = self.post.call_args.kwargs['json']
        self.assertNotIn('tools', payload)
        self.assertEqual(payload['response_format'], {'type': 'json_object'})
        self.assertIn('Format de ta réponse', payload['messages'][0]['content'])
        self.assertEqual(d['content'], 'Je propose le prix.')
        self.assertEqual(d['proposal']['operations'], [OP_VALIDE])
        self.assertEqual(d['choices']['items'], ['EUR', 'USD'])
        # Opérations refusées : une seule correction.
        mauvaise = json.dumps({'reponse': 'x', 'operations': [OP_INVALIDE]})
        bonne = json.dumps({'reponse': 'Corrigé.', 'operations': [OP_VALIDE]})
        d = self.chat_mistral(rep_mistral(mauvaise), rep_mistral(bonne), model='mistral-inconnu-latest').json()
        self.assertEqual(self.post.call_count, 2)
        self.assertEqual(d['content'], 'Corrigé.')
        self.assertIn('Opérations refusées', self.post.call_args.kwargs['json']['messages'][-1]['content'])


# ═══ Garde-fous de la vue ═════════════════════════════════════════════════════

class ChatGardeFousTests(_ChatBase):

    def test_spec_d_autrui_ou_absente_404_sans_appel(self):
        faux = FauxClaude()
        bob = self.client_de('bob')
        self.coffre('bob', claude='cle-de-bob')
        self.assertEqual(self.chat(faux, client=bob).status_code, 404)
        self.assertEqual(self.chat(faux, app_id=None).status_code, 404)
        self.assertEqual(self.chat(faux, app_id='x').status_code, 404)
        self.assertEqual(self.chat(faux, app_id=999999).status_code, 404)
        self.assertEqual(faux.requetes, [])
        self.assertEqual(self.alice.post('/api/chat/estimate/', {**self.corps, 'app_id': 999999},
                                         format='json').status_code, 404)

    def test_app_spec_du_corps_ignoree(self):
        faux = FauxClaude(rep_claude(texte('ok')))
        self.chat(faux, app_spec={'name': 'PIRATE-SPEC', 'data_models': [{'name': 'Pirate'}]})
        envoye = json.dumps(faux.requetes, default=str)
        self.assertNotIn('PIRATE', envoye)
        self.assertNotIn('Pirate', envoye)

    def test_historique_en_texte_seulement(self):
        messages = [{'role': 'user', 'content': 'a', 'proposal': {'operations': [OP_VALIDE]}},
                    {'role': 'assistant', 'content': 'b', 'tool_use': {'id': 'x'}},
                    {'role': 'user', 'content': 'c'}]
        faux = FauxClaude(rep_claude(texte('ok')))
        self.chat(faux, messages=messages)
        self.assertEqual(faux.requetes[0]['messages'],
                         [{'role': 'user', 'content': 'a'}, {'role': 'assistant', 'content': 'b'},
                          {'role': 'user', 'content': 'c'}])

    def test_sans_cle_ou_sans_message(self):
        faux = FauxClaude()
        bob = self.client_de('bob')
        spec_bob = bob.post('/api/apps/', {'name': 'B'}, format='json').json()['id']
        resp = self.chat(faux, client=bob, app_id=spec_bob, api_key='cle-du-corps')
        self.assertEqual((resp.status_code, resp.json()['code']), (400, 'key_not_configured'))
        self.assertEqual(self.chat(faux, messages=[]).status_code, 400)
        self.assertEqual(faux.requetes, [])

    def test_413_avant_tout_appel(self):
        with mock.patch.object(fournisseurs.http_requests, 'post') as post:
            resp = self.alice.post('/api/chat/', {**self.corps, 'provider': 'mistral', 'model': 'mistral-small-latest',
                                                  'messages': [{'role': 'user', 'content': 'x' * 200_000}]},
                                   format='json')
            post.assert_not_called()
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(resp.json()['code'], 'context_too_large')
        self.assertFalse(resp.json()['context']['fits'])

    def test_pannes_du_fournisseur(self):
        import anthropic
        cas = [(anthropic.AuthenticationError, 401, 502, 'refusée'),
               (anthropic.RateLimitError, 429, 502, 'Quota'),
               (anthropic.InternalServerError, 500, 502, 'a échoué'),
               (anthropic.APITimeoutError, None, 504, 'à temps')]
        for classe, statut, attendu, mot in cas:
            with self.subTest(classe=classe.__name__):
                resp = self.chat(FauxClaude(erreur_anthropic(classe, statut)))
                self.assertEqual(resp.status_code, attendu)
                self.assertIn(mot, resp.json()['error'])
                self.assertNotIn('cle-de-alice', resp.content.decode())
                self.assertNotIn('refus interne', resp.content.decode())
        trop = erreur_anthropic(anthropic.BadRequestError, 400, 'prompt is too long: 1200000 tokens > 1000000 maximum')
        self.assertEqual(self.chat(FauxClaude(trop)).status_code, 413)
        resp = self.chat_mistral(requests.exceptions.ConnectTimeout())
        self.assertEqual(resp.status_code, 504)
        http = requests.exceptions.HTTPError('401')
        http.response = mock.Mock(status_code=401, text='unauthorized cle-mistral-de-alice')
        resp = self.chat_mistral(http)
        self.assertEqual(resp.status_code, 502)
        self.assertNotIn('cle-mistral', resp.content.decode())
        # Une panne APRÈS un premier appel réussi termine le tour proprement.
        faux = FauxClaude(rep_claude(outil('o1', 'proposer_operations', {'operations': [OP_VALIDE]})),
                          erreur_anthropic(anthropic.InternalServerError, 500))
        resp = self.chat(faux)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['proposal']['operations'], [OP_VALIDE])

    def test_le_journal_ne_porte_aucun_contenu(self):
        faux = FauxClaude(rep_claude(texte('REPONSE-SECRETE'), outil('o1', 'proposer_operations', {'operations': [OP_VALIDE]})),
                          rep_claude(texte('REPONSE-SECRETE-2')))
        with self.assertLogs('api', 'INFO') as journal:
            self.chat(faux, messages=[{'role': 'user', 'content': 'QUESTION-SECRETE'}])
        texte_journal = '\n'.join(journal.output)
        for interdit in ('QUESTION-SECRETE', 'REPONSE-SECRETE', 'cle-de-alice', 'Boutique', 'prix'):
            self.assertNotIn(interdit, texte_journal)
        self.assertIn('proposer_operations', texte_journal)


# ═══ Prompt et vues d'opérations ══════════════════════════════════════════════

class PromptTests(SimpleTestCase):

    def test_une_seule_source_pour_le_bloc_stable(self):
        from api import mcp
        self.assertTrue(mcp.INSTRUCTIONS.startswith(prompt.REGLES))
        for attendu in ('storage_file', 'project_name', 'Foyer', 'Keycloak', 'proposer_operations', 'lire_elements',
                        'verifier_spec', 'proposer_choix', 'access', 'states', 'job',
                        'integration', 'secret', 'enum', 'kanban', 'map', 'raison'):
            self.assertIn(attendu, prompt.REGLES)
        for interdit in ('PATCH_READY', 'CHOICES_START', 'Spring', 'json/file', 'azp', 'admin-cli'):
            self.assertNotIn(interdit, prompt.REGLES)
        # Aucun élément variable dans le bloc stable (sinon le cache ne sert jamais).
        self.assertNotRegex(prompt.REGLES, r'20\d\d-\d\d-\d\d')

    def test_outils_figes(self):
        self.assertEqual(outils.pour_anthropic(), outils.pour_anthropic())
        self.assertEqual(json.dumps(outils.pour_mistral(), sort_keys=True), json.dumps(outils.pour_mistral(), sort_keys=True))
        self.assertEqual(set(outils.SECTIONS), set(__import__('api.lecture', fromlist=['SECTIONS']).SECTIONS))

    def test_table_des_modeles(self):
        for m in budget.MODELES:
            self.assertIn('tools', m)
            self.assertLess(budget.sortie(m), 21_000)        # non streamé
        self.assertTrue(budget.modele('claude', 'claude-opus-5-5')['tools'])
        self.assertFalse(budget.modele('mistral', 'mistral-inconnu')['tools'])
        self.assertEqual(budget.MODELE_PAR_DEFAUT['claude'], 'claude-sonnet-5-5')


class OperationsVuesTests(_ChatBase):

    def url(self, suffixe=''):
        return f'/api/apps/{self.app_id}/operations/{suffixe}'

    def test_version_dans_le_detail(self):
        v = self.alice.get(f'/api/apps/{self.app_id}/').json()['version']
        self.assertRegex(v, r'^v:[0-9a-f]{16}$')

    def test_essai_puis_application_puis_version_perimee(self):
        v = self.alice.get(f'/api/apps/{self.app_id}/').json()['version']
        essai = self.alice.post(self.url('essai/'), {'operations': [OP_VALIDE]}, format='json')
        self.assertEqual(essai.status_code, 200)
        self.assertTrue(essai.json()['ok'])
        self.assertIn('texte', essai.json()['resume'])
        refus = self.alice.post(self.url('essai/'), {'operations': [OP_INVALIDE]}, format='json').json()
        self.assertFalse(refus['ok'])
        self.assertTrue(refus['erreurs'][0].startswith('opération 1 : '))
        self.assertFalse(PatchApplication.objects.filter(app_id=self.app_id).exists())

        resp = self.alice.post(self.url(), {'operations': [OP_VALIDE], 'base_version': v}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()
        self.assertEqual(set(d), {'application', 'version', 'spec'})
        self.assertEqual(d['application']['mode'], 'ops')
        self.assertNotEqual(d['version'], v)
        # Même base : la spec a changé ⇒ 409 avec la version actuelle.
        resp = self.alice.post(self.url(), {'operations': [OP_VALIDE], 'base_version': v}, format='json')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['code'], 'version_perimee')
        self.assertEqual(resp.json()['version'], d['version'])
        resp = self.alice.post(self.url(), {'operations': [OP_INVALIDE], 'base_version': d['version']}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(resp.json()['erreurs'])

    def test_corps_refuses_et_spec_d_autrui(self):
        for corps in ({}, {'operations': []}, {'operations': 'x'}, {'operations': [1]}):
            self.assertEqual(self.alice.post(self.url(), corps, format='json').status_code, 400)
            self.assertFalse(self.alice.post(self.url('essai/'), corps, format='json').json()['ok'])
        bob = self.client_de('bob')
        self.assertEqual(bob.post(self.url(), {'operations': [OP_VALIDE]}, format='json').status_code, 404)
        self.assertEqual(bob.post(self.url('essai/'), {'operations': [OP_VALIDE]}, format='json').status_code, 404)
        self.assertEqual(self.client_de('alice', azp='lab-admin').post(
            self.url('essai/'), {'operations': [OP_VALIDE]}, format='json').status_code, 403)

    def test_chat_history_doit_etre_une_liste(self):
        url = f'/api/apps/{self.app_id}/chat/'
        for valeur in ('texte', {'a': 1}, 3):
            self.assertEqual(self.alice.patch(url, {'chat_history': valeur}, format='json').status_code, 400)
        self.assertEqual(self.alice.patch(url, {'chat_history': [{'role': 'user', 'content': 'x'}]},
                                          format='json').status_code, 200)
