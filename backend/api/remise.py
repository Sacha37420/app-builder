"""Remise au lab : cahier des charges et feuille de route générés depuis une spécification.

Génération déterministe, à partir de la spec seule — aucune IA, aucun réseau.
Ce qui sort d'ici est remis au moteur du lab (par le navigateur de
l'utilisateur de lab-admin) pour créer le projet :

- `lots_md` remplace, dans la `FEUILLE_DE_ROUTE.md` du gabarit, tout ce qui suit
  le Lot 1 : il ne contient donc ni en-tête, ni « Commande de test », ni Lot 1,
  et ses lots sont numérotés à partir de 2 ;
- `cahier_des_charges_md` devient `CAHIER_DES_CHARGES.md` à la racine du projet.

Le moteur valide la graine avant toute création (`valider_graine` reprend ses
règles à l'identique) : un texte saisi par l'utilisateur ne doit jamais pouvoir
la rendre invalide. D'où `_ligne` : dans `lots_md`, tout ce qui vient de la spec
tient sur une ligne qui ne commence jamais par « # ».
"""
import hashlib
import json
import re
import unicodedata

from . import conformite
from .budget import LOT_BUDGET_JETONS, estimer_jetons

# Règles du moteur sur la graine (contrat du chantier « app-builder-lab », I2).
LOTS_MD_MAX = 100_000
CAHIER_MD_MAX = 200_000
LOTS_MAX = 40
PREMIER_LOT = 2
TITRE_DE_LOT = re.compile(r'^## Lot ([0-9]+) — .+·[ \t\n\r\f\v]*statut : à faire[ \t\n\r\f\v]*$')

# Taille visée pour un lot : assez petit pour qu'un agent le tienne à l'aise,
# assez gros pour ne pas émietter la feuille de route.
LOT_CIBLE_JETONS = 6_000

# Dans le cahier des charges, aucune troncature : ce plafond n'est qu'un garde-fou
# (le contrôle `context_budget` sur CAHIER_MD_MAX protège la taille totale).
TEXTE_ENTIER = 100_000

# Lignes fixes du cahier, retirées avant le calcul de l'empreinte (voir `empreinte`).
LIGNE_ETAT = 'Spécification App Builder n° '
LIGNE_EMPREINTE = 'Empreinte de la spécification : '

_LIBELLE_TYPE = {'django-angular': 'Django + Angular', 'django': 'Django seul (API)', 'angular': 'Angular seul'}
_LIBELLE_OPERATION = {'list': 'liste', 'create': 'création', 'retrieve': 'lecture', 'update': 'remplacement',
                      'partial_update': 'modification', 'delete': 'suppression', 'custom': 'traitement propre'}
_CONTROLES = re.compile(r'[\x00-\x1f\x7f-\x9f\u2028\u2029]+')
_CONTROLES_SAUF_SAUT = re.compile(r'[\x00-\x09\x0b-\x1f\x7f-\x9f\u2028\u2029]+')


# ── Texte sûr ─────────────────────────────────────────────────────────────────

def _ligne(v, maxi=600) -> str:
    """Une valeur de la spec sur UNE ligne : ni saut de ligne, ni caractère de contrôle."""
    texte = _CONTROLES.sub(' ', v if isinstance(v, str) else ('' if v is None else str(v)))
    texte = re.sub(r' {2,}', ' ', texte).strip()
    return texte if len(texte) <= maxi else texte[:maxi - 1].rstrip() + '…'


def _bloc(v, maxi=4000) -> str:
    """Un texte libre de la spec, sauts de ligne gardés, sans retour chariot ni octet nul."""
    texte = v if isinstance(v, str) else ''
    texte = _CONTROLES_SAUF_SAUT.sub(' ', texte.replace('\r\n', '\n').replace('\r', '\n')).strip()
    return texte if len(texte) <= maxi else texte[:maxi - 1].rstrip() + '…'


def _code(v) -> str:
    return '`' + (_ligne(v, 200).replace('`', "'") or '?') + '`'


def _identifiant(nom, defaut='Element') -> str:
    """« Lignes de commande » → « LignesDeCommande » : un nom de classe de test."""
    ascii_ = unicodedata.normalize('NFKD', _ligne(nom, 80)).encode('ascii', 'ignore').decode()
    mots = re.findall(r'[A-Za-z0-9]+', ascii_)
    ident = ''.join(m[0].upper() + m[1:] for m in mots)
    if not ident:
        return defaut
    return ident if ident[0].isalpha() else defaut + ident


def _liste(v):
    return v if isinstance(v, list) else []


def _dicts(v):
    return [x for x in _liste(v) if isinstance(x, dict)]


def _ids(v) -> list:
    """Identifiants de liens (`service_ids`, `endpoint_group_ids`) : seuls les
    entiers et textes comptent ; une valeur non hachable ne fait pas tomber la génération."""
    return [x for x in _liste(v) if isinstance(x, (int, str)) and not isinstance(x, bool)]


def _noms(v) -> list[str]:
    return [_ligne(x, 80) for x in _liste(v) if isinstance(x, str) and x.strip()]


def _t(v, maxi, entier=False) -> str:
    """`_ligne` plafonné pour la feuille de route, entier pour le cahier."""
    return _ligne(v, TEXTE_ENTIER if entier else maxi)


def _objet(v) -> dict:
    return v if isinstance(v, dict) else {}


def _nombre(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# Une ligne de texte libre qui, en début de ligne, ferait un titre (« # », ou une
# ligne de « = » / « - » sous un paragraphe), ou ouvrirait un bloc de code qui
# avalerait la suite : précédée d'une barre oblique inverse, elle reste du texte.
_DEBUT_DANGEREUX = re.compile(r'^([ \t]*)(#|=+[ \t]*$|-{2,}[ \t]*$|```|~~~)')


def _neutraliser(texte: str) -> str:
    return '\n'.join(_DEBUT_DANGEREUX.sub(lambda m: m.group(1) + '\\' + m.group(2), ligne)
                     for ligne in texte.split('\n'))


def _para(v) -> str:
    """Un texte libre entier, sauts de ligne gardés, qui ne peut créer aucun titre."""
    return _neutraliser(_bloc(v, TEXTE_ENTIER))


def _item(tete: str, v, sep=' — ') -> list[str]:
    """Un élément de liste suivi d'un texte libre entier : la première ligne du texte
    sur la ligne de l'élément, les suivantes en continuation (indentées, neutralisées)."""
    texte = _bloc(v, TEXTE_ENTIER)
    if not texte:
        return [tete]
    premiere, _, suite = texte.partition('\n')
    resultat = [tete + sep + premiere]
    if suite:
        resultat += [('  ' + ligne) if ligne.strip() else '' for ligne in _neutraliser(suite).split('\n')]
    return resultat


def _valeur(v) -> str:
    """Valeur d'un réglage libre (`components[].config`) sur une ligne."""
    if isinstance(v, str):
        return _ligne(v, TEXTE_ENTIER)
    try:
        return _ligne(json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str), TEXTE_ENTIER)
    except (TypeError, ValueError):
        return _ligne(str(v), TEXTE_ENTIER)


# ── Qui (règles d'accès, transitions) ─────────────────────────────────────────

def _qui(w) -> str:
    w = _ligne(w, 80)
    if w == 'owner':
        return 'le propriétaire'
    if w == 'public':
        return 'tout visiteur, sans compte'
    if w == 'member':
        return 'tout membre'
    genre, _, nom = w.partition(':')
    if nom and genre == 'role':
        return f'le rôle {nom}'
    if nom and genre == 'share':
        return f'un partage « {nom} »'
    if nom and genre == 'group':
        return f'le groupe {nom}'
    return w


def _a_qui(qui: list[str]) -> str:
    """« au propriétaire, au rôle manager, à tout membre »."""
    return ', '.join(('au ' + q[3:]) if q.startswith('le ') else ('à ' + q) for q in (_qui(w) for w in qui))


def _non(w) -> str:
    w = _ligne(w, 80)
    if w == 'owner':
        return 'un non-propriétaire'
    if w == 'member':
        return 'un compte hors des groupes requis'
    genre, _, nom = w.partition(':')
    if nom and genre == 'role':
        return f'un membre sans le rôle {nom}'
    if nom and genre == 'share':
        return f'un compte sans partage « {nom} »'
    if nom and genre == 'group':
        return f'un compte hors du groupe {nom}'
    return f'un compte qui n\'est pas {w}'


def _refuse_a(qui: list[str]) -> str:
    """Qui est refusé quand seuls `qui` sont permis ('' si personne : public)."""
    if not qui or 'public' in qui:
        return ''
    if len(qui) == 1:
        return _non(qui[0])
    return 'un compte qui n\'est ni ' + ' ni '.join(_qui(w) for w in qui)


_VERBES = {'read': ('lit', 'lecture'), 'create': ('crée', 'création'), 'update': ('modifie', 'modification'),
           'delete': ('supprime', 'suppression'), 'manage_shares': ('gère', 'gestion des partages')}


def _objet_action(action: str, modele: str) -> str:
    return {'read': f'les {modele} d\'un autre', 'create': f'de {modele}',
            'manage_shares': f'les partages d\'un {modele}'}.get(action, f'un {modele}')


def _cas_d_acces(nom: str, access: dict) -> list[str]:
    """Les cas de test qui découlent de `access` (vide ⇒ aucun)."""
    modele = _code(nom)
    cas = []
    regles = _dicts(access.get('rules'))
    scope = _ligne(access.get('scope'), 30)
    if not regles:
        if scope == 'owner':
            cas.append(f'un autre compte ne voit pas les {modele} de l\'autre')
        elif scope == 'shared':
            cas.append(f'un compte sans partage ne voit pas les {modele} d\'un autre')
        elif scope == 'parent' and _ligne(access.get('parent')):
            cas.append(f"un compte sans accès à {_code(access['parent'])} ne voit pas les {modele} qui en dépendent")
        elif scope == 'public_read':
            cas.append(f'les {modele} se lisent sans jeton ; toute écriture sans jeton est refusée')
    for r in regles:
        action = _ligne(r.get('action'), 30)
        verbe, libelle = _VERBES.get(action, (action or 'agit sur', action or 'action'))
        qui = _noms(r.get('who'))
        if not qui:
            continue
        cas.append(f"{libelle} d'un {modele} permise " + _a_qui(qui))
        refuse = _refuse_a(qui)
        if refuse:
            cas.append(f'{refuse} ne {verbe} pas {_objet_action(action, modele)}')
    if _ligne(access.get('public_flag')):
        drapeau = _code(access['public_flag'])
        cas.append(f'lecture anonyme d\'un {modele} seulement si {drapeau} est vrai ; refusée sans jeton quand {drapeau} est faux')
    for h in _dicts(access.get('hidden_fields')):
        if _ligne(h.get('field')):
            sauf = _ligne(h.get('unless'), 80)
            cas.append(f"{_code(h['field'])} n'est pas rendu" + (' sauf ' + _a_qui([sauf]) if sauf else ''))
    return cas


def _cas_d_etats(nom: str, states: dict) -> list[str]:
    modele = _code(nom)
    champ = _code(states.get('field')) if _ligne(states.get('field')) else '`état`'
    cas = []
    if _ligne(states.get('initial')):
        cas.append(f"un {modele} créé est à l'état {_code(states['initial'])}")
    transitions = _dicts(states.get('transitions'))
    for tr in transitions:
        depuis = _noms(tr.get('from')) or ([_ligne(tr['from'], 80)] if _ligne(tr.get('from')) else [])
        vers = _ligne(tr.get('to'), 80)
        if not vers:
            continue
        passage = f"{'/'.join(depuis) or '?'} → {vers}"
        par = _noms(tr.get('by'))
        cas.append(f'transition {passage} permise ' + (_a_qui(par) if par else 'à qui y a droit'))
        refuse = _refuse_a(par)
        if refuse:
            cas.append(f'transition {passage} refusée à {refuse}')
    if transitions:
        cas.append(f'une transition non déclarée de {champ} est refusée')
    for gel in _noms(states.get('frozen_in')):
        cas.append(f'un {modele} à l\'état {_code(gel)} n\'est plus modifiable')
    return cas


def _acces_md(access: dict, entier=False) -> str:
    """Les droits d'un modèle sur une ligne."""
    if not access:
        return 'non décrit : par défaut, propriétaire seul'
    parties = []
    scope = _ligne(access.get('scope'), 30)
    if scope:
        parties.append(f'portée {scope}')
    for cle, libelle in (('owner_field', 'champ propriétaire'), ('parent', 'suit la relation'),
                         ('share_model', 'partages par'), ('public_flag', 'lecture anonyme si')):
        if _ligne(access.get(cle)):
            parties.append(f'{libelle} {_code(access[cle])}')
    for r in _dicts(access.get('rules')):
        if _ligne(r.get('action')):
            parties.append(f"{_ligne(r['action'], 30)} : " + (', '.join(_noms(r.get('who'))) or 'personne'))
    for h in _dicts(access.get('hidden_fields')):
        if _ligne(h.get('field')):
            parties.append(f"{_code(h['field'])} masqué" + (f" sauf pour {_ligne(h.get('unless'), 80)}" if _ligne(h.get('unless')) else ''))
    if _ligne(access.get('reason')):
        parties.append('raison : ' + _t(access['reason'], 300, entier))
    return ' ; '.join(parties) or 'non décrit : par défaut, propriétaire seul'


def _transition(tr: dict) -> str:
    depuis = _noms(tr.get('from')) or ([_ligne(tr['from'], 80)] if _ligne(tr.get('from')) else [])
    texte = f"{', '.join(depuis) or '?'} → {_ligne(tr.get('to'), 80) or '?'}"
    par = _noms(tr.get('by'))
    if par:
        texte += ' par ' + ', '.join(par)
    if _ligne(tr.get('action')):
        texte += f" (action {_code(tr['action'])})"
    effets = _noms(tr.get('side_effects'))
    if effets:
        texte += ' ; effets : ' + ', '.join(effets)
    return texte


def _etats_md(states: dict) -> str:
    texte = f"états de {_code(states.get('field')) if _ligne(states.get('field')) else '?'}"
    if _noms(states.get('values')):
        texte += ' : ' + ', '.join(_noms(states.get('values')))
    if _ligne(states.get('initial')):
        texte += f" (initial {_code(states['initial'])})"
    transitions = [_transition(tr) for tr in _dicts(states.get('transitions'))]
    if transitions:
        texte += ' ; transitions : ' + ' | '.join(transitions)
    if _noms(states.get('frozen_in')):
        texte += ' ; gelé dans : ' + ', '.join(_noms(states.get('frozen_in')))
    return texte


def _contrainte(c: dict) -> str:
    genre = _ligne(c.get('kind'), 20) or 'contrainte'
    texte = genre
    if _noms(c.get('fields')):
        texte += ' sur ' + ', '.join(_code(f) for f in _noms(c.get('fields')))
    if _ligne(c.get('condition')):
        texte += f" : {_code(c['condition'])}"
    if _ligne(c.get('name')):
        texte += f" (nom {_code(c['name'])})"
    return texte


# ── Lecture de la spec ────────────────────────────────────────────────────────

def _champ(f, entier=False) -> str:
    details = [_ligne(f.get('type'), 30) or 'string']
    details.append('requis' if f.get('required') is not False else 'facultatif')
    if f.get('unique'):
        details.append('unique')
    if f.get('unique_ci') is True:
        details.append('unique sans tenir compte de la casse')
    if isinstance(f.get('max_length'), int):
        details.append(f"{f['max_length']} caractères au plus")
    if f.get('default') not in (None, ''):
        details.append(f"défaut {_code(f['default'])}")
    valeurs = _noms(f.get('values'))
    if valeurs:
        details.append('valeurs : ' + ', '.join(valeurs))
    if _nombre(f.get('min')):
        details.append(f"minimum {f['min']}")
    if _nombre(f.get('max')):
        details.append(f"maximum {f['max']}")
    if _ligne(f.get('pattern')):
        details.append(f"motif {_code(f['pattern'])}")
    if isinstance(f.get('max_bytes'), int) and not isinstance(f.get('max_bytes'), bool):
        details.append(f"{f['max_bytes']} octets au plus")
    accept = _noms(f.get('accept')) or ([_ligne(f['accept'], 200)] if _ligne(f.get('accept')) else [])
    if accept:
        details.append('types acceptés : ' + ', '.join(accept))
    if _ligne(f.get('geometry_kind')):
        details.append(f"géométrie {_ligne(f['geometry_kind'], 40)}")
    if isinstance(f.get('srid'), int) and not isinstance(f.get('srid'), bool):
        details.append(f"SRID {f['srid']}")
    texte = f"{_code(f.get('name'))} ({', '.join(details)})"
    if f.get('type') == 'storage_file':
        texte += ' — chemin d\'un fichier déposé dans le service storage'
    if f.get('type') == 'secret':
        portee = _ligne(f.get('secret_scope'), 10)
        texte += (' — secret chiffré au coffre' + (f' (portée {portee})' if portee else '')
                  + ', jamais rendu par l\'API (seul le fait qu\'il soit renseigné l\'est)')
    if _ligne(f.get('help_text')):
        texte += f" — {_t(f['help_text'], 200, entier)}"
    return texte


def _relation(r) -> str:
    genre = {'FK': 'plusieurs vers un', 'M2M': 'plusieurs vers plusieurs', 'O2O': 'un vers un'}.get(r.get('rel_type'), 'lien')
    texte = f"{_code(r.get('name'))} → {_code(r.get('to_model'))} ({genre}"
    if r.get('rel_type') != 'M2M' and _ligne(r.get('on_delete')):
        texte += f", à la suppression : {_ligne(r['on_delete'], 20)}"
    if _ligne(r.get('related_name')):
        texte += f", accès inverse {_code(r['related_name'])}"
    return texte + ')'


def _route(e) -> str:
    return f"{_ligne(e.get('method'), 10) or 'GET'} {_ligne(e.get('path'), 300) or '/'}"


def _schema(v) -> str:
    if isinstance(v, dict) and v:
        return ', '.join(f'{_ligne(k, 60)} ({_ligne(t, 40)})' for k, t in list(v.items())[:40])
    return ''


def _auth(e, entier=False) -> str:
    """Le mode d'authentification d'un endpoint quand ce n'est pas le jeton du lab ('' sinon)."""
    auth = _objet(e.get('auth'))
    mode = _ligne(auth.get('mode'), 30)
    if not mode or mode == 'jwt':
        return ''
    texte = f'authentification {mode}'
    if _ligne(auth.get('caller')):
        texte += f", appelant {_ligne(auth['caller'], 80)}"
    if _ligne(auth.get('key_source')):
        texte += f", clé : {_t(auth['key_source'], 200, entier)}"
    if _ligne(auth.get('reason')):
        texte += f" ({_t(auth['reason'], 300, entier)})"
    return texte


def _endpoint(e, entier=False) -> str:
    texte = f"`{_route(e)}` — {_LIBELLE_OPERATION.get(e.get('operation'), 'traitement propre')}"
    if _ligne(e.get('linked_model_name')):
        texte += f" sur {_code(e['linked_model_name'])}"
    if _ligne(e.get('description')):
        texte += f" : {_t(e['description'], 400, entier)}"
    precisions = []
    if e.get('auth_required') is False:
        precisions.append('ROUTE PUBLIQUE (sans jeton)')
    if _auth(e, entier):
        precisions.append(_auth(e, entier))
    roles = _noms(e.get('required_roles'))
    if roles:
        precisions.append('réservé aux groupes ' + ', '.join(roles))
    params = [f"{_ligne(q.get('name'), 60)} ({_ligne(q.get('type'), 30) or 'string'}"
              f"{', requis' if q.get('required') else ''})" for q in _dicts(e.get('query_params')) if _ligne(q.get('name'))]
    if params:
        precisions.append('paramètres : ' + ', '.join(params))
    if _schema(e.get('request_schema')):
        precisions.append('corps reçu : ' + _schema(e['request_schema']))
    if _schema(e.get('response_schema')):
        precisions.append('réponse : ' + _schema(e['response_schema']))
    if entier:
        etapes = [(_ligne(s.get('label'), 200) or _ligne(s.get('type'), 30))
                  + (f" [{_ligne(s['type'], 30)}]" if _ligne(s.get('type')) and _ligne(s.get('label')) else '')
                  + (f" ({_t(s['description'], 200, True)})" if _ligne(s.get('description')) else '')
                  for s in _dicts(e.get('steps')) if _ligne(s.get('label')) or _ligne(s.get('type'))]
    else:
        etapes = [_ligne(s.get('label'), 80) + (f" ({_ligne(s['description'], 200)})" if _ligne(s.get('description')) else '')
                  for s in _dicts(e.get('steps')) if _ligne(s.get('label'))]
    if etapes:
        precisions.append('étapes : ' + ' → '.join(etapes))
    return texte + (' — ' + ' ; '.join(precisions) if precisions else '')


def _test_endpoint(e, groupes_requis) -> str:
    route = f'`{_route(e)}`'
    if e.get('auth_required') is False:
        return f"{route} répond sans jeton, et ne rend rien d'autre que ce que la décision de route publique autorise"
    cas = ['réponse attendue pour un membre ' + ('du groupe ' + ' ou '.join(groupes_requis) if groupes_requis else 'autorisé'),
           'refus sans jeton', "refus (403) d'un jeton émis pour un autre client (`azp`)"]
    if groupes_requis:
        cas.append("refus (403) d'un compte hors des groupes requis")
    roles = _noms(e.get('required_roles'))
    if roles:
        cas.append('refus (403) d\'un membre qui n\'est pas dans ' + ' ou '.join(roles))
    return f"{route} : " + ' ; '.join(cas)


def _composant(c, entier=False) -> str:
    texte = f"{_ligne(c.get('type'), 30) or 'composant'} « {_t(c.get('label'), 120, entier) or 'sans titre'} »"
    if _ligne(c.get('linked_model')):
        texte += f" sur {_code(c['linked_model'])}"
    champs = _noms(c.get('fields'))
    if champs:
        texte += ' (champs : ' + ', '.join(champs[:30]) + ')'
    return texte


def _etape_pipeline(s, entier=False) -> str:
    texte = _t(s.get('label'), 120, entier) or _ligne(s.get('type'), 30) or 'étape'
    precisions = []
    if entier and _ligne(s.get('type')):
        precisions.append('type ' + _ligne(s['type'], 30))
    precisions += [_t(s.get(c), 200, entier) for c in ('service_method', 'data_flow', 'description') if _ligne(s.get(c))]
    if _ligne(s.get('on_error')):
        precisions.append('en cas d\'erreur : ' + _t(s['on_error'], 200, entier))
    return texte + (' (' + ' ; '.join(precisions) + ')' if precisions else '')


# ── Lots ──────────────────────────────────────────────────────────────────────

def _unites(spec: dict) -> dict:
    """Ce qu'il y a à construire, famille par famille. Une unité ne se coupe pas :
    un modèle, un groupe d'endpoints, un service, une page, les pipelines d'une page."""
    app_type = spec.get('app_type')
    inconnu = app_type not in conformite.TYPES_CONSTRUCTIBLES
    backend = inconnu or conformite.a_un_backend(app_type)
    frontend = inconnu or conformite.a_un_frontend(app_type)
    groupes_requis = _noms(spec.get('required_groups'))
    familles = {'modeles': [], 'api': [], 'regles': [], 'jobs': [], 'services': [], 'pages': [], 'pipelines': []}
    idents = set()

    def classe(nom, suffixe):
        base, ident, n = _identifiant(nom), None, 1
        while ident is None or ident in idents:
            ident = f"{base}{'' if n == 1 else n}{suffixe}"
            n += 1
        idents.add(ident)
        return ident

    if backend:
        for m in _dicts(spec.get('data_models')):
            nom = _ligne(m.get('name'), 80)
            champs, relations = _dicts(m.get('fields')), _dicts(m.get('relationships'))
            taches = [f"Modèle {_code(nom)}" + (f" — {_ligne(m.get('description'), 400)}" if _ligne(m.get('description')) else '')
                      + (' ; champs : ' + ' ; '.join(_champ(f) for f in champs) if champs else ' ; aucun champ décrit')
                      + (' ; relations : ' + ' ; '.join(_relation(r) for r in relations) if relations else '')]
            cas = ['création valide']
            if any(f.get('required') is not False for f in champs):
                cas.append('champ requis manquant refusé')
            if any(f.get('unique') for f in champs):
                cas.append('doublon sur un champ unique refusé')
            if relations:
                cas.append('comportement à la suppression de chaque relation')
            for f in champs:
                if f.get('type') == 'storage_file':
                    taches.append(f"Fichier {_code(nom + '.' + _ligne(f.get('name'), 80))} : le modèle garde le chemin, les octets "
                                  "passent par l'API du service storage du lab (client `api/storage_client.py`, appels "
                                  'simulés dans les tests) — ni `FileField`, ni volume, ni blob en base')
                    cas.append(f"dépôt et lecture de {_code(f.get('name'))} par le client storage simulé")
                elif f.get('type') == conformite.TYPE_FICHIER_ANCIEN:
                    taches.append(f"⚠ {_code(nom + '.' + _ligne(f.get('name'), 80))} est encore de type « file » : à convertir "
                                  'en référence au service storage avant toute construction')
            for c in _dicts(m.get('constraints')):
                cas.append(f'{_contrainte(c)} : violation refusée')
            access, states = _objet(m.get('access')), _objet(m.get('states'))
            if access:
                taches.append(f"Droits sur {_code(nom)} (appliqués par le serveur, filtre de chaque requête) : {_acces_md(access)}")
            if _ligne(states.get('field')) or _dicts(states.get('transitions')):
                taches.append(f"Cycle de vie de {_code(nom)} : {_etats_md(states)} — chaque transition est une action "
                              "du serveur qui vérifie l'état courant et qui l'a demandée")
            tests = [f"`python manage.py test api.tests.{classe(nom, 'ModelTests')}` passe ({' ; '.join(cas)})"]
            cas_acces = _cas_d_acces(nom, access)
            if cas_acces:
                tests.append(f"`python manage.py test api.tests.{classe(nom, 'AccessTests')}` passe ({' ; '.join(cas_acces)})")
            cas_etats = _cas_d_etats(nom, states)
            if cas_etats:
                tests.append(f"`python manage.py test api.tests.{classe(nom, 'StateTests')}` passe ({' ; '.join(cas_etats)})")
            familles['modeles'].append({
                'label': nom, 'tasks': taches, 'tests': tests,
                'elements': [{'kind': 'data_model', 'name': nom}]})

        for g in _dicts(spec.get('endpoint_groups')):
            nom, points = _ligne(g.get('name'), 80), _dicts(g.get('endpoints'))
            taches = [_endpoint(e) for e in points] or [f'Groupe {_code(nom)} : aucun endpoint décrit — à préciser avant de coder']
            for e in points:
                if e.get('auth_required') is False:
                    raison = _ligne(e.get('public_reason'), 400)
                    taches.append(f'Décision explicite — route publique `{_route(e)}` : '
                                  + (raison if raison else 'JUSTIFICATION ABSENTE : la faire écrire par le commanditaire '
                                     'ou remettre la route derrière l\'authentification avant de coder'))
            tests = [f"`python manage.py test api.tests.{classe(nom, 'ApiTests')}` passe"
                     + (' : ' + ' | '.join(_test_endpoint(e, groupes_requis) for e in points) if points else '')]
            familles['api'].append({
                'label': nom, 'tasks': taches, 'tests': tests,
                'elements': [{'kind': 'endpoint_group', 'name': nom}]})

        regles = [r for r in _dicts(spec.get('business_rules')) if _ligne(r.get('title'))]
        for r in regles:
            titre = _ligne(r.get('title'), 200)
            familles['regles'].append({
                'label': titre,
                'tasks': [f"Règle « {titre} »" + (f" : {_ligne(r.get('description'), 600)}" if _ligne(r.get('description')) else '')
                          + _portee_regle(r)
                          + ' — appliquée côté serveur (jamais seulement dans l\'interface)'],
                'tests': [f"`python manage.py test api.tests.{classe(titre, 'RuleTests')}` passe (le cas permis passe, "
                          'le cas interdit est refusé avec un message clair)'],
                'elements': [{'kind': 'business_rule', 'name': titre}]})

        for j in _dicts(spec.get('jobs')):
            nom = _ligne(j.get('name'), 80)
            if not nom:
                continue
            cas = ['la tâche lancée fait son travail hors de la requête', "son échec est enregistré et visible, jamais silencieux"]
            if _ligne(j.get('tracked_by')):
                cas.append(f"l'avancement est suivi dans {_code(j['tracked_by'])}")
            if _ligne(j.get('concurrency')):
                cas.append(f"un second lancement concurrent est refusé ({_ligne(j['concurrency'], 80)})")
            familles['jobs'].append({
                'label': nom, 'tasks': [_job(j)],
                'tests': [f"`python manage.py test api.tests.{classe(nom, 'JobTests')}` passe ({' ; '.join(cas)} ; "
                          "la file est simulée dans les tests)"],
                'elements': [{'kind': 'job', 'name': nom}]})

    if frontend:
        groupes_par_id = {g.get('id'): g for g in _dicts(spec.get('endpoint_groups'))}
        services_par_id = {}
        for s in _dicts(spec.get('services')):
            nom = _ligne(s.get('name'), 80)
            services_par_id[s.get('id')] = nom
            lies = [groupes_par_id[i] for i in _ids(s.get('endpoint_group_ids')) if i in groupes_par_id]
            routes = [f'`{_route(e)}`' for g in lies for e in _dicts(g.get('endpoints'))]
            familles['services'].append({
                'label': nom,
                'tasks': [f"Service Angular {_code(nom)} (`src/app/core/`)"
                          + (' pour ' + ', '.join(_code(g.get('name')) for g in lies) if lies else ' — aucun groupe d\'endpoints relié')
                          + (' ; une méthode typée par route : ' + ', '.join(routes) if routes else '')
                          + ' ; l\'adresse de l\'API vient de `env.js`, jamais d\'une constante'],
                'tests': ['`npm run build` du frontend sans erreur'],
                'elements': [{'kind': 'service', 'name': nom}]})

        for p in _dicts(spec.get('pages')):
            nom = _ligne(p.get('name'), 80)
            services = [services_par_id[i] for i in _ids(p.get('service_ids')) if i in services_par_id]
            composants, interactions = _dicts(p.get('components')), _dicts(p.get('interactions'))
            taches = [f"Page {_code(nom)} — route {_code(p.get('route'))}, disposition {_ligne(p.get('layout'), 20) or 'mixed'}"
                      + (' ; services : ' + ', '.join(_code(s) for s in services) if services else '')
                      + _acces_page(p)
                      + ' ; entrée dans la navigation verticale (identité Foyer : tokens CSS, rupture à 900 px, cibles de 44 px)']
            if composants:
                taches.append(f'Composants de {_code(nom)} : ' + ' ; '.join(_composant(c) for c in composants))
            if interactions:
                taches.append(f'Interactions de {_code(nom)} : ' + ' ; '.join(
                    f"« {_ligne(i.get('name'), 120)} » ({_ligne(i.get('type'), 30) or 'autre'})"
                    + (f" — {_ligne(i.get('description'), 300)}" if _ligne(i.get('description')) else '')
                    for i in interactions if _ligne(i.get('name'))))
            familles['pages'].append({
                'label': nom, 'tasks': taches,
                'tests': ['`npm run build` du frontend sans erreur',
                          f"Page {_code(p.get('route'))} vérifiée dans le navigateur : elle s'ouvre depuis la navigation, "
                          'ses composants affichent les données de l\'API, en thème clair et sombre, à 900 px et en dessous'],
                'elements': [{'kind': 'page', 'name': nom}]})

            pipelines = [pl for pl in _dicts(p.get('pipelines')) if _ligne(pl.get('name'))]
            if pipelines:
                familles['pipelines'].append({
                    'label': nom,
                    'tasks': [f"Pipeline « {_ligne(pl.get('name'), 120)} » de {_code(nom)}"
                              + (f" — déclenché par « {_ligne(pl['trigger_interaction'], 120)} »" if _ligne(pl.get('trigger_interaction')) else '')
                              + (f" : {_ligne(pl.get('description'), 300)}" if _ligne(pl.get('description')) else '')
                              + (' ; étapes : ' + ' → '.join(_etape_pipeline(s) for s in _dicts(pl.get('steps')))
                                 if _dicts(pl.get('steps')) else ' ; étapes à préciser')
                              for pl in pipelines],
                    'tests': [f"Parcours « {_ligne(pl.get('name'), 120)} » vérifié dans le navigateur, cas d'erreur compris "
                              '(résultat noté sous « Vérifié le »)' for pl in pipelines],
                    'elements': [{'kind': 'pipeline', 'name': _ligne(pl.get('name'), 120), 'page': nom} for pl in pipelines]})
    return familles


def _portee_regle(r, entier=False) -> str:
    parties = []
    if _ligne(r.get('kind')):
        parties.append(f"nature {_ligne(r['kind'], 30)}")
    if _ligne(r.get('applies_to')):
        parties.append(f"porte sur {_code(r['applies_to'])}")
    appliquee = _noms(r.get('enforced_by'))
    if appliquee:
        parties.append('tenue par ' + ', '.join(_code(x) for x in appliquee))
    return (' (' + ' ; '.join(parties) + ')') if parties else ''


def _acces_page(p, entier=False) -> str:
    texte = ''
    if p.get('public') is True:
        raison = _t(p.get('public_reason'), 300, entier)
        texte += ' ; PAGE PUBLIQUE (sans connexion) : ' + (raison or 'JUSTIFICATION ABSENTE — décision à écrire avant de coder')
    roles = _noms(p.get('required_roles'))
    if roles:
        texte += ' ; réservée aux rôles ' + ', '.join(roles)
    return texte


def _job(j, entier=False) -> str:
    texte = f"Tâche de fond {_code(j.get('name'))} ({_ligne(j.get('kind'), 20) or 'async'}"
    if _ligne(j.get('trigger')):
        texte += f", déclenchée par {_code(j['trigger'])}"
    if _ligne(j.get('input_model')):
        texte += f", sur {_code(j['input_model'])}"
    if _ligne(j.get('tracked_by')):
        texte += f", suivie dans {_code(j['tracked_by'])}"
    if _ligne(j.get('concurrency')):
        texte += f", concurrence {_ligne(j['concurrency'], 80)}"
    if j.get('heavy') is True:
        texte += ', lourde'
    texte += ')'
    if _ligne(j.get('description')):
        texte += f" : {_t(j['description'], 400, entier)}"
    return texte


_FAMILLES = (
    ('modeles', 'Modèles de données',
     'les données de l\'app existent en base, avec leurs contraintes, et chaque modèle a ses tests.',
     ['Migrations générées et rejouables (`makemigrations`, appliquées au démarrage du conteneur)']),
    ('api', 'API',
     'les routes décrites répondent, derrière les deux verrous du lab, avec les rôles prévus.',
     ['Toute route reste derrière `api/authentication.py` (jeton du client de l\'app, groupes requis) ; '
      'chaque vue déclare qui a le droit de lire ou modifier quoi']),
    ('regles', 'Règles métier',
     'chaque règle métier validée est appliquée par le serveur et prouvée par un test.', []),
    ('jobs', 'Tâches de fond',
     'les tâches de fond décrites tournent hors de la requête, avec leur suivi et leurs erreurs.',
     ['Une tâche `async` ou `scheduled` tourne dans un worker Celery (avec Redis, sur `dev-net`) ; '
      'une tâche `command` est une commande de gestion Django']),
    ('services', 'Services d\'accès à l\'API',
     'le frontend dispose d\'un service typé par domaine, branché sur l\'API.', []),
    ('pages', 'Pages',
     'l\'utilisateur atteint ces pages depuis la navigation et y voit les données réelles.', []),
    ('pipelines', 'Pipelines',
     'les enchaînements décrits fonctionnent de bout en bout, erreurs comprises.', []),
)


def _rendre(lot: dict) -> str:
    lignes = [f"## Lot {lot['number']} — {lot['title']}   ·   statut : à faire",
              f"**Objectif :** {lot['objective']}", '**Tâches :**']
    lignes += [f'- [ ] {t}' for t in lot['tasks']]
    lignes.append('**Tests à passer avant de clore le lot :**')
    lignes += [f'- [ ] {t}' for t in lot['tests']]
    lignes.append('**Vérifié le :**')
    return '\n'.join(lignes) + '\n'


def _regrouper(unites: list, cible: int) -> list[list]:
    """Regroupe des unités voisines tant que le lot reste sous la taille visée."""
    paquets, courant, poids = [], [], 0
    for u in unites:
        p = estimer_jetons('\n'.join(u['tasks'] + u['tests']))
        if courant and poids + p > cible:
            paquets.append(courant)
            courant, poids = [], 0
        courant.append(u)
        poids += p
    if courant:
        paquets.append(courant)
    return paquets


def _titre(famille: str, paquet: list, rang: int, total: int) -> str:
    noms = [u['label'] for u in paquet if u['label']]
    if famille in ('modeles', 'regles') or not noms:
        return famille_titre(famille) + (f' ({rang}/{total})' if total > 1 else '')
    return f"{famille_titre(famille)} — {', '.join(noms[:3])}" + ('…' if len(noms) > 3 else '')


def famille_titre(famille: str) -> str:
    return next(t for cle, t, _, _ in _FAMILLES if cle == famille)


def _lots(spec: dict, cible: int) -> list[dict]:
    familles = _unites(spec)
    lots = []
    for cle, _titre_famille, objectif, communes in _FAMILLES:
        paquets = _regrouper(familles[cle], cible)
        for rang, paquet in enumerate(paquets, 1):
            lots.append({
                'family': cle, 'title': _titre(cle, paquet, rang, len(paquets)),
                'objective': objectif[0].upper() + objectif[1:],
                'tasks': (communes if rang == 1 else []) + [t for u in paquet for t in u['tasks']],
                'tests': list(dict.fromkeys(t for u in paquet for t in u['tests'])),
                'elements': [e for u in paquet for e in u['elements']]})

    vide = not (_dicts(spec.get('data_models')) or _dicts(spec.get('pages')) or conformite.endpoints(spec))
    if not vide:
        lots.append(_lot_de_recette(spec))
    for numero, lot in enumerate(lots, PREMIER_LOT):
        lot['number'] = numero
        lot['tokens'] = estimer_jetons(_rendre(lot))
    return lots


def _lot_de_recette(spec: dict) -> dict:
    app_type = spec.get('app_type')
    taches = ['Relire `CAHIER_DES_CHARGES.md` point par point et noter tout écart avec ce qui est livré']
    tests = []
    if conformite.a_un_backend(app_type) or app_type not in conformite.TYPES_CONSTRUCTIBLES:
        tests.append('Suite backend complète verte (commande de la section « Commande de test »)')
    if conformite.a_un_frontend(app_type) or app_type not in conformite.TYPES_CONSTRUCTIBLES:
        tests.append('`npm run build` du frontend sans erreur ; aucune couleur en dur dans les composants')
        tests.append('Test de cloisonnement `frontend/e2e/cloisonnement.spec.ts` vert après déploiement')
    if not conformite.a_un_backend(app_type):
        for r in _dicts(spec.get('business_rules')):
            if _ligne(r.get('title')):
                taches.append(f"Règle « {_ligne(r['title'], 200)} »"
                              + (f" : {_ligne(r.get('description'), 600)}" if _ligne(r.get('description')) else '')
                              + ' — vérifiée dans le navigateur')
    if spec.get('uses_email'):
        taches.append('Emails : envoyés par `send_mail` de Django, jamais de réglage SMTP dans le dépôt ; '
                      'rattacher un compte d\'envoi au projet dans lab-admin (carte « Email »)')
        tests.append('Un email d\'essai part (ou s\'affiche dans le journal du conteneur tant qu\'aucun compte n\'est rattaché)')
    if conformite.champs_storage(spec):
        taches.append('Storage : demander au lab d\'autoriser ce client auprès du service storage (ticket), '
                      'puis vérifier un dépôt et une lecture réels')
    publiques = conformite.routes_publiques(spec)
    if publiques:
        taches.append('Routes publiques : vérifier que seules ' + ', '.join(f"`{p['method']} {_ligne(p['path'], 200)}`" for p in publiques)
                      + ' répondent sans jeton')
    taches.append('Déployer par le moteur du lab (lab-admin → Projets → « Déployer ») et parcourir l\'app avec un compte '
                  'membre, puis avec un compte hors des groupes requis')
    tests.append('Un compte hors des groupes requis est refusé à la connexion ET sur l\'API (403)')
    return {'family': 'recette', 'title': 'Recette et mise en service',
            'objective': 'L\'app déployée fait ce que dit le cahier des charges, et rien n\'y entre sans le groupe requis.',
            'tasks': taches, 'tests': tests, 'elements': []}


def lots(spec: dict) -> list[dict]:
    """Les lots métier de la feuille de route, numérotés à partir de 2.

    La taille visée est relevée tant que la feuille de route dépasserait le
    nombre de lots que le moteur accepte ; au-delà du budget d'un lot, on s'arrête
    (la spec n'est alors pas « prête »)."""
    cible = LOT_CIBLE_JETONS
    resultat = _lots(spec, cible)
    while len(resultat) > LOTS_MAX and cible < LOT_BUDGET_JETONS:
        cible = min(cible * 2, LOT_BUDGET_JETONS)
        resultat = _lots(spec, cible)
    return resultat


def lots_md(lots_: list[dict]) -> str:
    return '\n'.join(_rendre(lot) for lot in lots_)


# ── Cahier des charges ────────────────────────────────────────────────────────
#
# Le cahier rend la spec ENTIÈRE (aucune troncature : `entier=True`, `_para`,
# `_item`). Tout texte libre y est soit sur la ligne d'un élément (aplati par
# `_ligne`), soit en paragraphe ou en continuation dont chaque ligne qui ferait un
# titre (« # », soulignement « = »/« - ») ou ouvrirait un bloc de code est
# précédée d'une barre oblique inverse (`_neutraliser`) : une description
# « ## Lot 99 — … » ne crée aucun titre.

def empreinte(lots_md_texte: str, cahier: str) -> str:
    """Empreinte de ce qui est remis : « sha256:<64 hex> ».

    sha256 (UTF-8) de `lots_md`, d'un saut de ligne, puis du cahier des charges
    privé de deux lignes : sa ligne d'état (« Spécification App Builder n° …, état
    du … » — la 3ᵉ, qui porte la date de modification) et la ligne d'empreinte qui
    la suit (elle ne peut pas se contenir elle-même). L'empreinte ne bouge donc pas
    quand seul `updated_at` change, et bouge dès que le contenu remis change.
    Le cahier peut être passé avec ou sans sa ligne d'empreinte : même résultat.
    """
    lignes = cahier.split('\n')
    if len(lignes) > 3 and lignes[3].startswith(LIGNE_EMPREINTE):
        del lignes[3]
    if len(lignes) > 2 and lignes[2].startswith(LIGNE_ETAT):
        del lignes[2]
    texte = lots_md_texte + '\n' + '\n'.join(lignes)
    return 'sha256:' + hashlib.sha256(texte.encode('utf-8')).hexdigest()


def _roles_md(spec: dict) -> list[str]:
    L = []
    for r in _dicts(spec.get('roles')):
        nom = _ligne(r.get('name'), 80)
        if not nom:
            continue
        genre = _ligne(r.get('kind'), 30)
        tete = f'- {_code(nom)}'
        if genre == 'keycloak_group':
            tete += ' (groupe Keycloak)'
        elif genre == 'object_role':
            tete += ' (rôle sur un objet' + (f", porté par {_code(r['on_model'])}" if _ligne(r.get('on_model')) else '') + ')'
        elif genre:
            tete += f' ({genre})'
        inclut = _noms(r.get('implies'))
        if inclut:
            tete += ' ; inclut : ' + ', '.join(_code(x) for x in inclut)
        L += _item(tete, r.get('description'))
    return L


def _modele_md(m: dict) -> list[str]:
    L = [f"### {_ligne(m.get('name'), 80) or 'Modèle sans nom'}", '']
    if _bloc(m.get('description')):
        L += [_para(m.get('description')), '']
    if _ligne(m.get('kind')):
        L.append(f"- Nature : {_ligne(m['kind'], 30)}")
    L += [f'- {_champ(f, True)}' for f in _dicts(m.get('fields'))] or ['- (aucun champ décrit)']
    L += [f'- relation {_relation(r)}' for r in _dicts(m.get('relationships'))]
    L += [f'- contrainte : {_contrainte(c)}' for c in _dicts(m.get('constraints'))]
    access = _objet(m.get('access'))
    L.append(f'- Accès : {_acces_md(access, True)}')
    states = _objet(m.get('states'))
    if states:
        L.append(f"- Cycle de vie : états de {_code(states.get('field')) if _ligne(states.get('field')) else '?'}"
                 + (' : ' + ', '.join(_noms(states.get('values'))) if _noms(states.get('values')) else '')
                 + (f" (initial {_code(states['initial'])})" if _ligne(states.get('initial')) else ''))
        L += [f'  - transition {_transition(tr)}' for tr in _dicts(states.get('transitions'))]
        if _noms(states.get('frozen_in')):
            L.append('  - gelé (plus aucune modification) dans : ' + ', '.join(_code(x) for x in _noms(states.get('frozen_in'))))
    L.append('')
    return L


def _page_md(p: dict, services_par_id: dict) -> list[str]:
    L = [f"### Page {_ligne(p.get('name'), 80) or 'sans nom'}", '']
    lies = [services_par_id[i] for i in _ids(p.get('service_ids')) if i in services_par_id]
    L.append(f"- Route {_code(p.get('route'))}, disposition {_ligne(p.get('layout'), 20) or 'mixed'}"
             + (' ; services : ' + ', '.join(lies) if lies else '') + _acces_page(p, True))
    for c in _dicts(p.get('components')):
        L.append(f'- Composant : {_composant(c, True)}')
        config = _objet(c.get('config'))
        L += [f'  - {_ligne(k, 200)} : {_valeur(config[k])}' for k in sorted(config, key=str)]
    L += [f"- Interaction « {_t(i.get('name'), 120, True)} » ({_ligne(i.get('type'), 30) or 'autre'})"
          + (f" — {_t(i.get('description'), 300, True)}" if _ligne(i.get('description')) else '')
          for i in _dicts(p.get('interactions'))]
    for pl in _dicts(p.get('pipelines')):
        L.append(f"- Pipeline « {_t(pl.get('name'), 120, True)} »"
                 + (f" (déclenché par « {_t(pl['trigger_interaction'], 120, True)} »)" if _ligne(pl.get('trigger_interaction')) else '')
                 + (f" — {_t(pl.get('description'), 300, True)}" if _ligne(pl.get('description')) else '')
                 + (' : ' + ' → '.join(_etape_pipeline(s, True) for s in _dicts(pl.get('steps'))) if _dicts(pl.get('steps')) else ''))
    L.append('')
    return L


def _fond_md(spec: dict) -> list[str]:
    """Tâches de fond, services du lab utilisés et API tierces."""
    L = ['### Tâches de fond', '']
    jobs = [j for j in _dicts(spec.get('jobs')) if _ligne(j.get('name'))]
    L += [f'- {_job(j, True)}' for j in jobs] or ['Aucune.']
    L += ['', '### Services du lab utilisés', '']
    integrations = [i for i in _dicts(spec.get('integrations')) if _ligne(i.get('type'))]
    for i in integrations:
        L += _item(f"- {_code(i['type'])}" + (f" (mode {_ligne(i['mode'], 40)})" if _ligne(i.get('mode')) else ''),
                   i.get('description'))
    if not integrations:
        L.append('Aucun en plus de Keycloak et de la base.')
    L += ['', '### API tierces', '']
    externes = [x for x in _dicts(spec.get('external_apis')) if _ligne(x.get('name'))]
    for x in externes:
        details = []
        if _ligne(x.get('purpose')):
            details.append('usage : ' + _t(x['purpose'], 200, True))
        if _ligne(x.get('auth')):
            details.append('authentification : ' + _ligne(x['auth'], 30))
        if _ligne(x.get('called_from')):
            details.append('appelée depuis : ' + _ligne(x['called_from'], 30))
        L += _item(f"- **{_ligne(x['name'], 200)}**" + (' (' + ' ; '.join(details) + ')' if details else ''),
                   x.get('description'))
    if not externes:
        L.append('Aucune.')
    L += ['', 'Une clé d\'API se règle dans l\'environnement du projet (lab-admin), jamais dans le dépôt ; '
          'une clé propre à un utilisateur est chiffrée au coffre et jamais rendue par l\'API.', '']
    return L


def _extensions_md(spec: dict) -> list[str]:
    ext = _objet(spec.get('extensions'))
    L = []
    data_io = _dicts(ext.get('data_io'))
    if data_io:
        L += ['### Imports et exports', '']
        for d in data_io:
            texte = f"- {_ligne(d.get('direction'), 20) or 'échange'} {_ligne(d.get('format'), 30) or '?'}"
            if _ligne(d.get('model')):
                texte += f" de {_code(d['model'])}"
            if _ligne(d.get('mode')):
                texte += f" (mode {_ligne(d['mode'], 20)})"
            if d.get('async') is True:
                texte += ', en tâche de fond'
            L.append(texte)
        L.append('')
    realtime = [r for r in _dicts(ext.get('realtime')) if _ligne(r.get('name'))]
    if realtime:
        L += ['### Temps réel', '']
        for r in realtime:
            L += _item(f"- « {_t(r['name'], 200, True)} »" + (f" ({_ligne(r['transport'], 20)})" if _ligne(r.get('transport')) else ''),
                       r.get('description'))
        L.append('')
    calculs = [c for c in _dicts(ext.get('computations')) if _ligne(c.get('name'))]
    if calculs:
        L += ['### Calculs', '']
        for c in calculs:
            texte = f"- « {_t(c['name'], 200, True)} »"
            if _noms(c.get('inputs')):
                texte += ' à partir de ' + ', '.join(_code(x) for x in _noms(c.get('inputs')))
            if _ligne(c.get('output')):
                texte += ' → ' + _t(c['output'], 200, True)
            if _ligne(c.get('run')):
                texte += f" ({_ligne(c['run'], 10)})"
            if _ligne(c.get('verification')):
                texte += ' ; vérification : ' + _t(c['verification'], 300, True)
            L.append(texte)
        L.append('')
    notifications = [n for n in _dicts(ext.get('notifications')) if _ligne(n.get('event'))]
    if notifications:
        L += ['### Notifications', '']
        L += [f"- sur {_code(n['event'])} : {_ligne(n.get('channel'), 20) or 'email'}"
              + (' ' + (_a_qui([n['to']]) if ':' in _ligne(n['to']) or _ligne(n['to']) == 'owner' else 'à ' + _code(n['to']))
                 if _ligne(n.get('to')) else '') for n in notifications]
        L.append('')
    return L or ['Aucune.', '']


def cahier_des_charges_md(spec: dict, spec_id, etat_du: str, lots_: list[dict]) -> str:
    app_type = spec.get('app_type')
    nom_projet = _ligne(spec.get('project_name'), 40)
    groupes = _noms(spec.get('required_groups'))
    L = [f"# Cahier des charges — {_ligne(spec.get('name'), 200) or 'Application sans titre'}", '',
         f'{LIGNE_ETAT}{spec_id}, état du {_ligne(etat_du, 80)}.', '',
         'Ce document est généré depuis la spécification ; il se lit avant tout lot de la feuille de route. '
         'En cas d\'écart entre ce texte et une règle du lab (`CLAUDE.md` du projet), la règle du lab l\'emporte.', '',
         '## 1. Objet', '', _para(spec.get('description')) or '(Aucune description saisie.)', '',
         f"- Nom du projet dans le lab : {_code(nom_projet) if nom_projet else 'non choisi'}",
         f"- Type d'app : {_LIBELLE_TYPE.get(app_type, _ligne(app_type, 30) + ' (non constructible par le lab)')}", '']

    L += ['## 2. Accès et cloisonnement', '',
          'Groupes autorisés : ' + (', '.join(_code(g) for g in groupes) if groupes else 'AUCUN — à définir avant toute construction') + '.',
          'Être connecté au lab ne donne accès à rien : deux verrous, à ne jamais retirer.',
          '1. Le flow Keycloak du client refuse à la connexion qui n\'est dans aucun de ces groupes (posé par le lab).',
          '2. L\'API vérifie elle-même le client émetteur du jeton (`azp`) et les groupes (`api/authentication.py` du gabarit).', '']
    roles = _roles_md(spec)
    L += ['### Rôles de l\'app', '']
    L += roles or ['Aucun rôle décrit en plus des groupes autorisés.']
    L.append('')
    publiques = conformite.routes_publiques(spec)
    L.append('### Routes publiques')
    L.append('')
    if publiques:
        for p in publiques:
            L.append(f"- `{_ligne(p['method'], 10)} {_ligne(p['path'], 300)}` — "
                     + (_t(p['reason'], 400, True) or 'JUSTIFICATION ABSENTE : décision à écrire avant de coder'))
    else:
        L.append('Aucune : toute route de l\'API demande un jeton.')
    L.append('')

    L += ['## 3. Règles métier', '']
    regles = [r for r in _dicts(spec.get('business_rules')) if _ligne(r.get('title'))]
    if regles:
        for r in regles:
            L += _item(f"- **{_t(r['title'], 200, True)}**" + _portee_regle(r, True), r.get('description'))
    else:
        L.append('Aucune règle métier saisie.')
    L.append('')

    L += ['## 4. Modèle de données', '']
    modeles = _dicts(spec.get('data_models'))
    if not modeles:
        L.append('Aucun modèle décrit.')
    for m in modeles:
        L += _modele_md(m)
    L += ['Ne jamais modéliser utilisateurs, rôles ou permissions : ils viennent de Keycloak (jeton).', '']

    L += ['## 5. API', '']
    if not conformite.a_un_backend(app_type) and app_type in conformite.TYPES_CONSTRUCTIBLES:
        L += ['Type « Angular seul » : cette app n\'a pas d\'API propre. Les routes ci-dessous sont celles '
              'qu\'elle consomme ailleurs — elles ne sont pas à construire ici.', '']
    groupes_api = _dicts(spec.get('endpoint_groups'))
    if not groupes_api:
        L.append('Aucun endpoint décrit.')
    for g in groupes_api:
        L.append(f"### {_ligne(g.get('name'), 80) or 'Groupe sans nom'}")
        L.append('')
        if _bloc(g.get('description')):
            L += [_para(g.get('description')), '']
        L += [f'- {_endpoint(e, True)}' for e in _dicts(g.get('endpoints'))] or ['- (aucun endpoint décrit)']
        L.append('')

    L += ['## 6. Interface', '']
    if not conformite.a_un_frontend(app_type) and app_type in conformite.TYPES_CONSTRUCTIBLES:
        L += ['Type « Django seul » : cette app n\'a pas d\'interface. Ce qui suit n\'est pas à construire.', '']
    L += ['Identité « Foyer » du lab : aucune couleur en dur (tokens CSS de `src/styles.scss`), navigation verticale, '
          'rupture à 900 px, polices embarquées, cibles tactiles de 44 px.', '']
    groupes_par_id = {g.get('id'): _ligne(g.get('name'), 80) for g in groupes_api}
    services = _dicts(spec.get('services'))
    services_par_id = {s.get('id'): _ligne(s.get('name'), 80) for s in services}
    if services:
        L += ['### Services', '']
        for s in services:
            lies = [groupes_par_id[i] for i in _ids(s.get('endpoint_group_ids')) if i in groupes_par_id]
            L.append(f"- {_code(s.get('name'))}" + (' — ' + ', '.join(lies) if lies else ''))
        L.append('')
    pages = _dicts(spec.get('pages'))
    if not pages:
        L += ['Aucune page décrite.', '']
    for p in pages:
        L += _page_md(p, services_par_id)

    L += ['## 7. Tâches de fond, services du lab et API tierces', '']
    L += _fond_md(spec)

    L += ['## 8. Extensions', '']
    L += _extensions_md(spec)

    L += ['## 9. Fichiers et emails', '']
    stockage = conformite.champs_storage(spec)
    L.append('Fichiers des utilisateurs : ' + (', '.join(_code(c) for c in stockage) + ' — ' if stockage else 'aucun champ fichier. ')
             + 'Tout fichier d\'utilisateur passe par l\'API du service storage du lab ; le modèle garde le chemin. '
               'Jamais de `FileField`, de volume média ni de blob en base.')
    anciens = conformite.champs_fichier_anciens(spec)
    if anciens:
        L.append('⚠ Champs encore de type « file », à convertir : ' + ', '.join(_code(c) for c in anciens) + '.')
    L.append('Emails : ' + ('l\'app en envoie — ' if spec.get('uses_email') else 'l\'app n\'en envoie pas. S\'il en faut un jour : ')
             + '`send_mail` de Django, compte d\'envoi réglé dans lab-admin, rien dans le dépôt.')
    L.append('')

    L += ['## 10. Ce que le lab fournit', '',
          'Le projet est créé par le moteur du lab : dépôt GitHub, squelette, client Keycloak, base PostgreSQL '
          '(un schéma dans la base du propriétaire), chemins Caddy. On ne déploie qu\'un commit poussé, après les tests backend.']
    e = conformite.empreinte(spec)
    L += [f"- Conteneurs : {', '.join(c['name'] for c in e['containers']) or '—'}",
          f"- Adresses : interface {e['paths']['frontend'] or '—'} ; API {e['paths']['api'] or '—'}",
          f"- Base : {'schéma ' + e['database']['schema'] if e['database'] else 'aucune'}", '']

    L += ['## 11. Feuille de route', '',
          'Le Lot 1 (socle du gabarit) est livré par le lab. Lots à réaliser, dans l\'ordre, un seul « en cours » à la fois :', '']
    L += [f"- Lot {lot['number']} — {lot['title']}" for lot in lots_] or ['- (aucun lot : la spécification est vide)']
    L.append('')

    # La ligne d'empreinte suit immédiatement la ligne d'état (contrat I7).
    L.insert(3, f'{LIGNE_EMPREINTE}{empreinte(lots_md(lots_), chr(10).join(L))}.')
    return '\n'.join(L)


# ── Graine : mêmes règles que le moteur ───────────────────────────────────────

def valider_graine(graine) -> list[str]:
    """Les raisons pour lesquelles le moteur refuserait cette graine (vide si aucune)."""
    if not isinstance(graine, dict):
        return ['seed doit être un objet']
    raisons = []
    if set(graine) != {'lots_md', 'cahier_des_charges_md'}:
        raisons.append('seed porte exactement les clés lots_md et cahier_des_charges_md')
    for cle, maxi in (('lots_md', LOTS_MD_MAX), ('cahier_des_charges_md', CAHIER_MD_MAX)):
        v = graine.get(cle)
        if not isinstance(v, str) or not v:
            raisons.append(f'{cle} doit être une chaîne non vide')
            continue
        if '\x00' in v or '\r' in v:
            raisons.append(f'{cle} contient un octet nul ou un retour chariot')
        if len(v) > maxi:
            raisons.append(f'{cle} dépasse {maxi} caractères')
    texte = graine.get('lots_md')
    if isinstance(texte, str) and texte:
        lignes = texte.split('\n')
        non_vides = [ligne for ligne in lignes if ligne.strip()]
        numeros = []
        for ligne in lignes:
            if ligne.startswith('#'):
                m = TITRE_DE_LOT.match(ligne)
                if not m:
                    raisons.append(f'ligne de titre invalide dans lots_md : {ligne[:80]}')
                else:
                    numeros.append(int(m.group(1)))
        if not non_vides or not TITRE_DE_LOT.match(non_vides[0]):
            raisons.append('la première ligne non vide de lots_md doit être un titre de lot')
        if not 1 <= len(numeros) <= LOTS_MAX:
            raisons.append(f'lots_md doit contenir entre 1 et {LOTS_MAX} lots')
        if numeros != list(range(PREMIER_LOT, PREMIER_LOT + len(numeros))):
            raisons.append(f'les lots doivent se suivre à partir de {PREMIER_LOT}')
    return raisons


# ── Tout d'un coup ────────────────────────────────────────────────────────────

def livrables(spec: dict, spec_id, etat_du: str) -> dict:
    """Tout ce qui se déduit d'une spec pour la remettre au lab.

    `spec` : la spec sérialisée ; `etat_du` : sa date de modification, telle
    qu'elle est rendue à l'appelant (elle est citée dans le cahier des charges).
    """
    lots_ = lots(spec)
    feuille = lots_md(lots_)
    cahier = cahier_des_charges_md(spec, spec_id, etat_du, lots_)
    blocages = conformite.blocages(spec)

    trop_gros = [lot for lot in lots_ if lot['tokens'] > LOT_BUDGET_JETONS]
    if trop_gros:
        lot = max(trop_gros, key=lambda x: x['tokens'])
        blocages.append({'code': 'context_budget', 'message':
                         f"Le lot « {lot['title']} » pèserait environ {lot['tokens']} jetons, plus que les "
                         f"{LOT_BUDGET_JETONS} qu'un agent de développement peut tenir : découpez-le "
                         "(groupes d'endpoints, pages ou descriptions plus petits)."})
    elif len(lots_) > LOTS_MAX:
        blocages.append({'code': 'context_budget', 'message':
                         f'La feuille de route compterait {len(lots_)} lots, plus que les {LOTS_MAX} que le lab '
                         'accepte : la spécification est trop vaste pour une seule app.'})
    elif len(feuille) > LOTS_MD_MAX or len(cahier) > CAHIER_MD_MAX:
        blocages.append({'code': 'context_budget', 'message':
                         'La feuille de route ou le cahier des charges générés dépassent la taille que le lab '
                         'accepte : raccourcissez les descriptions ou réduisez la spécification.'})

    return {
        'ready': not blocages,
        'blockers': blocages,
        'create': {'name': spec.get('project_name') or '', 'type': spec.get('app_type'),
                   'required_groups': _noms(spec.get('required_groups'))},
        'lots': lots_,
        'lots_md': feuille,
        'cahier_des_charges_md': cahier,
        'fingerprint': empreinte(feuille, cahier),
        'context': {'cahier_tokens': estimer_jetons(cahier),
                    'largest_lot_tokens': max((lot['tokens'] for lot in lots_), default=0),
                    'lot_budget_tokens': LOT_BUDGET_JETONS},
        'counts': {'data_models': len(_dicts(spec.get('data_models'))),
                   'endpoints': len(conformite.endpoints(spec)),
                   'pages': len(_dicts(spec.get('pages'))),
                   'lots': len(lots_)},
    }
