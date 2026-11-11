"""Repli pour un modèle sans outils (`tools: false` dans budget.MODELES).

Un appel en sortie structurée — objet `{reponse, choix?, operations?}` —, l'index
en prompt et le détail de la spec SEULEMENT s'il tient ; validation et essai à
blanc identiques à la boucle d'outils ; une seule correction autorisée.
"""
import json
import re

from .. import budget, lecture, patching
from . import outils as outils_mod

SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['reponse'],
    'properties': {
        'reponse': {'type': 'string'},
        'choix': {'type': 'object', 'additionalProperties': False, 'required': ['question', 'options', 'multiple'],
                  'properties': {'question': {'type': 'string'}, 'multiple': {'type': 'boolean'},
                                 'options': {'type': 'array', 'items': {'type': 'string'}}}},
        'operations': {'type': 'array', 'items': outils_mod.SCHEMA_OPERATION},
    },
}

CONSIGNE = """## Format de ta réponse (ce modèle n'a pas d'outils)
Réponds par UN objet JSON, rien d'autre : {"reponse": "texte affiché à l'utilisateur",
"choix": {"question": "…", "multiple": false, "options": ["A", "B"]} (facultatif : une question fermée),
"operations": [ … ] (facultatif : les opérations proposées, même forme que proposer_operations)}.
Sans outil de lecture, appuie-toi sur le détail de la spécification ci-dessous."""


def detail_spec(spec: dict, place: int) -> str:
    """Le détail de toutes les sections (api.lecture.lire_elements), s'il tient dans `place` jetons."""
    morceaux = []
    for section in outils_mod.SECTIONS:
        r = lecture.lire_elements(spec, section, [])
        if not isinstance(r, dict) or r.get('erreur'):
            return ''
        if r.get('elements'):
            morceaux.append(f'### {section}\n' + outils_mod.compact(r['elements']))
    texte = '\n'.join(morceaux)
    return texte if budget.estimer_jetons(texte) <= place else ''


def _objet(texte: str):
    t = (texte or '').strip()
    t = re.sub(r'^```[a-zA-Z0-9]*\s*', '', t)
    t = re.sub(r'\s*```$', '', t)
    try:
        o = json.loads(t)
    except ValueError:
        return None
    return o if isinstance(o, dict) else None


def tour(t) -> None:
    """Joue le repli sur l'objet `_Tour` (api/ia/boucle.py)."""
    disponible = t.fiche['context_window'] - budget.sortie(t.fiche) - budget.MARGE_JETONS
    place = disponible // 3
    detail = detail_spec(t.spec, place)
    t.variable += '\n\n' + CONSIGNE + (
        '\n\n## Détail de la spécification\n' + detail if detail
        else "\n\n(Le détail de la spécification est trop gros pour ce modèle : l'index seul est fourni.)")
    # Mistral : `response_format: json_object`. Claude : seul un modèle INCONNU de la table arrive
    # ici (tous ceux de la table ont des outils) — rien ne dit qu'il prend `output_config.format` :
    # la consigne du prompt suffit, la réponse est validée de toute façon.
    from .boucle import anthropique
    format_json = None if anthropique(t.fiche) else {}
    conv = list(t.conv)
    for essai in (1, 2):
        r = t.appeler(conv, format_json=format_json)
        if r.arret == 'refus':
            from .boucle import _REFUS
            t.avis = _REFUS
            return
        if r.arret == 'tronque':
            t.tronque = True
            return
        objet = _objet(r.texte)
        if objet is None or not isinstance(objet.get('reponse'), str):
            if essai == 2:
                t.textes.append(r.texte)
                return
            conv = conv + [{'role': 'assistant', 'content': r.texte},
                           {'role': 'user', 'content': 'Réponse illisible : renvoie uniquement l’objet JSON demandé.'}]
            continue
        t.textes.append(objet['reponse'].strip())
        choix = objet.get('choix')
        if isinstance(choix, dict):
            t.etat.executer('proposer_choix', choix)
        operations = objet.get('operations')
        if not operations:
            return
        contenu, erreur = t.etat.executer('proposer_operations', {'operations': operations})
        if not erreur or essai == 2:
            return
        t.textes.pop()
        conv = conv + [{'role': 'assistant', 'content': r.texte},
                       {'role': 'user', 'content': 'Opérations refusées : ' + contenu
                        + '. Renvoie l’objet JSON complet corrigé.'}]
