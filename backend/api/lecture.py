"""Lecture compacte d'une spécification, pour l'IA et le MCP (I3, fonctions pures).

`index_spec` rend un index texte de la spec : une ligne par section, chaque
élément de premier niveau en quelques dizaines de jetons. Les champs des modèles
y sont (un modèle en a besoin presque à chaque tour) ; endpoints, composants et
pipelines y sont résumés et se lisent en détail par `lire_elements`.

Forme (déterministe : ordre `order` puis nom, aucun horodatage) :

    meta: nom-de-projet=stock type=django-angular groupes=[magasin] email=non
    regles: Stock jamais négatif (invariant) · Commande payée figée
    roles: manager(keycloak_group) · editeur(object_role sur TreeShare)
    jobs: Reconstruction(async, POST /api/x/, Projet→Job)
    integrations: storage(user_token) · email
    api_externes: Stripe(app_key)
    extensions: data_io[import csv Produit] · notifications[Commande.payee → email]
    modeles: Produit(nom:string!,prix:decimal!u,photo:storage_file;→Categorie) [owner] {statut: brouillon|payee}
    groupes: Produits[GET,POST /api/produits/ · GET,PATCH,DELETE /api/produits/{id}/]
    services: ProduitService→Produits
    pages: Liste /produits list (table:Produit; 2 interactions, 1 pipeline)

Notation des champs : `!` requis, `u` unique ; relations `→` FK, `⇄` M2M,
`–` O2O ; `[portée]` d'accès (`[accès ?]` si non décrit) ; `{champ: états}`.
Une section vide est rendue `aucun(e)` pour que l'IA sache qu'elle est vide.
"""
import json
import re

from . import patching
from .budget import estimer_jetons

SECTIONS = ('meta', 'regles', 'roles', 'jobs', 'integrations', 'api_externes', 'extensions',
            'modeles', 'groupes', 'services', 'pages')

# Au-delà, `lire_elements` refuse : l'appelant demande moins d'éléments.
LIRE_MAX_JETONS = 6_000

_CONTROLES = re.compile(r'[\x00-\x1f\x7f-\x9f  ]+')


def _t(v, maxi=80) -> str:
    texte = _CONTROLES.sub(' ', v if isinstance(v, str) else ('' if v is None else str(v))).strip()
    texte = re.sub(r' {2,}', ' ', texte)
    return texte if len(texte) <= maxi else texte[:maxi - 1] + '…'


def _l(v):
    return v if isinstance(v, list) else []


def _d(v):
    return [x for x in _l(v) if isinstance(x, dict)]


def _tri(elements, cle='name'):
    def k(e):
        o = e.get('order')
        return (o if isinstance(o, int) and not isinstance(o, bool) else 0, str(e.get(cle) or ''))
    return sorted(elements, key=k)


_FLECHE = {'FK': '→', 'M2M': '⇄', 'O2O': '–'}


def _modele(m) -> str:
    champs = []
    for f in _d(m.get('fields')):
        marque = ('!' if f.get('required') is not False else '') + ('u' if f.get('unique') else '')
        champs.append(f"{_t(f.get('name'), 40)}:{_t(f.get('type'), 20) or 'string'}{marque}")
    relations = [f"{_FLECHE.get(r.get('rel_type'), '→')}{_t(r.get('to_model'), 40)}" for r in _d(m.get('relationships'))]
    texte = f"{_t(m.get('name'))}({','.join(champs)}" + (';' + ','.join(relations) if relations else '') + ')'
    if m.get('kind') not in (None, '', 'entity'):
        texte += f" <{_t(m['kind'], 12)}>"
    acces = m.get('access') if isinstance(m.get('access'), dict) else {}
    texte += f" [{_t(acces.get('scope'), 12) or 'accès ?'}]" if acces else ' [accès ?]'
    etats = m.get('states') if isinstance(m.get('states'), dict) else {}
    if etats.get('values'):
        texte += f" {{{_t(etats.get('field'), 30) or 'état'}: {'|'.join(_t(v, 20) for v in _l(etats['values']))}}}"
    return texte


def _groupe(g) -> str:
    par_chemin = {}
    for e in _d(g.get('endpoints')):
        par_chemin.setdefault(_t(e.get('path'), 120), []).append(_t(e.get('method'), 8))
    routes = [f"{','.join(m)} {chemin}" for chemin, m in par_chemin.items()]
    return f"{_t(g.get('name'))}[{' · '.join(routes)}]"


def _page(p) -> str:
    comps = [f"{_t(c.get('type'), 20) or 'composant'}" + (f":{_t(c['linked_model'], 40)}" if _t(c.get('linked_model')) else '')
             for c in _d(p.get('components'))]
    n_i, n_p = len(_d(p.get('interactions'))), len(_d(p.get('pipelines')))
    morceaux = [', '.join(comps)] if comps else []
    if n_i:
        morceaux.append(f"{n_i} interaction{'s' if n_i > 1 else ''}")
    if n_p:
        morceaux.append(f"{n_p} pipeline{'s' if n_p > 1 else ''}")
    texte = f"{_t(p.get('name'))} {_t(p.get('route'), 80)} {_t(p.get('layout'), 12) or 'mixed'}"
    if p.get('public') is True:
        texte += ' public'
    if _l(p.get('required_roles')):
        texte += ' roles=' + ','.join(_t(r, 30) for r in p['required_roles'])
    return texte + (f" ({'; '.join(morceaux)})" if morceaux else '')


def _ligne(section, elements) -> str:
    return f"{section}: " + (' · '.join(elements) if elements else 'aucun')


def index_spec(spec: dict) -> str:
    """Index texte déterministe de la spec, une ligne par section."""
    etat = patching._vers_noms(spec)
    meta = (f"meta: nom-de-projet={_t(etat['project_name'], 40) or '?'} type={etat['app_type']} "
            f"groupes=[{','.join(_t(g, 40) for g in etat['required_groups'])}] "
            f"email={'oui' if etat['uses_email'] else 'non'} titre={_t(etat['name'], 60)}")
    regles = [_t(r['title'], 80) + (f" ({_t(r['kind'], 12)})" if _t(r.get('kind')) else '') for r in etat['business_rules']]
    roles = [f"{_t(r.get('name'), 40)}({_t(r.get('kind'), 16) or '?'}"
             + (f" sur {_t(r['on_model'], 40)}" if _t(r.get('on_model')) else '') + ')' for r in _tri(etat['roles'])]
    jobs = [f"{_t(j.get('name'), 40)}(" + ', '.join(x for x in (
        _t(j.get('kind'), 12) or '?', _t(j.get('trigger'), 60),
        '→'.join(_t(j.get(c), 40) for c in ('input_model', 'tracked_by') if _t(j.get(c)))) if x) + ')'
        for j in _tri(etat['jobs'])]
    integrations = [_t(i.get('type'), 20) + (f"({_t(i['mode'], 20)})" if _t(i.get('mode')) else '')
                    for i in _tri(etat['integrations'], 'type')]
    externes = [f"{_t(a.get('name'), 40)}({_t(a.get('auth'), 12) or '?'})" for a in _tri(etat['external_apis'])]
    extensions = [f"{liste}[{', '.join(_t(patching.cle_extension(liste, x), 60) for x in _d(etat['extensions'].get(liste)))}]"
                  for liste in sorted(etat['extensions']) if _d(etat['extensions'].get(liste))]
    groupes_de = {s['name']: s['endpoint_group_names'] for s in etat['services']}
    lignes = [
        meta,
        _ligne('regles', regles),
        _ligne('roles', roles),
        _ligne('jobs', jobs),
        _ligne('integrations', integrations),
        _ligne('api_externes', externes),
        _ligne('extensions', extensions),
        _ligne('modeles', [_modele(m) for m in _tri(etat['data_models'])]),
        _ligne('groupes', [_groupe(g) for g in _tri(etat['endpoint_groups'])]),
        _ligne('services', [f"{_t(s['name'])}→{','.join(_t(n) for n in groupes_de[s['name']]) or '∅'}"
                            for s in _tri(etat['services'])]),
        _ligne('pages', [_page(p) for p in _tri(etat['pages'])]),
    ]
    return '\n'.join(lignes)


def _propre(v):
    """Sans identifiants, sans rang, sans valeurs vides (False et 0 restent : ce sont des valeurs)."""
    if isinstance(v, dict):
        sortie = {}
        for k, x in v.items():
            if k in ('id', 'order'):
                continue
            x = _propre(x)
            if x in (None, '', [], {}):
                continue
            sortie[k] = x
        return sortie
    if isinstance(v, list):
        return [x for x in (_propre(y) for y in v) if x not in (None, '', [], {})]
    return v


def lire_elements(spec: dict, section: str, noms: list[str]) -> dict:
    """Le détail de quelques éléments d'une section : {"elements", "inconnus"},
    ou {"erreur": "trop_gros", "message"} au-delà de 6 000 jetons estimés."""
    if section not in SECTIONS:
        return {'erreur': 'section_inconnue',
                'message': f'section « {section} » inconnue : ' + ', '.join(SECTIONS)}
    etat = patching._vers_noms(spec)
    if section == 'meta':
        candidats = [('meta', {k: etat[k] for k in ('name', 'project_name', 'description', 'app_type',
                                                     'uses_email', 'required_groups')})]
    elif section == 'regles':
        candidats = [(r['title'], r) for r in etat['business_rules']]
    elif section == 'extensions':
        candidats = [(f'{liste}:{patching.cle_extension(liste, x)}', {'liste': liste, **x})
                     for liste in sorted(etat['extensions']) for x in _d(etat['extensions'][liste])]
    else:
        source, cle = {'roles': ('roles', 'name'), 'jobs': ('jobs', 'name'), 'integrations': ('integrations', 'type'),
                       'api_externes': ('external_apis', 'name'), 'modeles': ('data_models', 'name'),
                       'groupes': ('endpoint_groups', 'name'), 'services': ('services', 'name'),
                       'pages': ('pages', 'name')}[section]
        candidats = [(x.get(cle), x) for x in etat[source]]
    noms = [n for n in (noms or []) if isinstance(n, str)]
    if noms:
        par_nom = {n: x for n, x in candidats}
        elements = [_propre(par_nom[n]) for n in noms if n in par_nom]
        inconnus = [n for n in noms if n not in par_nom]
    else:
        elements, inconnus = [_propre(x) for _, x in candidats], []
    taille = estimer_jetons(json.dumps(elements, ensure_ascii=False))
    if taille > LIRE_MAX_JETONS:
        return {'erreur': 'trop_gros',
                'message': f'Environ {taille} jetons, plus que les {LIRE_MAX_JETONS} permis en une lecture : '
                           'demande moins d\'éléments (noms précis) à la fois.'}
    return {'elements': elements, 'inconnus': inconnus}
