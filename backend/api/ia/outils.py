"""Les outils de l'assistant (chat intégré) et leur exécution côté serveur.

Quatre outils, déclarés une fois sous une forme neutre (`OUTILS`) puis traduits
pour chaque fournisseur (`pour_anthropic`, `pour_mistral`). Liste figée et triée :
c'est le début du préfixe mis en cache par Anthropic.

Lecture (`lire_elements`, `verifier_spec`) : exécutée tout de suite. Écriture
(`proposer_operations`) : essai à blanc seulement (api.patching.essayer_operations),
sur la spec ET sur les propositions précédentes du tour — rien n'est écrit en
base, l'utilisateur applique ensuite (POST /api/apps/<id>/operations/).
`proposer_choix` est terminal : il termine le tour.

Résultats : JSON compact, plafonnés (PLAFOND_RESULTAT) — au-delà, refus explicite
plutôt que troncature silencieuse.
"""
import json
import re

from .. import budget, conformite, lecture, patching

PLAFOND_RESULTAT = 6_000          # jetons estimés
MAX_OPERATIONS = 40

SECTIONS = ['meta', 'regles', 'roles', 'jobs', 'integrations', 'api_externes', 'extensions',
            'modeles', 'groupes', 'services', 'pages']
TYPES_CIBLE = ['meta', 'groupe_requis', 'regle', 'role', 'job', 'integration', 'api_externe',
               'extension', 'modele', 'champ', 'relation', 'groupe_endpoints', 'endpoint',
               'service', 'page', 'interaction', 'pipeline']

# Schéma d'UNE opération (I2). `data` est polymorphe : non strict, validé par le serveur.
SCHEMA_OPERATION = {
    'type': 'object', 'additionalProperties': False, 'required': ['op', 'cible'],
    'properties': {
        'op': {'type': 'string', 'enum': ['upsert', 'remove', 'rename']},
        'cible': {'type': 'object', 'additionalProperties': False, 'required': ['type'], 'properties': {
            'type': {'type': 'string', 'enum': TYPES_CIBLE},
            'nom': {'type': 'string', 'description': 'endpoint : "METHODE /chemin/" ; extension : "<liste>:<name>"'},
            'modele': {'type': 'string'}, 'groupe': {'type': 'string'}, 'page': {'type': 'string'}}},
        'nouveau_nom': {'type': 'string', 'description': 'op=rename seulement'},
        'data': {'type': 'object', 'description': 'op=upsert : seulement les clés qui changent'},
    },
}

OUTILS = [
    {'name': 'lire_elements', 'strict': True,
     'description': "Rend le détail JSON d'éléments de la spécification (noms : voir l'index). ≤ 10 éléments.",
     'schema': {'type': 'object', 'additionalProperties': False, 'required': ['section', 'noms'], 'properties': {
         'section': {'type': 'string', 'enum': SECTIONS},
         'noms': {'type': 'array', 'maxItems': 10, 'items': {'type': 'string'},
                  'description': 'Noms exacts (titre pour une règle). Vide = toute la section, refusé si trop grosse.'}}}},
    {'name': 'proposer_choix', 'strict': True,
     'description': "Pose UNE question fermée et termine ton tour. L'interface ajoute « Autre… ».",
     'schema': {'type': 'object', 'additionalProperties': False, 'required': ['question', 'options', 'multiple'],
                'properties': {'question': {'type': 'string'}, 'multiple': {'type': 'boolean'},
                               'options': {'type': 'array', 'minItems': 2, 'maxItems': 6,
                                           'items': {'type': 'string'}}}}},
    {'name': 'proposer_operations', 'strict': False,
     'description': ("Propose des modifications atomiques, vérifiées à blanc sur la spec et sur tes propositions "
                     "précédentes du tour ; tu reçois le résumé ou les erreurs par opération. Rien n'est appliqué "
                     "sans l'utilisateur."),
     'schema': {'type': 'object', 'additionalProperties': False, 'required': ['operations'], 'properties': {
         'operations': {'type': 'array', 'minItems': 1, 'maxItems': MAX_OPERATIONS, 'items': SCHEMA_OPERATION}}}},
    {'name': 'verifier_spec', 'strict': True,
     'description': ('Blocages du lab et manques de qualité (accès aux données, règles sans endpoint, rôles hors '
                     'des groupes requis…).'),
     'schema': {'type': 'object', 'additionalProperties': False, 'properties': {}, 'required': []}},
]
OUTILS.sort(key=lambda o: o['name'])
NOMS = {o['name'] for o in OUTILS}


def _sans_contraintes_de_tableau(schema):
    """Le mode strict d'Anthropic refuse les contraintes de tableau complexes
    (minItems/maxItems) : on les retire du schéma strict ; le serveur les
    revérifie (`EtatDuTour`)."""
    if isinstance(schema, dict):
        return {k: _sans_contraintes_de_tableau(v) for k, v in schema.items() if k not in ('minItems', 'maxItems')}
    if isinstance(schema, list):
        return [_sans_contraintes_de_tableau(v) for v in schema]
    return schema


def pour_anthropic(strict: bool = True) -> list[dict]:
    """`strict` : le modèle accepte `strict: true` (pas Sonnet 4.6)."""
    outils = []
    for o in OUTILS:
        if o['strict'] and strict:
            d = {'name': o['name'], 'description': o['description'],
                 'input_schema': _sans_contraintes_de_tableau(o['schema']), 'strict': True}
        else:
            d = {'name': o['name'], 'description': o['description'], 'input_schema': o['schema']}
        outils.append(d)
    return outils


def pour_mistral() -> list[dict]:
    return [{'type': 'function', 'function': {'name': o['name'], 'description': o['description'],
                                              'parameters': o['schema']}} for o in OUTILS]


def compact(objet) -> str:
    return json.dumps(objet, ensure_ascii=False, separators=(',', ':'), default=str)


def plafonne(objet) -> tuple[str, bool]:
    """(texte, est_une_erreur) : le résultat, ou un refus s'il dépasse le plafond."""
    texte = compact(objet)
    if budget.estimer_jetons(texte) > PLAFOND_RESULTAT:
        return compact({'error': 'trop_gros', 'detail': 'Résultat trop volumineux : demande moins d’éléments.'}), True
    return texte, False


_PREFIXE = re.compile(r'^opération (\d+) : ')


def renumeroter(erreurs, decalage: int) -> list[str]:
    """Les erreurs d'un essai sur `cumul + nouvelles` ramenées aux indices des nouvelles."""
    sortie = []
    for e in erreurs or []:
        e = str(e)
        m = _PREFIXE.match(e)
        if m and decalage:
            i = int(m.group(1)) - decalage
            e = (f'opération {i} : ' if i >= 1 else 'proposition précédente : ') + e[m.end():]
        sortie.append(e)
    return sortie


class EtatDuTour:
    """Ce que le tour a accumulé : la spec de départ (lue en base), l'état après
    les propositions acceptées à blanc, les opérations retenues, les échecs."""

    def __init__(self, spec: dict):
        self.spec = spec
        self.etat = spec
        self.operations: list = []
        self.erreurs: list = []
        self.echecs_consecutifs = 0
        self.choix = None
        self.jetons_resultats = 0

    # ── Exécution d'un appel ──────────────────────────────────────────────────

    def executer(self, nom: str, entree) -> tuple[str, bool]:
        """(contenu, is_error) — jamais d'exception vers la boucle."""
        if nom not in NOMS:
            return compact({'error': 'outil_inconnu', 'detail': f'Outil inconnu : {nom}.'}), True
        if not isinstance(entree, dict):
            return compact({'error': 'arguments', 'detail': 'Arguments illisibles : un objet JSON est attendu.'}), True
        try:
            texte, erreur = getattr(self, '_' + nom)(entree)
        except patching.PatchRefuse as refus:
            texte, erreur = compact({'error': 'refus', 'detail': list(refus.erreurs)}), True
        self.jetons_resultats += budget.estimer_jetons(texte)
        return texte, erreur

    def _lire_elements(self, entree):
        section, noms = entree.get('section'), entree.get('noms', [])
        if section not in SECTIONS:
            return compact({'error': 'section', 'detail': f'Section inconnue ; attendu : {", ".join(SECTIONS)}.'}), True
        if not isinstance(noms, list) or not all(isinstance(n, str) for n in noms):
            return compact({'error': 'noms', 'detail': 'noms : une liste de chaînes est attendue.'}), True
        resultat = lecture.lire_elements(self.etat, section, noms[:10])
        if isinstance(resultat, dict) and resultat.get('erreur'):
            return compact({'error': resultat['erreur'], 'detail': resultat.get('message', '')}), True
        return plafonne(resultat)

    def _verifier_spec(self, entree):
        return plafonne(conformite.verifier(self.etat))

    def _proposer_choix(self, entree):
        question, options, multiple = entree.get('question'), entree.get('options'), entree.get('multiple', False)
        if (not isinstance(question, str) or not question.strip() or not isinstance(options, list)
                or not 2 <= len(options) <= 6 or not all(isinstance(o, str) and o.strip() for o in options)):
            return compact({'error': 'choix', 'detail': 'Une question et 2 à 6 options (chaînes) sont attendues.'}), True
        self.choix = {'question': question.strip(), 'multiple': bool(multiple), 'items': [o.strip() for o in options]}
        return compact({'ok': True, 'detail': 'Question posée ; ton tour est terminé.'}), False

    def _proposer_operations(self, entree):
        nouvelles = entree.get('operations')
        if not isinstance(nouvelles, list) or not nouvelles or not all(isinstance(o, dict) for o in nouvelles):
            self.echecs_consecutifs += 1
            return compact({'error': 'operations', 'detail': 'operations : une liste non vide d’objets est attendue.'}), True
        if len(self.operations) + len(nouvelles) > MAX_OPERATIONS * 2:
            self.echecs_consecutifs += 1
            return compact({'error': 'operations', 'detail': 'Trop d’opérations pour un tour : propose moins à la fois.'}), True
        lot = self.operations + nouvelles
        try:
            apres = patching.essayer_operations(self.spec, lot)
        except patching.PatchRefuse as refus:
            self.echecs_consecutifs += 1
            erreurs = renumeroter(refus.erreurs, len(self.operations))
            self.erreurs = erreurs
            return compact({'error': 'refus', 'detail': erreurs,
                            'consigne': 'Rien n’a été retenu de ce lot : corrige et propose-le à nouveau.'}), True
        self.echecs_consecutifs = 0
        self.erreurs = []
        resume_lot = patching.resume_operations(self.etat, nouvelles, apres)
        self.operations = lot
        self.etat = apres
        return plafonne({'ok': True, 'resume': resume_lot.get('texte', ''),
                         'destructive': bool(resume_lot.get('destructive')),
                         'operations_retenues_ce_tour': len(self.operations)})

    # ── Ce que rend le tour ───────────────────────────────────────────────────

    def proposition(self, base_version: str) -> dict | None:
        if not self.operations and not self.erreurs:
            return None
        resume = (patching.resume_operations(self.spec, self.operations, self.etat) if self.operations
                  else {'texte': '', 'destructive': False, 'details': []})
        return {'operations': self.operations, 'resume': resume, 'base_version': base_version,
                'erreurs': list(self.erreurs)}
