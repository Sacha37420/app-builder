"""Application d'un patch IA à une spécification — côté serveur.

Un patch ne décrit que ce qui change. Les règles, les mêmes pour toute la spec :

- un élément est retrouvé par son nom (un endpoint par méthode + chemin) ;
- ce que le patch ne cite pas reste en place : un champ, un endpoint, une
  interaction ou un pipeline ajouté n'efface pas ses voisins, et une clé
  absente d'un élément cité garde sa valeur ;
- on ne retire que sur demande explicite (`remove_*`), on ne renomme que par
  `rename_from` ;
- une liste de liens (`endpoint_group_names`, `service_names`), les
  `components` d'une page et les `steps` d'un pipeline ou d'un endpoint sont
  des listes complètes : présentes, elles remplacent ; absentes, rien ne bouge ;
- un patch qui introduit une référence vers un élément inexistant est refusé
  en entier, la spec n'est pas touchée.

`fusionner` est une fonction pure (spec sérialisée → spec sérialisée) ;
`appliquer` et `annuler` l'enregistrent, avec un instantané pour revenir en
arrière.
"""
import json
from copy import deepcopy

from django.db import transaction
from django.utils import timezone

from .models import AppSpec, PatchApplication
from .serializers import AppSpecSerializer


class PatchRefuse(Exception):
    """Le patch ne peut pas être appliqué ; `erreurs` dit pourquoi, ligne par ligne."""

    def __init__(self, erreurs):
        self.erreurs = list(erreurs)
        super().__init__(' ; '.join(self.erreurs))


MODES = ('merge', 'replace')
# Nombre d'applications (donc d'instantanés) gardées par spécification.
HISTORIQUE_MAX = 20

_COLLECTIONS = ('data_models', 'endpoint_groups', 'services', 'pages')
_CLES_SPEC = ('name', 'project_name', 'description', 'app_type', 'required_groups',
              'business_rules', 'uses_email') + _COLLECTIONS

_TYPES_DE_CHAMP = {
    'string': 'string', 'str': 'string', 'char': 'string', 'varchar': 'string',
    'url': 'string', 'email': 'string', 'slug': 'string',
    'text': 'text', 'longtext': 'text', 'long_text': 'text',
    'int': 'int', 'integer': 'int',
    'decimal': 'decimal', 'float': 'decimal', 'double': 'decimal', 'number': 'decimal',
    'bool': 'bool', 'boolean': 'bool',
    'datetime': 'datetime', 'date': 'datetime', 'timestamp': 'datetime',
    'json': 'json', 'jsonb': 'json', 'dict': 'json', 'object': 'json', 'array': 'json',
    # Un fichier d'utilisateur va dans le service `storage` du lab : le modèle
    # n'en garde que le chemin. L'ancien type `file` n'entre plus par un patch.
    'storage_file': 'storage_file', 'storage': 'storage_file', 'storage_path': 'storage_file',
    'file': 'storage_file', 'image': 'storage_file', 'upload': 'storage_file',
    'photo': 'storage_file', 'document': 'storage_file',
}
_OPERATIONS = {
    'list': 'list', 'index': 'list', 'getall': 'list', 'get_all': 'list',
    'create': 'create', 'post': 'create', 'add': 'create',
    'retrieve': 'retrieve', 'get': 'retrieve', 'detail': 'retrieve', 'read': 'retrieve',
    'update': 'update', 'put': 'update', 'replace': 'update',
    'partial_update': 'partial_update', 'patch': 'partial_update',
    'delete': 'delete', 'destroy': 'delete', 'remove': 'delete',
    'custom': 'custom',
}
_RELATIONS = {
    'fk': 'FK', 'foreignkey': 'FK', 'manytoone': 'FK',
    'm2m': 'M2M', 'manytomany': 'M2M',
    'o2o': 'O2O', 'onetoone': 'O2O',
}
_METHODES = ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')
_ON_DELETE = ('CASCADE', 'SET_NULL', 'PROTECT', 'DO_NOTHING')


# ── Normalisation : ne garder que ce que le patch dit, sous une forme sûre ────

def _liste(v):
    return v if isinstance(v, list) else []


def _dicts(v):
    return [x for x in _liste(v) if isinstance(x, dict)]


def _texte(v, defaut=''):
    return v.strip() if isinstance(v, str) else defaut


def _noms(v):
    vus, noms = set(), []
    for n in (_texte(x) for x in _liste(v)):
        if n and n not in vus:
            vus.add(n)
            noms.append(n)
    return noms


def _premier(d, *cles):
    """Valeur de la première clé présente (les IA varient sur les noms de clés)."""
    for c in cles:
        if c in d:
            return d[c]
    return None


def _a(d, *cles):
    return any(c in d for c in cles)


def _communs(brut, propre, texte=('description',)):
    for c in texte:
        if c in brut:
            propre[c] = _texte(brut[c])
    if isinstance(brut.get('order'), int) and not isinstance(brut['order'], bool) and brut['order'] >= 0:
        propre['order'] = brut['order']
    if _texte(brut.get('rename_from')):
        propre['rename_from'] = _texte(brut['rename_from'])
    return propre


def _champ(f):
    c = {'name': _texte(f.get('name'))}
    if 'type' in f:
        c['type'] = _TYPES_DE_CHAMP.get(_texte(f['type']).lower(), 'string')
    if 'required' in f:
        c['required'] = f['required'] is not False
    if 'unique' in f:
        c['unique'] = bool(f['unique'])
    if isinstance(f.get('max_length'), int) and not isinstance(f['max_length'], bool):
        c['max_length'] = f['max_length']
    if f.get('default') is not None:
        c['default'] = str(f['default'])
    if _texte(f.get('help_text')):
        c['help_text'] = _texte(f['help_text'])
    return c


def _relation(r):
    rel = {'name': _texte(r.get('name'))}
    if 'rel_type' in r:
        cle = _texte(r['rel_type']).lower().replace(' ', '').replace('_', '').replace('-', '')
        rel['rel_type'] = _RELATIONS.get(cle, 'FK')
    if _a(r, 'to_model', 'target', 'model'):
        rel['to_model'] = _texte(_premier(r, 'to_model', 'target', 'model'))
    if 'related_name' in r:
        rel['related_name'] = _texte(r['related_name'])
    if _a(r, 'on_delete', 'on_delete_action'):
        od = _texte(_premier(r, 'on_delete', 'on_delete_action')).upper()
        rel['on_delete'] = od if od in _ON_DELETE else 'CASCADE'
    return rel


def _etapes(v, cles):
    etapes = []
    for st in _dicts(v):
        e = {'label': _texte(st.get('label')), 'type': _texte(st.get('type')) or 'trigger'}
        for c in cles:
            if _texte(st.get(c)):
                e[c] = _texte(st[c])
        etapes.append(e)
    return etapes


def _cle_endpoint(v):
    """('GET', '/api/x/') depuis {"method", "path"} ou depuis "GET /api/x/"."""
    if isinstance(v, dict):
        methode, chemin = _texte(v.get('method')).upper(), _texte(v.get('path'))
    else:
        methode, _, chemin = _texte(v).partition(' ')
        methode, chemin = methode.upper(), chemin.strip()
    return (methode, chemin) if methode and chemin else None


def _endpoint(e):
    methode = _texte(e.get('method')).upper()
    ep = _communs(e, {'method': methode if methode in _METHODES else 'GET', 'path': _texte(e.get('path'))})
    ep.pop('rename_from', None)
    if 'operation' in e:
        op = _texte(e['operation']).lower().replace(' ', '_').replace('-', '_')
        ep['operation'] = _OPERATIONS.get(op, 'custom')
    if _a(e, 'linked_model_name', 'model', 'linked_model'):
        ep['linked_model_name'] = _texte(_premier(e, 'linked_model_name', 'model', 'linked_model'))
    if 'auth_required' in e:
        ep['auth_required'] = e['auth_required'] is not False
    if 'public_reason' in e:
        ep['public_reason'] = _texte(e['public_reason'])
    if 'required_roles' in e:
        ep['required_roles'] = _noms(e['required_roles'])
    for c in ('request_schema', 'response_schema'):
        if c in e:
            ep[c] = e[c] if isinstance(e[c], (dict, list)) else None
    if 'query_params' in e:
        ep['query_params'] = _liste(e['query_params'])
    if 'steps' in e:
        ep['steps'] = _etapes(e['steps'], ('description',))
    return ep


def _modele(m):
    mod = _communs(m, {'name': _texte(m.get('name'))})
    if 'fields' in m:
        mod['fields'] = [c for c in map(_champ, _dicts(m['fields'])) if c['name']]
    if 'relationships' in m:
        mod['relationships'] = [r for r in map(_relation, _dicts(m['relationships'])) if r['name']]
    mod['remove_fields'] = _noms(m.get('remove_fields'))
    mod['remove_relationships'] = _noms(m.get('remove_relationships'))
    return mod


def _groupe(g):
    grp = _communs(g, {'name': _texte(g.get('name'))})
    if 'endpoints' in g:
        grp['endpoints'] = [e for e in map(_endpoint, _dicts(g['endpoints'])) if e['path']]
    grp['remove_endpoints'] = [c for c in map(_cle_endpoint, _liste(g.get('remove_endpoints'))) if c]
    return grp


def _service(s):
    svc = _communs(s, {'name': _texte(s.get('name'))}, texte=())
    if _a(s, 'endpoint_group_names', 'groups', 'endpoint_groups'):
        svc['endpoint_group_names'] = _noms(_premier(s, 'endpoint_group_names', 'groups', 'endpoint_groups'))
    return svc


def _interaction(i):
    inter = _communs(i, {'name': _texte(i.get('name'))})
    inter.pop('rename_from', None)
    if 'type' in i:
        inter['type'] = _texte(i['type']) or 'other'
    return inter


def _pipeline(p):
    pipe = _communs(p, {'name': _texte(p.get('name'))})
    pipe.pop('rename_from', None)
    if 'trigger_interaction' in p:
        pipe['trigger_interaction'] = _texte(p['trigger_interaction'])
    if 'steps' in p:
        pipe['steps'] = _etapes(p['steps'], ('description', 'service_name', 'service_method', 'data_flow', 'on_error'))
    return pipe


def _page(p):
    page = _communs(p, {'name': _texte(p.get('name'))}, texte=())
    if _texte(p.get('route')):
        page['route'] = _texte(p['route'])
    if _texte(p.get('layout')):
        page['layout'] = _texte(p['layout'])
    if _a(p, 'service_names', 'services'):
        page['service_names'] = _noms(_premier(p, 'service_names', 'services'))
    if 'components' in p:
        page['components'] = _dicts(p['components'])
    if 'interactions' in p:
        page['interactions'] = [i for i in map(_interaction, _dicts(p['interactions'])) if i['name']]
    if 'pipelines' in p:
        page['pipelines'] = [pl for pl in map(_pipeline, _dicts(p['pipelines'])) if pl['name']]
    page['remove_interactions'] = _noms(p.get('remove_interactions'))
    page['remove_pipelines'] = _noms(p.get('remove_pipelines'))
    return page


def _regle(r):
    regle = {'title': _texte(_premier(r, 'title', 'name'))[:200]}
    if _a(r, 'description', 'rule', 'text'):
        regle['description'] = _texte(_premier(r, 'description', 'rule', 'text'))
    return regle


def normaliser(brut) -> dict:
    """Patch brut de l'IA → patch sûr. Tolère les clés alternatives, écarte les
    éléments sans nom, et ne garde d'un élément que les clés réellement fournies."""
    if not isinstance(brut, dict):
        raise PatchRefuse(['le patch doit être un objet JSON'])
    meta_brut = brut.get('set_meta') if isinstance(brut.get('set_meta'), dict) else {}
    meta = {}
    for c in ('name', 'description'):
        if _texte(meta_brut.get(c)):
            meta[c] = _texte(meta_brut[c])
    if _texte(meta_brut.get('project_name')):
        meta['project_name'] = _texte(meta_brut['project_name']).lower()
    if isinstance(meta_brut.get('uses_email'), bool):
        meta['uses_email'] = meta_brut['uses_email']
    meta['required_groups'] = _noms(meta_brut.get('required_groups'))
    meta['remove_required_groups'] = _noms(meta_brut.get('remove_required_groups'))
    return {
        'set_meta': meta,
        'business_rules': [r for r in map(_regle, _dicts(_premier(brut, 'business_rules', 'rules'))) if r['title']],
        'remove_business_rules': _noms(brut.get('remove_business_rules')),
        'data_models': [m for m in map(_modele, _dicts(_premier(brut, 'data_models', 'models', 'data-models'))) if m['name']],
        'endpoint_groups': [g for g in map(_groupe, _dicts(_premier(brut, 'endpoint_groups', 'groups', 'endpoints'))) if g['name']],
        'services': [s for s in map(_service, _dicts(brut.get('services'))) if s['name']],
        'pages': [p for p in map(_page, _dicts(brut.get('pages'))) if p['name']],
        'remove_models': _noms(_premier(brut, 'remove_models', 'delete_models')),
        'remove_endpoint_groups': _noms(_premier(brut, 'remove_endpoint_groups', 'delete_groups')),
        'remove_services': _noms(_premier(brut, 'remove_services', 'delete_services')),
        'remove_pages': _noms(_premier(brut, 'remove_pages', 'delete_pages')),
    }


def resume(brut) -> str:
    """Une ligne lisible : ce que le patch ajoute, modifie ou retire."""
    try:
        p = normaliser(brut)
    except PatchRefuse:
        return 'patch illisible'
    parts = []
    meta = p['set_meta']
    if meta.get('name'):
        parts.append(f'nom → « {meta["name"]} »')
    if meta['required_groups']:
        parts.append('groupes requis → ' + ', '.join(meta['required_groups']))
    if meta['remove_required_groups']:
        parts.append('groupes retirés → ' + ', '.join(meta['remove_required_groups']))
    if meta.get('project_name'):
        parts.append(f'nom de projet → {meta["project_name"]}')
    if p['business_rules']:
        parts.append(f'{len(p["business_rules"])} règle(s) métier')
    if p['remove_business_rules']:
        parts.append(f'−{len(p["remove_business_rules"])} règle(s) métier')
    for cle, retrait, libelle in (('data_models', 'remove_models', 'modèle(s)'),
                                  ('endpoint_groups', 'remove_endpoint_groups', 'groupe(s)'),
                                  ('services', 'remove_services', 'service(s)'),
                                  ('pages', 'remove_pages', 'page(s)')):
        if p[cle]:
            texte = f'{len(p[cle])} {libelle}'
            if cle == 'endpoint_groups':
                texte += f' / {sum(len(g.get("endpoints", [])) for g in p[cle])} endpoint(s)'
            parts.append(texte)
        if p[retrait]:
            parts.append(f'−{len(p[retrait])} {libelle}')
    return ' · '.join(parts) or 'patch vide'


# ── Fusion ────────────────────────────────────────────────────────────────────

def _trouver(elements, nom):
    return next((e for e in elements if e.get('name') == nom), None)


def _vers_noms(spec: dict) -> dict:
    """Spec sérialisée (liens par identifiant) → état de travail (liens par nom)."""
    spec = spec if isinstance(spec, dict) else {}
    etat = {
        'name': _texte(spec.get('name')) or 'Mon Application',
        'description': _texte(spec.get('description')),
        'app_type': _texte(spec.get('app_type')) or 'django-angular',
        'required_groups': _noms(spec.get('required_groups')),
        'project_name': _texte(spec.get('project_name')),
        'business_rules': [{'title': _texte(r.get('title')), 'description': _texte(r.get('description'))}
                           for r in _dicts(spec.get('business_rules')) if _texte(r.get('title'))],
        'uses_email': spec.get('uses_email') is True,
    }
    for c in _COLLECTIONS:
        etat[c] = deepcopy(_dicts(spec.get(c)))
    groupes = {g.get('id'): g.get('name') for g in etat['endpoint_groups'] if g.get('id') is not None}
    for g in etat['endpoint_groups']:
        g['endpoints'] = _dicts(g.get('endpoints'))
    for m in etat['data_models']:
        m['fields'], m['relationships'] = _dicts(m.get('fields')), _dicts(m.get('relationships'))
    for s in etat['services']:
        s['endpoint_group_names'] = [groupes[i] for i in _liste(s.pop('endpoint_group_ids', [])) if i in groupes]
    services = {s.get('id'): s.get('name') for s in etat['services'] if s.get('id') is not None}
    for p in etat['pages']:
        p['service_names'] = [services[i] for i in _liste(p.pop('service_ids', [])) if i in services]
        for c in ('components', 'interactions', 'pipelines'):
            p[c] = _dicts(p.get(c))
    return etat


def _vers_ids(etat: dict) -> dict:
    """État de travail → spec sérialisée. Un élément nouveau reçoit un
    identifiant temporaire négatif, que le sérialiseur résout à l'écriture."""
    def identifier(elements):
        libre = min([e['id'] for e in elements if isinstance(e.get('id'), int)] + [0]) - 1
        for e in elements:
            if not isinstance(e.get('id'), int):
                e['id'], libre = libre, libre - 1
        return {e['name']: e['id'] for e in elements}

    groupes = identifier(etat['endpoint_groups'])
    services = identifier(etat['services'])
    for s in etat['services']:
        s['endpoint_group_ids'] = [groupes[n] for n in s.pop('endpoint_group_names') if n in groupes]
    for p in etat['pages']:
        p['service_ids'] = [services[n] for n in p.pop('service_names') if n in services]
    return etat


def _orphelins(etat: dict) -> set:
    """Références vers un élément absent de la spec, en phrases."""
    modeles = {m['name'] for m in etat['data_models']}
    groupes = {g['name'] for g in etat['endpoint_groups']}
    services = {s['name'] for s in etat['services']}
    manques = set()
    for m in etat['data_models']:
        for r in m['relationships']:
            if r.get('to_model') not in modeles:
                manques.add(f"la relation « {m['name']}.{r.get('name')} » vise le modèle « {r.get('to_model')} », absent de la spec")
    for g in etat['endpoint_groups']:
        for e in g['endpoints']:
            if e.get('linked_model_name') and e['linked_model_name'] not in modeles:
                manques.add(f"l'endpoint {e.get('method')} {e.get('path')} vise le modèle « {e['linked_model_name']} », absent de la spec")
    for s in etat['services']:
        for n in s['endpoint_group_names']:
            if n not in groupes:
                manques.add(f"le service « {s['name']} » vise le groupe d'endpoints « {n} », absent de la spec")
    for p in etat['pages']:
        for n in p['service_names']:
            if n not in services:
                manques.add(f"la page « {p['name']} » vise le service « {n} », absent de la spec")
        for c in p['components']:
            if c.get('linked_model') and c['linked_model'] not in modeles:
                manques.add(f"un composant de la page « {p['name']} » vise le modèle « {c['linked_model']} », absent de la spec")
        interactions = {i.get('name') for i in p['interactions']}
        for pl in p['pipelines']:
            if pl.get('trigger_interaction') and pl['trigger_interaction'] not in interactions:
                manques.add(f"le pipeline « {pl.get('name')} » de la page « {p['name']} » est déclenché par "
                            f"l'interaction « {pl['trigger_interaction']} », absente de cette page")
            for st in _dicts(pl.get('steps')):
                if st.get('service_name') and st['service_name'] not in services:
                    manques.add(f"une étape du pipeline « {pl.get('name')} » de la page « {p['name']} » appelle "
                                f"le service « {st['service_name']} », absent de la spec")
    return manques


def _fusion_par_cle(existants, apports, cle, defauts):
    """Chaque apport complète l'élément de même clé, ou s'ajoute en fin de liste."""
    for apport in apports:
        cible = next((e for e in existants if cle(e) == cle(apport)), None)
        if cible is None:
            cible = {**deepcopy(defauts), 'order': len(existants)}
            existants.append(cible)
        cible.update(apport)


def _renommer(elements, apport, genre, erreurs, propager=None):
    ancien, nouveau = apport.pop('rename_from', None), apport['name']
    if not ancien or ancien == nouveau:
        return
    cible = _trouver(elements, ancien)
    if cible is None:
        return  # déjà renommé, ou jamais existé : le patch vaut alors pour `nouveau`
    if _trouver(elements, nouveau) is not None:
        erreurs.append(f'impossible de renommer {genre} « {ancien} » en « {nouveau} » : ce nom est déjà pris')
        return
    cible['name'] = nouveau
    if propager:
        propager(ancien, nouveau)


def _retirer(elements, noms):
    elements[:] = [e for e in elements if e.get('name') not in noms]


_DEFAUT_CHAMP = {'type': 'string', 'required': True, 'unique': False}
_DEFAUT_RELATION = {'rel_type': 'FK', 'to_model': '', 'related_name': '', 'on_delete': 'CASCADE'}
_DEFAUT_ENDPOINT = {'description': '', 'operation': 'custom', 'linked_model_name': '', 'auth_required': True,
                    'public_reason': '',
                    'required_roles': [], 'request_schema': None, 'response_schema': None,
                    'query_params': [], 'steps': []}
_DEFAUT_INTERACTION = {'type': 'other', 'description': ''}
_DEFAUT_PIPELINE = {'description': '', 'trigger_interaction': '', 'steps': []}


def fusionner(spec: dict, patch_brut, mode: str = 'merge') -> dict:
    """Rend la spec sérialisée après application du patch. Ne modifie pas `spec`.
    Lève `PatchRefuse` si le patch est illisible ou incohérent."""
    if mode not in MODES:
        raise PatchRefuse([f'mode inconnu : {mode}'])
    patch = normaliser(patch_brut)
    etat = _vers_noms(spec)
    if mode == 'replace':
        for c in _COLLECTIONS:
            etat[c] = []
    avant = _orphelins(etat)
    erreurs = []

    # ── Métadonnées ───────────────────────────────────────────────────────────
    meta = patch['set_meta']
    for c in ('name', 'description', 'project_name', 'uses_email'):
        if c in meta:
            etat[c] = meta[c]
    # Règles métier : retrouvées par leur titre, comme tout le reste par son nom.
    etat['business_rules'] = [r for r in etat['business_rules'] if r['title'] not in patch['remove_business_rules']]
    for apport in patch['business_rules']:
        regle = next((r for r in etat['business_rules'] if r['title'] == apport['title']), None)
        if regle is None:
            regle = {'title': apport['title'], 'description': ''}
            etat['business_rules'].append(regle)
        regle.update(apport)
    # Union, jamais remplacement : ajouter un groupe ne fait pas disparaître
    # ceux déjà validés. Un groupe ne sort que par `remove_required_groups`.
    etat['required_groups'] = [g for g in _noms(etat['required_groups'] + meta['required_groups'])
                               if g not in meta['remove_required_groups']]

    # ── Modèles ───────────────────────────────────────────────────────────────
    def propager_modele(ancien, nouveau):
        for m in etat['data_models']:
            for r in m['relationships']:
                if r.get('to_model') == ancien:
                    r['to_model'] = nouveau
        for g in etat['endpoint_groups']:
            for e in g['endpoints']:
                if e.get('linked_model_name') == ancien:
                    e['linked_model_name'] = nouveau
        for p in etat['pages']:
            for c in p['components']:
                if c.get('linked_model') == ancien:
                    c['linked_model'] = nouveau

    _retirer(etat['data_models'], patch['remove_models'])
    for apport in patch['data_models']:
        _renommer(etat['data_models'], apport, 'le modèle', erreurs, propager_modele)
        modele = _trouver(etat['data_models'], apport['name'])
        if modele is None:
            modele = {'name': apport['name'], 'description': '', 'fields': [], 'relationships': [],
                      'order': len(etat['data_models'])}
            etat['data_models'].append(modele)
        for c in ('description', 'order'):
            if c in apport:
                modele[c] = apport[c]
        _retirer(modele['fields'], apport['remove_fields'])
        _retirer(modele['relationships'], apport['remove_relationships'])
        nom = lambda x: x.get('name')  # noqa: E731
        _fusion_par_cle(modele['fields'], apport.get('fields', []), nom, _DEFAUT_CHAMP)
        _fusion_par_cle(modele['relationships'], apport.get('relationships', []), nom, _DEFAUT_RELATION)
        for liste in (modele['fields'], modele['relationships']):
            for element in liste:
                element.pop('order', None)

    # ── Groupes d'endpoints ───────────────────────────────────────────────────
    def propager_groupe(ancien, nouveau):
        for s in etat['services']:
            s['endpoint_group_names'] = [nouveau if n == ancien else n for n in s['endpoint_group_names']]

    _retirer(etat['endpoint_groups'], patch['remove_endpoint_groups'])
    for s in etat['services']:
        s['endpoint_group_names'] = [n for n in s['endpoint_group_names'] if n not in patch['remove_endpoint_groups']]
    for apport in patch['endpoint_groups']:
        _renommer(etat['endpoint_groups'], apport, "le groupe d'endpoints", erreurs, propager_groupe)
        groupe = _trouver(etat['endpoint_groups'], apport['name'])
        if groupe is None:
            groupe = {'name': apport['name'], 'description': '', 'endpoints': [],
                      'order': len(etat['endpoint_groups'])}
            etat['endpoint_groups'].append(groupe)
        for c in ('description', 'order'):
            if c in apport:
                groupe[c] = apport[c]
        cle = lambda e: (e.get('method'), e.get('path'))  # noqa: E731
        groupe['endpoints'] = [e for e in groupe['endpoints'] if cle(e) not in apport['remove_endpoints']]
        _fusion_par_cle(groupe['endpoints'], apport.get('endpoints', []), cle, _DEFAUT_ENDPOINT)

    # ── Services ──────────────────────────────────────────────────────────────
    def propager_service(ancien, nouveau):
        for p in etat['pages']:
            p['service_names'] = [nouveau if n == ancien else n for n in p['service_names']]
            for pl in p['pipelines']:
                for st in _dicts(pl.get('steps')):
                    if st.get('service_name') == ancien:
                        st['service_name'] = nouveau

    _retirer(etat['services'], patch['remove_services'])
    for p in etat['pages']:
        p['service_names'] = [n for n in p['service_names'] if n not in patch['remove_services']]
    for apport in patch['services']:
        _renommer(etat['services'], apport, 'le service', erreurs, propager_service)
        service = _trouver(etat['services'], apport['name'])
        if service is None:
            service = {'name': apport['name'], 'endpoint_group_names': [], 'order': len(etat['services'])}
            etat['services'].append(service)
        for c in ('order', 'endpoint_group_names'):
            if c in apport:
                service[c] = apport[c]

    # ── Pages ─────────────────────────────────────────────────────────────────
    _retirer(etat['pages'], patch['remove_pages'])
    for apport in patch['pages']:
        _renommer(etat['pages'], apport, 'la page', erreurs)
        page = _trouver(etat['pages'], apport['name'])
        if page is None:
            page = {'name': apport['name'], 'route': '/' + '-'.join(apport['name'].lower().split()),
                    'layout': 'mixed', 'components': [], 'service_names': [], 'interactions': [],
                    'pipelines': [], 'order': len(etat['pages'])}
            etat['pages'].append(page)
        for c in ('route', 'layout', 'order', 'service_names', 'components'):
            if c in apport:
                page[c] = apport[c]
        _retirer(page['interactions'], apport['remove_interactions'])
        _retirer(page['pipelines'], apport['remove_pipelines'])
        nom = lambda x: x.get('name')  # noqa: E731
        _fusion_par_cle(page['interactions'], apport.get('interactions', []), nom, _DEFAUT_INTERACTION)
        _fusion_par_cle(page['pipelines'], apport.get('pipelines', []), nom, _DEFAUT_PIPELINE)

    erreurs += sorted(_orphelins(etat) - avant)
    if erreurs:
        raise PatchRefuse(erreurs)
    return _vers_ids(etat)


# ── Enregistrement, historique, annulation ────────────────────────────────────

def instantane(app: AppSpec) -> dict:
    """La spec telle qu'elle est en base, sans la conversation ni les dates."""
    donnees = json.loads(json.dumps(AppSpecSerializer(app).data, default=str))
    return {c: donnees[c] for c in _CLES_SPEC}


def spec_de(app: AppSpec) -> dict:
    """La spec en base sous sa forme sérialisée, pour les calculs (conformité, remise)."""
    return {**instantane(app), 'id': app.pk}


def _aplatir(erreurs, chemin='') -> list:
    if isinstance(erreurs, dict):
        return [ligne for cle, v in erreurs.items() for ligne in _aplatir(v, f'{chemin}{cle}.')]
    if isinstance(erreurs, list):
        if all(isinstance(v, str) for v in erreurs):
            return [f"{chemin.rstrip('.')} : {' '.join(str(v) for v in erreurs)}"] if erreurs else []
        return [ligne for i, v in enumerate(erreurs) for ligne in _aplatir(v, f'{chemin}{i}.')]
    return [f"{chemin.rstrip('.')} : {erreurs}"]


def _enregistrer(app: AppSpec, spec: dict, restauration: bool = False) -> None:
    # `restauration` : on rend un état que la spec a déjà eu (annulation) — ce
    # qu'il contenait d'ancien (champ `file`) n'est pas une nouveauté à refuser.
    serialiseur = AppSpecSerializer(app, data=spec, context={'restauration': restauration})
    if not serialiseur.is_valid():
        raise PatchRefuse(_aplatir(serialiseur.errors))
    serialiseur.save()


def appliquer(app: AppSpec, patch_brut, mode: str = 'merge') -> PatchApplication:
    """Applique le patch à la spec en base, tout ou rien, et garde de quoi revenir en arrière."""
    with transaction.atomic():
        app = AppSpec.objects.select_for_update().get(pk=app.pk)
        avant = instantane(app)
        _enregistrer(app, fusionner(avant, patch_brut, mode))
        application = PatchApplication.objects.create(
            app=app, mode=mode, patch=patch_brut, summary=resume(patch_brut), snapshot_before=avant)
        anciennes = list(app.patch_applications.values_list('pk', flat=True)[HISTORIQUE_MAX:])
        PatchApplication.objects.filter(pk__in=anciennes).delete()
    return application


class AnnulationImpossible(Exception):
    pass


def annuler(application: PatchApplication) -> None:
    """Rend la spec d'avant ce patch. Seul le dernier patch encore en vigueur
    s'annule : défaire un patch plus ancien écraserait ceux appliqués depuis."""
    with transaction.atomic():
        app = AppSpec.objects.select_for_update().get(pk=application.app_id)
        derniere = app.patch_applications.filter(undone_at__isnull=True).first()
        if application.undone_at is not None:
            raise AnnulationImpossible('Ce patch a déjà été annulé.')
        if derniere is None or derniere.pk != application.pk:
            raise AnnulationImpossible("Seul le dernier patch appliqué peut être annulé.")
        _enregistrer(app, application.snapshot_before, restauration=True)
        application.undone_at = timezone.now()
        application.save(update_fields=['undone_at'])
