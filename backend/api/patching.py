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
import hashlib
import json
import threading
from copy import deepcopy

from django.db import transaction
from django.utils import timezone

from . import conformite
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
# Listes I1 de la spec fusionnées par nom (les intégrations par `type`).
_LISTES_V2 = {'roles': 'name', 'jobs': 'name', 'integrations': 'type', 'external_apis': 'name'}
_CLES_SPEC = ('name', 'project_name', 'description', 'app_type', 'required_groups',
              'business_rules', 'uses_email', 'roles', 'jobs', 'integrations', 'external_apis',
              'extensions') + _COLLECTIONS

_TYPES_DE_CHAMP = {
    'string': 'string', 'str': 'string', 'char': 'string', 'varchar': 'string',
    'slug': 'string',
    'url': 'url', 'uri': 'url', 'link': 'url', 'email': 'email', 'mail': 'email',
    'enum': 'enum', 'choice': 'enum', 'choices': 'enum', 'select': 'enum',
    'secret': 'secret', 'password': 'secret', 'api_key': 'secret', 'token': 'secret',
    'geo_point': 'geo_point', 'point': 'geo_point', 'geopoint': 'geo_point', 'latlng': 'geo_point',
    'geometry': 'geometry', 'polygon': 'geometry', 'linestring': 'geometry', 'multipolygon': 'geometry',
    'text': 'text', 'longtext': 'text', 'long_text': 'text',
    'int': 'int', 'integer': 'int',
    'decimal': 'decimal', 'float': 'decimal', 'double': 'decimal', 'number': 'decimal',
    'bool': 'bool', 'boolean': 'bool',
    'datetime': 'datetime', 'date': 'date', 'timestamp': 'datetime',
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
    # Attributs I1 (facultatifs).
    if 'values' in f:
        c['values'] = _noms(f['values'])
    for cle in ('min', 'max', 'max_bytes', 'srid'):
        if isinstance(f.get(cle), (int, float)) and not isinstance(f[cle], bool):
            c[cle] = f[cle]
    for cle in ('pattern', 'geometry_kind'):
        if _texte(f.get(cle)):
            c[cle] = _texte(f[cle])
    if 'unique_ci' in f:
        c['unique_ci'] = bool(f['unique_ci'])
    if 'accept' in f:
        c['accept'] = _noms(f['accept']) if isinstance(f['accept'], list) else _noms(_texte(f['accept']).split(','))
    if _texte(f.get('secret_scope')) in ('user', 'app'):
        c['secret_scope'] = _texte(f['secret_scope'])
    if _texte(f.get('rename_from')):
        c['rename_from'] = _texte(f['rename_from'])
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
    if _texte(r.get('rename_from')):
        rel['rename_from'] = _texte(r['rename_from'])
    return rel


# ── Structures I1 ─────────────────────────────────────────────────────────────

def _enum(valeur, permis, quoi, erreurs, defaut=None):
    v = _texte(valeur)
    if not v:
        return defaut
    if v not in permis:
        erreurs.append(f'{quoi} « {v} » inconnu(e) : ' + ', '.join(permis))
        return defaut
    return v


def _acces(a, erreurs, nom):
    if not isinstance(a, dict):
        return {}
    acces = {}
    portee = _enum(a.get('scope'), conformite.PORTEES, f'portée d\'accès du modèle « {nom} »', erreurs)
    if portee:
        acces['scope'] = portee
    for cle in ('owner_field', 'parent', 'share_model', 'public_flag', 'reason'):
        if _texte(a.get(cle)):
            acces[cle] = _texte(a[cle])
    if 'rules' in a:
        acces['rules'] = []
        for r in _dicts(a['rules']):
            action = _enum(r.get('action'), conformite.ACTIONS_D_ACCES, f'action d\'accès du modèle « {nom} »', erreurs)
            if action:
                acces['rules'].append({'action': action, 'who': _noms(r.get('who'))})
    if 'hidden_fields' in a:
        acces['hidden_fields'] = [{'field': _texte(h.get('field')), 'unless': _texte(h.get('unless')) or 'owner'}
                                  for h in _dicts(a['hidden_fields']) if _texte(h.get('field'))]
    return acces


def _etats(e):
    if not isinstance(e, dict):
        return {}
    etats = {}
    for cle in ('field', 'initial'):
        if _texte(e.get(cle)):
            etats[cle] = _texte(e[cle])
    if 'values' in e:
        etats['values'] = _noms(e['values'])
    if 'transitions' in e:
        etats['transitions'] = []
        for t in _dicts(e['transitions']):
            source = t.get('from')
            tr = {'from': _noms(source if isinstance(source, list) else [source]), 'to': _texte(t.get('to'))}
            if 'by' in t:
                tr['by'] = _noms(t['by'])
            if _texte(t.get('action')):
                tr['action'] = _texte(t['action'])
            if 'side_effects' in t:
                tr['side_effects'] = _noms(t['side_effects'])
            etats['transitions'].append(tr)
    if 'frozen_in' in e:
        etats['frozen_in'] = _noms(e['frozen_in'])
    return etats


def _contraintes(v):
    resultat = []
    for c in _dicts(v):
        genre = _texte(c.get('kind'))
        if genre not in ('unique', 'check'):
            continue
        k = {'kind': genre, 'fields': _noms(c.get('fields'))}
        for cle in ('condition', 'name'):
            if _texte(c.get(cle)):
                k[cle] = _texte(c[cle])
        resultat.append(k)
    return resultat


def _auth(a, erreurs, route):
    if not isinstance(a, dict):
        return {}
    auth = {}
    mode = _enum(a.get('mode'), conformite.MODES_AUTH, f'mode d\'authentification de {route}', erreurs)
    if mode:
        auth['mode'] = mode
    for cle in ('caller', 'key_source', 'reason'):
        if _texte(a.get(cle)):
            auth[cle] = _texte(a[cle])
    return auth


def _element_v2(x, erreurs, liste):
    """Un élément de `roles`, `jobs`, `integrations` ou `external_apis` : clés texte
    nettoyées, listes de noms dédoublonnées, genres fermés contrôlés."""
    el = {}
    for cle, v in x.items():
        if cle == 'rename_from':
            if _texte(v):
                el[cle] = _texte(v)
        elif isinstance(v, str):
            el[cle] = v.strip()
        elif isinstance(v, bool):
            el[cle] = v
        elif isinstance(v, list) and all(isinstance(n, str) for n in v):
            el[cle] = _noms(v)
    if liste == 'roles':
        _enum(el.get('kind'), conformite.GENRES_DE_ROLE, f"genre du rôle « {el.get('name')} »", erreurs)
    elif liste == 'jobs':
        _enum(el.get('kind'), conformite.GENRES_DE_JOB, f"genre de la tâche « {el.get('name')} »", erreurs)
    elif liste == 'integrations':
        _enum(el.get('type'), conformite.INTEGRATIONS, 'intégration', erreurs)
    return el


def cle_extension(liste, x) -> str:
    """Nom d'un élément d'extension : `name`, sinon dérivé de ses clés (data_io,
    notifications n'ont pas toujours de nom)."""
    if _texte(x.get('name')):
        return _texte(x['name'])
    if liste == 'data_io':
        return ' '.join(p for p in (_texte(x.get('direction')), _texte(x.get('format')), _texte(x.get('model'))) if p)
    if liste == 'notifications':
        return ' → '.join(p for p in (_texte(x.get('event')), _texte(x.get('channel'))) if p)
    return ''


def _extensions(v, erreurs):
    resultat = {}
    if not isinstance(v, dict):
        return resultat
    for liste, elements in v.items():
        if liste not in conformite.LISTES_D_EXTENSIONS:
            erreurs.append(f'liste d\'extensions « {liste} » inconnue : ' + ', '.join(conformite.LISTES_D_EXTENSIONS))
            continue
        resultat[liste] = [e for e in (deepcopy(x) for x in _dicts(elements)) if cle_extension(liste, e)]
    return resultat


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
    if 'auth' in e:
        ep['auth'] = _auth(e['auth'], _err(), f"{ep['method']} {ep['path']}")
    return ep


def _modele(m):
    mod = _communs(m, {'name': _texte(m.get('name'))})
    if 'fields' in m:
        mod['fields'] = [c for c in map(_champ, _dicts(m['fields'])) if c['name']]
    if 'relationships' in m:
        mod['relationships'] = [r for r in map(_relation, _dicts(m['relationships'])) if r['name']]
    if 'kind' in m:
        mod['kind'] = _enum(m['kind'], conformite.GENRES_DE_MODELE, f"genre du modèle « {mod['name']} »",
                            _err(), 'entity')
    if 'access' in m:
        mod['access'] = _acces(m['access'], _err(), mod['name'])
    if 'states' in m:
        mod['states'] = _etats(m['states'])
    if 'constraints' in m:
        mod['constraints'] = _contraintes(m['constraints'])
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
    if 'type' in i:
        inter['type'] = _texte(i['type']) or 'other'
    return inter


def _pipeline(p):
    pipe = _communs(p, {'name': _texte(p.get('name'))})
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
    if 'public' in p:
        page['public'] = p['public'] is True
    if 'public_reason' in p:
        page['public_reason'] = _texte(p['public_reason'])
    if 'required_roles' in p:
        page['required_roles'] = _noms(p['required_roles'])
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
    for cle in ('applies_to', 'kind'):
        if cle in r:
            regle[cle] = _texte(r[cle])
    if 'enforced_by' in r:
        regle['enforced_by'] = _noms(r['enforced_by'])
    if _texte(r.get('rename_from')):
        regle['rename_from'] = _texte(r['rename_from'])[:200]
    return regle


# Erreurs de valeurs fermées relevées pendant la normalisation (genres, modes,
# portées…) : remplie et vidée par `normaliser`, qui lève si elle n'est pas vide.
# Une liste par fil d'exécution (gunicorn sert plusieurs requêtes à la fois).
_LOCAL = threading.local()


def _err() -> list:
    if not hasattr(_LOCAL, 'erreurs'):
        _LOCAL.erreurs = []
    return _LOCAL.erreurs


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
    erreurs = _err()
    erreurs.clear()
    if _texte(meta_brut.get('app_type')):
        meta['app_type'] = _enum(meta_brut['app_type'], conformite.TYPES_CONSTRUCTIBLES, "type d'app", erreurs)
        if meta['app_type'] is None:
            del meta['app_type']
    meta['required_groups'] = _noms(meta_brut.get('required_groups'))
    meta['remove_required_groups'] = _noms(meta_brut.get('remove_required_groups'))
    v2 = {}
    for liste, cle in _LISTES_V2.items():
        v2[liste] = [x for x in (_element_v2(e, erreurs, liste) for e in _dicts(brut.get(liste))) if _texte(x.get(cle))]
        v2['remove_' + liste] = _noms(brut.get('remove_' + liste))
    v2['extensions'] = _extensions(brut.get('extensions'), erreurs)
    retraits = brut.get('remove_extensions') if isinstance(brut.get('remove_extensions'), dict) else {}
    v2['remove_extensions'] = {liste: _noms(noms) for liste, noms in retraits.items()
                               if liste in conformite.LISTES_D_EXTENSIONS}
    resultat = {
        **v2,
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
    if erreurs:
        refus = list(dict.fromkeys(erreurs))
        erreurs.clear()
        raise PatchRefuse(refus)
    return resultat


def resume(brut) -> str:
    """Une ligne lisible : ce que le patch ajoute, modifie ou retire."""
    if isinstance(brut, dict) and isinstance(brut.get('operations'), list):
        n = len(brut['operations'])
        return f'{n} opération{"s" if n > 1 else ""}'
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
        'business_rules': [{**deepcopy(r), 'title': _texte(r.get('title')), 'description': _texte(r.get('description'))}
                           for r in _dicts(spec.get('business_rules')) if _texte(r.get('title'))],
        'uses_email': spec.get('uses_email') is True,
    }
    for liste in _LISTES_V2:
        etat[liste] = deepcopy(_dicts(spec.get(liste)))
    extensions = spec.get('extensions') if isinstance(spec.get('extensions'), dict) else {}
    etat['extensions'] = {liste: deepcopy(_dicts(v)) for liste, v in extensions.items()}
    for c in _COLLECTIONS:
        etat[c] = deepcopy(_dicts(spec.get(c)))
    groupes = {g.get('id'): g.get('name') for g in etat['endpoint_groups'] if g.get('id') is not None}
    for g in etat['endpoint_groups']:
        g['endpoints'] = _dicts(g.get('endpoints'))
    for m in etat['data_models']:
        m['fields'], m['relationships'] = _dicts(m.get('fields')), _dicts(m.get('relationships'))
        m.setdefault('kind', 'entity')
        for cle, vide in (('access', {}), ('states', {}), ('constraints', [])):
            if not isinstance(m.get(cle), type(vide)):
                m[cle] = deepcopy(vide)
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


def fusionner(spec: dict, patch_brut, mode: str = 'merge', verifier_orphelins: bool = True) -> dict:
    """Rend la spec sérialisée après application du patch. Ne modifie pas `spec`.
    Lève `PatchRefuse` si le patch est illisible ou incohérent.

    `verifier_orphelins=False` : pour les étapes intermédiaires d'une suite
    d'opérations, dont les références sont vérifiées une fois, à la fin."""
    if mode not in MODES:
        raise PatchRefuse([f'mode inconnu : {mode}'])
    patch = normaliser(patch_brut)
    etat = _vers_noms(spec)
    if mode == 'replace':
        for c in _COLLECTIONS:
            etat[c] = []
    avant = _orphelins(etat) | _references_v2(etat)
    erreurs = []

    # ── Métadonnées ───────────────────────────────────────────────────────────
    meta = patch['set_meta']
    for c in ('name', 'description', 'project_name', 'uses_email', 'app_type'):
        if c in meta:
            etat[c] = meta[c]
    # Règles métier : retrouvées par leur titre, comme tout le reste par son nom.
    etat['business_rules'] = [r for r in etat['business_rules'] if r['title'] not in patch['remove_business_rules']]
    for apport in patch['business_rules']:
        ancien = apport.pop('rename_from', None)
        if ancien and ancien != apport['title']:
            cible = next((r for r in etat['business_rules'] if r['title'] == ancien), None)
            if cible is not None:
                if any(r['title'] == apport['title'] for r in etat['business_rules']):
                    erreurs.append(f"impossible de renommer la règle « {ancien} » en « {apport['title']} » : ce titre est déjà pris")
                else:
                    cible['title'] = apport['title']
        regle = next((r for r in etat['business_rules'] if r['title'] == apport['title']), None)
        if regle is None:
            regle = {'title': apport['title'], 'description': ''}
            etat['business_rules'].append(regle)
        regle.update(apport)
    # Union, jamais remplacement : ajouter un groupe ne fait pas disparaître
    # ceux déjà validés. Un groupe ne sort que par `remove_required_groups`.
    etat['required_groups'] = [g for g in _noms(etat['required_groups'] + meta['required_groups'])
                               if g not in meta['remove_required_groups']]

    # ── Listes I1 : rôles, tâches, intégrations (par `type`), API externes ────
    def propager_role(ancien, nouveau):
        def r(n):
            return nouveau if n == ancien else n

        def qui(n):
            return f'role:{nouveau}' if n == f'role:{ancien}' else n
        for role in etat['roles']:
            if isinstance(role.get('implies'), list):
                role['implies'] = [r(n) for n in role['implies']]
        for g in etat['endpoint_groups']:
            for e in g['endpoints']:
                e['required_roles'] = [r(n) for n in _liste(e.get('required_roles'))]
        for p in etat['pages']:
            p['required_roles'] = [r(n) for n in _liste(p.get('required_roles'))]
        for m in etat['data_models']:
            for regle in _dicts(m['access'].get('rules')):
                regle['who'] = [qui(n) for n in _liste(regle.get('who'))]
            for h in _dicts(m['access'].get('hidden_fields')):
                h['unless'] = qui(h.get('unless'))
            for t in _dicts(m['states'].get('transitions')):
                t['by'] = [qui(n) for n in _liste(t.get('by'))]
        for n in _dicts(etat['extensions'].get('notifications')):
            n['to'] = qui(n.get('to'))

    propagations = {'roles': propager_role}
    for liste, cle in _LISTES_V2.items():
        retraits = patch['remove_' + liste]
        etat[liste] = [x for x in etat[liste] if x.get(cle) not in retraits]
        for apport in patch[liste]:
            ancien = apport.pop('rename_from', None)
            if ancien and ancien != apport[cle]:
                cible = next((x for x in etat[liste] if x.get(cle) == ancien), None)
                if cible is not None:
                    if any(x.get(cle) == apport[cle] for x in etat[liste]):
                        erreurs.append(f'impossible de renommer « {ancien} » en « {apport[cle]} » : ce nom est déjà pris')
                    else:
                        cible[cle] = apport[cle]
                        if liste in propagations:
                            propagations[liste](ancien, apport[cle])
            cible = next((x for x in etat[liste] if x.get(cle) == apport[cle]), None)
            if cible is None:
                etat[liste].append(dict(apport))
            else:
                cible.update(apport)
    for liste, noms in patch['remove_extensions'].items():
        etat['extensions'][liste] = [x for x in _dicts(etat['extensions'].get(liste))
                                     if cle_extension(liste, x) not in noms]
    for liste, apports in patch['extensions'].items():
        elements = etat['extensions'].setdefault(liste, [])
        for apport in apports:
            nom = cle_extension(liste, apport)
            ancien = apport.pop('rename_from', None)
            if ancien:
                cible = next((x for x in elements if cle_extension(liste, x) == ancien), None)
                if cible is not None:
                    cible['name'] = nom
            cible = next((x for x in elements if cle_extension(liste, x) == nom), None)
            if cible is None:
                elements.append(apport)
            else:
                cible.update(apport)
    etat['extensions'] = {k: v for k, v in etat['extensions'].items() if v}

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
        # Références I1 vers un modèle.
        for j in etat['jobs']:
            for cle in ('input_model', 'tracked_by'):
                if j.get(cle) == ancien:
                    j[cle] = nouveau
            if j.get('concurrency') == f'one_per:{ancien}':
                j['concurrency'] = f'one_per:{nouveau}'
        for role in etat['roles']:
            if role.get('on_model') == ancien:
                role['on_model'] = nouveau
        for m in etat['data_models']:
            if m['access'].get('share_model') == ancien:
                m['access']['share_model'] = nouveau
        for r in etat['business_rules']:
            if r.get('applies_to') == ancien:
                r['applies_to'] = nouveau
        for x in _dicts(etat['extensions'].get('data_io')):
            if x.get('model') == ancien:
                x['model'] = nouveau
        for x in _dicts(etat['extensions'].get('computations')):
            if isinstance(x.get('inputs'), list):
                x['inputs'] = [nouveau + n[len(ancien):] if isinstance(n, str) and n.startswith(ancien + '.') else n
                               for n in x['inputs']]
        for x in _dicts(etat['extensions'].get('notifications')):
            if isinstance(x.get('event'), str) and x['event'].startswith(ancien + '.'):
                x['event'] = nouveau + x['event'][len(ancien):]

    def propager_champ(modele, ancien, nouveau):
        acces, etats = modele['access'], modele['states']
        for cle in ('owner_field', 'public_flag'):
            if acces.get(cle) == ancien:
                acces[cle] = nouveau
        for h in _dicts(acces.get('hidden_fields')):
            if h.get('field') == ancien:
                h['field'] = nouveau
        if etats.get('field') == ancien:
            etats['field'] = nouveau
        for c in _dicts(modele['constraints']):
            c['fields'] = [nouveau if n == ancien else n for n in _liste(c.get('fields'))]

    def propager_relation(modele, ancien, nouveau):
        if modele['access'].get('parent') == ancien:
            modele['access']['parent'] = nouveau

    _retirer(etat['data_models'], patch['remove_models'])
    for apport in patch['data_models']:
        _renommer(etat['data_models'], apport, 'le modèle', erreurs, propager_modele)
        modele = _trouver(etat['data_models'], apport['name'])
        if modele is None:
            modele = {'name': apport['name'], 'description': '', 'fields': [], 'relationships': [],
                      'order': len(etat['data_models']), 'kind': 'entity', 'access': {}, 'states': {},
                      'constraints': []}
            etat['data_models'].append(modele)
        # `access`, `states`, `constraints` : remplacés en entier quand fournis.
        for c in ('description', 'order', 'kind', 'access', 'states', 'constraints'):
            if c in apport:
                modele[c] = apport[c]
        _retirer(modele['fields'], apport['remove_fields'])
        _retirer(modele['relationships'], apport['remove_relationships'])
        for liste, genre, propager in (('fields', 'le champ', propager_champ),
                                       ('relationships', 'la relation', propager_relation)):
            for sous in apport.get(liste, []):
                _renommer(modele[liste], sous, f"{genre} de « {modele['name']} »", erreurs,
                          lambda a, n, m=modele, f=propager: f(m, a, n))
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
        for c in ('route', 'layout', 'order', 'service_names', 'components', 'public', 'public_reason',
                  'required_roles'):
            if c in apport:
                page[c] = apport[c]
        _retirer(page['interactions'], apport['remove_interactions'])
        _retirer(page['pipelines'], apport['remove_pipelines'])

        def propager_interaction(ancien, nouveau, page=page):
            for pl in page['pipelines']:
                if pl.get('trigger_interaction') == ancien:
                    pl['trigger_interaction'] = nouveau
        for sous in apport.get('interactions', []):
            _renommer(page['interactions'], sous, f"l'interaction de « {page['name']} »", erreurs, propager_interaction)
        for sous in apport.get('pipelines', []):
            _renommer(page['pipelines'], sous, f"le pipeline de « {page['name']} »", erreurs)
        nom = lambda x: x.get('name')  # noqa: E731
        _fusion_par_cle(page['interactions'], apport.get('interactions', []), nom, _DEFAUT_INTERACTION)
        _fusion_par_cle(page['pipelines'], apport.get('pipelines', []), nom, _DEFAUT_PIPELINE)

    _coherence_auth(etat)
    if verifier_orphelins:
        erreurs += sorted((_orphelins(etat) | _references_v2(etat)) - avant)
    if erreurs:
        raise PatchRefuse(erreurs)
    return _vers_ids(etat)


def _coherence_auth(etat: dict) -> None:
    """Règle I1 : `auth.mode` ≠ jwt ⇒ route sans jeton, raison copiée ;
    route sans jeton sans `auth` ⇒ mode `public`."""
    for g in etat['endpoint_groups']:
        for e in g['endpoints']:
            auth = e.get('auth') if isinstance(e.get('auth'), dict) else {}
            if auth.get('mode') and auth['mode'] != 'jwt':
                e['auth_required'] = False
                if _texte(auth.get('reason')):
                    e['public_reason'] = _texte(auth['reason'])
            elif e.get('auth_required') is False and not auth:
                e['auth'] = {'mode': 'public'}


def _references_v2(etat: dict) -> set:
    """Références I1 qui ne tiennent pas, en phrases. Comme `_orphelins`, seules
    celles qu'un patch INTRODUIT le font refuser. Les rôles inconnus ne sont pas
    ici : ce sont des avertissements (`conformite.verifier`)."""
    modeles = {m['name']: m for m in etat['data_models']}
    routes = {f"{e.get('method')} {e.get('path')}" for g in etat['endpoint_groups'] for e in g['endpoints']}
    manques = set()
    for m in etat['data_models']:
        nom, acces, etats = m['name'], m.get('access') or {}, m.get('states') or {}
        relations = {r.get('name') for r in m['relationships']}
        if acces.get('parent') and acces['parent'] not in relations:
            manques.add(f"l'accès du modèle « {nom} » suit la relation « {acces['parent']} », absente de ce modèle")
        if acces.get('share_model') and acces['share_model'] not in modeles:
            manques.add(f"l'accès du modèle « {nom} » cite le modèle de partage « {acces['share_model']} », absent de la spec")
        valeurs = set(_liste(etats.get('values')))
        if etats:
            for t in _dicts(etats.get('transitions')):
                for v in _liste(t.get('from')) + [t.get('to')]:
                    if v not in valeurs:
                        manques.add(f"une transition du modèle « {nom} » cite l'état « {v} », absent de ses valeurs")
            for v in ([etats['initial']] if etats.get('initial') else []) + _liste(etats.get('frozen_in')):
                if v not in valeurs:
                    manques.add(f"le cycle de vie du modèle « {nom} » cite l'état « {v} », absent de ses valeurs")
    for j in etat['jobs']:
        for cle in ('input_model', 'tracked_by'):
            if j.get(cle) and j[cle] not in modeles:
                manques.add(f"la tâche « {j.get('name')} » cite le modèle « {j[cle]} » ({cle}), absent de la spec")
    for r in etat['business_rules']:
        for route in _liste(r.get('enforced_by')):
            cle = _cle_endpoint(route)
            if cle is None or f'{cle[0]} {cle[1]}' not in routes:
                manques.add(f"la règle « {r['title']} » est tenue par l'endpoint « {route} », absent de la spec")
    return manques


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


# ── Opérations atomiques (I2/I3 du chantier app-builder-v2) ───────────────────

class VersionPerimee(Exception):
    """La spec a changé depuis la version sur laquelle les opérations ont été préparées."""


def _sans_ids(v):
    if isinstance(v, dict):
        return {k: _sans_ids(x) for k, x in v.items() if k != 'id'}
    if isinstance(v, list):
        return [_sans_ids(x) for x in v]
    return v


def version_de(app_or_spec) -> str:
    """« v: » + 16 hex : empreinte du contenu de la spec (sans conversation, sans
    identifiants, sans dates). Change dès qu'un élément change, pas autrement."""
    spec = instantane(app_or_spec) if isinstance(app_or_spec, AppSpec) else app_or_spec
    etat = _vers_noms(spec)
    texte = json.dumps(_sans_ids(etat), sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)
    return 'v:' + hashlib.sha256(texte.encode('utf-8')).hexdigest()[:16]


# Types d'opération (I2) : collection de l'état de travail et clé du nom.
TYPES_D_OPERATION = ('meta', 'groupe_requis', 'regle', 'role', 'job', 'integration', 'api_externe',
                     'extension', 'modele', 'champ', 'relation', 'groupe_endpoints', 'endpoint',
                     'service', 'page', 'interaction', 'pipeline')
_LISTE_V2_DE = {'role': 'roles', 'job': 'jobs', 'integration': 'integrations', 'api_externe': 'external_apis'}
_RENOMMABLES = ('regle', 'role', 'job', 'api_externe', 'extension', 'modele', 'champ', 'relation',
                'groupe_endpoints', 'service', 'page', 'interaction', 'pipeline')
_LIBELLE = {'meta': 'métadonnées', 'groupe_requis': 'groupe requis', 'regle': 'règle', 'role': 'rôle',
            'job': 'tâche', 'integration': 'intégration', 'api_externe': 'API externe', 'extension': 'extension',
            'modele': 'modèle', 'champ': 'champ', 'relation': 'relation', 'groupe_endpoints': "groupe d'endpoints",
            'endpoint': 'endpoint', 'service': 'service', 'page': 'page', 'interaction': 'interaction',
            'pipeline': 'pipeline'}
# Listes complètes : présentes dans `data`, elles remplacent (opération destructive si raccourcie).
_LISTES_COMPLETES = {'page': ('components', 'service_names'), 'pipeline': ('steps',), 'endpoint': ('steps',),
                     'service': ('endpoint_group_names',)}


def _nom_de(x, cle='name'):
    return x.get(cle) if isinstance(x, dict) else None


def _localiser(etat, cible):
    """(élément existant ou None, parent ou None, erreur de localisation ou None)."""
    t, nom = cible['type'], cible['nom']
    trouver = lambda liste, n, cle='name': next((x for x in liste if _nom_de(x, cle) == n), None)  # noqa: E731
    if t == 'groupe_requis':
        return (nom if nom in etat['required_groups'] else None), None, None
    if t == 'regle':
        return trouver(etat['business_rules'], nom, 'title'), None, None
    if t in _LISTE_V2_DE:
        liste = _LISTE_V2_DE[t]
        return trouver(etat[liste], nom, _LISTES_V2[liste]), None, None
    if t == 'extension':
        liste, _, n = nom.partition(':')
        if liste not in conformite.LISTES_D_EXTENSIONS or not n.strip():
            return None, None, ('une extension se nomme « <liste>:<nom> », liste parmi '
                                + ', '.join(conformite.LISTES_D_EXTENSIONS))
        return next((x for x in _dicts(etat['extensions'].get(liste)) if cle_extension(liste, x) == n.strip()), None), None, None
    if t == 'modele':
        return trouver(etat['data_models'], nom), None, None
    if t == 'groupe_endpoints':
        return trouver(etat['endpoint_groups'], nom), None, None
    if t == 'service':
        return trouver(etat['services'], nom), None, None
    if t == 'page':
        return trouver(etat['pages'], nom), None, None
    if t in ('champ', 'relation'):
        parent = trouver(etat['data_models'], cible.get('modele'))
        if parent is None:
            return None, None, f"le modèle « {cible.get('modele')} » n'existe pas (le créer par une opération précédente)"
        return trouver(parent['fields' if t == 'champ' else 'relationships'], nom), parent, None
    if t == 'endpoint':
        parent = trouver(etat['endpoint_groups'], cible.get('groupe'))
        if parent is None:
            return None, None, f"le groupe d'endpoints « {cible.get('groupe')} » n'existe pas (le créer par une opération précédente)"
        cle = _cle_endpoint(nom)
        if cle is None or cle[0] not in _METHODES or not cle[1].startswith('/'):
            return None, None, 'un endpoint se nomme « METHODE /chemin/ » (' + ', '.join(_METHODES) + ')'
        return next((e for e in parent['endpoints'] if (e.get('method'), e.get('path')) == cle), None), parent, None
    if t in ('interaction', 'pipeline'):
        parent = trouver(etat['pages'], cible.get('page'))
        if parent is None:
            return None, None, f"la page « {cible.get('page')} » n'existe pas (la créer par une opération précédente)"
        return trouver(parent['interactions' if t == 'interaction' else 'pipelines'], nom), parent, None
    return None, None, None


def _lire_operation(op):
    """Contrôle de forme d'une opération : (op, cible, erreur)."""
    if not isinstance(op, dict):
        return None, None, "une opération est un objet {op, cible, …}"
    genre = op.get('op')
    if genre not in ('upsert', 'remove', 'rename'):
        return None, None, f"« op » vaut upsert, remove ou rename (reçu : {genre!r})"
    brut = op.get('cible') if isinstance(op.get('cible'), dict) else {}
    t = brut.get('type')
    if t not in TYPES_D_OPERATION:
        return None, None, f"type de cible inconnu : {t!r} (" + ', '.join(TYPES_D_OPERATION) + ')'
    cible = {'type': t, 'nom': _texte(brut.get('nom'))}
    for cle in ('modele', 'groupe', 'page'):
        cible[cle] = _texte(brut.get(cle))
    if t != 'meta' and not cible['nom']:
        return None, None, f'la cible ({_LIBELLE[t]}) doit porter « nom »'
    besoin = {'champ': 'modele', 'relation': 'modele', 'endpoint': 'groupe', 'interaction': 'page', 'pipeline': 'page'}
    if t in besoin and not cible[besoin[t]]:
        return None, None, f'la cible ({_LIBELLE[t]}) doit porter « {besoin[t]} »'
    if t == 'meta' and genre != 'upsert':
        return None, None, 'les métadonnées ne se modifient que par upsert'
    if genre == 'rename':
        if t not in _RENOMMABLES:
            return None, None, f'un(e) {_LIBELLE[t]} ne se renomme pas : remove puis upsert'
        if not _texte(op.get('nouveau_nom')):
            return None, None, 'rename demande « nouveau_nom »'
    if genre == 'upsert' and 'data' in op and not isinstance(op['data'], dict):
        return None, None, '« data » est un objet'
    return genre, cible, None


def _fragment(genre, cible, data, nouveau):
    """Une opération → un patch au format de `normaliser`."""
    t, nom = cible['type'], cible['nom']
    data = {k: v for k, v in (data or {}).items() if k not in ('rename_from',)}
    if t == 'meta':
        return {'set_meta': {k: data[k] for k in ('name', 'project_name', 'description', 'app_type', 'uses_email') if k in data}}
    if t == 'groupe_requis':
        return {'set_meta': {'required_groups' if genre == 'upsert' else 'remove_required_groups': [nom]}}
    if t == 'regle':
        if genre == 'remove':
            return {'remove_business_rules': [nom]}
        if genre == 'rename':
            return {'business_rules': [{'title': nouveau, 'rename_from': nom}]}
        return {'business_rules': [{**data, 'title': nom}]}
    if t in _LISTE_V2_DE:
        liste = _LISTE_V2_DE[t]
        cle = _LISTES_V2[liste]
        if genre == 'remove':
            return {'remove_' + liste: [nom]}
        if genre == 'rename':
            return {liste: [{cle: nouveau, 'rename_from': nom}]}
        return {liste: [{**data, cle: nom}]}
    if t == 'extension':
        liste, _, n = nom.partition(':')
        n = n.strip()
        if genre == 'remove':
            return {'remove_extensions': {liste: [n]}}
        if genre == 'rename':
            return {'extensions': {liste: [{'name': _texte(nouveau.partition(':')[2]) if ':' in nouveau else nouveau,
                                            'rename_from': n}]}}
        return {'extensions': {liste: [{**data, 'name': n}]}}
    if t in ('modele', 'groupe_endpoints', 'service', 'page'):
        coll, retrait = {'modele': ('data_models', 'remove_models'), 'groupe_endpoints': ('endpoint_groups', 'remove_endpoint_groups'),
                         'service': ('services', 'remove_services'), 'page': ('pages', 'remove_pages')}[t]
        if genre == 'remove':
            return {retrait: [nom]}
        if genre == 'rename':
            return {coll: [{'name': nouveau, 'rename_from': nom}]}
        return {coll: [{**data, 'name': nom}]}
    if t in ('champ', 'relation'):
        sous, retrait = ('fields', 'remove_fields') if t == 'champ' else ('relationships', 'remove_relationships')
        if genre == 'remove':
            return {'data_models': [{'name': cible['modele'], retrait: [nom]}]}
        element = {'name': nouveau, 'rename_from': nom} if genre == 'rename' else {**data, 'name': nom}
        return {'data_models': [{'name': cible['modele'], sous: [element]}]}
    if t == 'endpoint':
        methode, chemin = _cle_endpoint(nom)
        if genre == 'remove':
            return {'endpoint_groups': [{'name': cible['groupe'], 'remove_endpoints': [nom]}]}
        return {'endpoint_groups': [{'name': cible['groupe'], 'endpoints': [{**data, 'method': methode, 'path': chemin}]}]}
    if t in ('interaction', 'pipeline'):
        sous = 'interactions' if t == 'interaction' else 'pipelines'
        if genre == 'remove':
            return {'pages': [{'name': cible['page'], 'remove_' + sous: [nom]}]}
        element = {'name': nouveau, 'rename_from': nom} if genre == 'rename' else {**data, 'name': nom}
        return {'pages': [{'name': cible['page'], sous: [element]}]}
    raise AssertionError(t)


def _instance_de(spec):
    pk = spec.get('id') if isinstance(spec, dict) else None
    return AppSpec.objects.filter(pk=pk).first() if isinstance(pk, int) else None


def essayer_operations(spec: dict, operations: list) -> dict:
    """Applique `operations` (I2) à `spec` sans rien écrire et rend l'état
    résultant (forme sérialisée). Lève `PatchRefuse` (refus en bloc)."""
    if not isinstance(operations, list) or not operations:
        raise PatchRefuse(['une liste d\'opérations non vide est attendue'])
    depart = _vers_noms(spec)
    avant = _orphelins(depart) | _references_v2(depart)
    courant = deepcopy(spec) if isinstance(spec, dict) else {}
    erreurs = []
    for i, op in enumerate(operations, 1):
        genre, cible, erreur = _lire_operation(op)
        if erreur is None:
            etat = _vers_noms(courant)
            existant, _parent, erreur = _localiser(etat, cible)
            if erreur is None and genre in ('remove', 'rename') and existant is None:
                erreur = f"{_LIBELLE[cible['type']]} « {cible['nom']} » introuvable"
            if erreur is None and genre == 'rename':
                deja, _, _ = _localiser(etat, {**cible, 'nom': _texte(op['nouveau_nom'])})
                if deja is not None:
                    erreur = f"impossible de renommer en « {_texte(op['nouveau_nom'])} » : ce nom est déjà pris"
        if erreur is None:
            try:
                courant = fusionner(courant, _fragment(genre, cible, op.get('data'), _texte(op.get('nouveau_nom'))),
                                    verifier_orphelins=False)
                courant['id'] = spec.get('id') if isinstance(spec, dict) else None
            except PatchRefuse as refus:
                erreur = ' ; '.join(refus.erreurs)
        if erreur is not None:
            erreurs.append(f'opération {i} : {erreur}')
    if erreurs:
        raise PatchRefuse(erreurs)
    fin = _vers_noms(courant)
    erreurs = sorted((_orphelins(fin) | _references_v2(fin)) - avant)
    if erreurs:
        raise PatchRefuse(erreurs)
    # Le sérialiseur a le dernier mot (longueurs, choix fermés, champ `file`…).
    donnees = {k: v for k, v in courant.items() if k in _CLES_SPEC}
    serialiseur = AppSpecSerializer(_instance_de(spec), data=donnees)
    if not serialiseur.is_valid():
        raise PatchRefuse(_aplatir(serialiseur.errors))
    return courant


def _trouve(spec, cible):
    try:
        return _localiser(_vers_noms(spec), cible)[0]
    except Exception:  # noqa: BLE001 — un résumé ne fait jamais échouer
        return None


def resume_operations(avant: dict, operations: list, apres: dict) -> dict:
    """Ce que fait une suite d'opérations, en phrases : {texte, destructive, details}."""
    details = []
    for i, op in enumerate(operations if isinstance(operations, list) else [], 1):
        genre, cible, erreur = _lire_operation(op)
        if erreur:
            details.append({'index': i, 'texte': f'opération illisible ({erreur})', 'destructive': False})
            continue
        t, nom = cible['type'], cible['nom']
        lieu = {'champ': cible['modele'], 'relation': cible['modele'], 'endpoint': cible['groupe'],
                'interaction': cible['page'], 'pipeline': cible['page']}.get(t)
        quoi = f"{_LIBELLE[t]} « {nom} »" + (f' de {lieu}' if lieu else '') if t != 'meta' else 'métadonnées'
        destructive = genre in ('remove', 'rename')
        if genre == 'remove':
            texte = f'{quoi} retiré(e)'
        elif genre == 'rename':
            texte = f"{quoi} renommé(e) en « {_texte(op.get('nouveau_nom'))} »"
        else:
            existant = _trouve(avant, cible) if t != 'meta' else True
            data = op.get('data') if isinstance(op.get('data'), dict) else {}
            texte = f'{quoi} ' + ('modifié(e)' if existant is not None else 'ajouté(e)')
            if t == 'meta':
                texte = 'métadonnées modifiées (' + ', '.join(sorted(data)) + ')'
            raccourcies = []
            for liste in _LISTES_COMPLETES.get(t, ()):
                if liste in data and isinstance(data[liste], list) and isinstance(existant, dict):
                    n_avant, n_apres = len(_liste(existant.get(liste))), len(data[liste])
                    if n_apres < n_avant:
                        raccourcies.append(f'{liste} remplacés ({n_avant} → {n_apres})')
            if raccourcies:
                destructive = True
                texte = f'{quoi} : ' + ', '.join(raccourcies)
        details.append({'index': i, 'texte': texte, 'destructive': destructive})
    # Regroupement : « 2 champs ajoutés à Produit ».
    morceaux, vus = [], {}
    for d, op in zip(details, operations if isinstance(operations, list) else []):
        cible = op.get('cible') if isinstance(op, dict) and isinstance(op.get('cible'), dict) else {}
        if cible.get('type') == 'champ' and op.get('op') == 'upsert' and d['texte'].endswith('ajouté(e)'):
            cle = ('champ', cible.get('modele'))
            if cle in vus:
                vus[cle][0] += 1
                continue
            vus[cle] = [1, len(morceaux)]
            morceaux.append(None)
            continue
        morceaux.append(d['texte'])
    for (_, modele), (n, place) in vus.items():
        morceaux[place] = f'{n} champ{"s" if n > 1 else ""} ajouté{"s" if n > 1 else ""} à {modele}'
    return {'texte': ' ; '.join(morceaux) or 'aucune opération',
            'destructive': any(d['destructive'] for d in details), 'details': details}


def appliquer_operations(app, operations: list, base_version: str | None = None) -> PatchApplication:
    """Applique les opérations en base, tout ou rien, avec un instantané pour annuler.
    `VersionPerimee` si `base_version` est fourni et ne correspond plus à la spec."""
    with transaction.atomic():
        app = AppSpec.objects.select_for_update().get(pk=app.pk)
        avant = instantane(app)
        if base_version is not None and base_version != version_de(avant):
            raise VersionPerimee(version_de(avant))
        spec = {**avant, 'id': app.pk}
        apres = essayer_operations(spec, operations)
        _enregistrer(app, {k: v for k, v in apres.items() if k in _CLES_SPEC})
        application = PatchApplication.objects.create(
            app=app, mode='ops', patch={'operations': operations},
            summary=resume_operations(spec, operations, apres)['texte'], snapshot_before=avant)
        anciennes = list(app.patch_applications.values_list('pk', flat=True)[HISTORIQUE_MAX:])
        PatchApplication.objects.filter(pk__in=anciennes).delete()
    return application


def patch_vers_operations(patch: dict) -> list:
    """Un patch (format de `normaliser`) → la liste d'opérations équivalente, dans
    l'ordre où `fusionner` l'applique. Le mode `replace` n'a pas d'équivalent."""
    p = normaliser(patch)
    ops = []

    def op(genre, t, nom='', data=None, nouveau=None, **loc):
        o = {'op': genre, 'cible': {'type': t, 'nom': nom, **loc}}
        if data:
            o['data'] = data
        if nouveau:
            o['nouveau_nom'] = nouveau
        ops.append(o)

    meta = {k: v for k, v in p['set_meta'].items() if k not in ('required_groups', 'remove_required_groups')}
    if meta:
        op('upsert', 'meta', data=meta)
    for g in p['set_meta']['required_groups']:
        op('upsert', 'groupe_requis', g)
    for g in p['set_meta']['remove_required_groups']:
        op('remove', 'groupe_requis', g)
    for t in p['remove_business_rules']:
        op('remove', 'regle', t)
    for r in p['business_rules']:
        r = dict(r)
        if r.get('rename_from'):
            op('rename', 'regle', r.pop('rename_from'), nouveau=r['title'])
        titre = r.pop('title')
        op('upsert', 'regle', titre, data=r or None)
    for t, liste in _LISTE_V2_DE.items():
        cle = _LISTES_V2[liste]
        for n in p['remove_' + liste]:
            op('remove', t, n)
        for x in p[liste]:
            x = dict(x)
            if x.get('rename_from'):
                op('rename', t, x.pop('rename_from'), nouveau=x[cle])
            nom = x.pop(cle)
            op('upsert', t, nom, data=x or None)
    for liste, noms in p['remove_extensions'].items():
        for n in noms:
            op('remove', 'extension', f'{liste}:{n}')
    for liste, elements in p['extensions'].items():
        for x in elements:
            op('upsert', 'extension', f'{liste}:{cle_extension(liste, x)}', data={k: v for k, v in x.items() if k != 'name'} or None)
    for n in p['remove_models']:
        op('remove', 'modele', n)
    for m in p['data_models']:
        m = dict(m)
        if m.get('rename_from'):
            op('rename', 'modele', m.pop('rename_from'), nouveau=m['name'])
        data = {k: m[k] for k in ('description', 'order', 'kind', 'access', 'states', 'constraints') if k in m}
        op('upsert', 'modele', m['name'], data=data or None)
        for sous, t in (('remove_fields', 'champ'), ('remove_relationships', 'relation')):
            for n in m.get(sous, []):
                op('remove', t, n, modele=m['name'])
        for sous, t in (('fields', 'champ'), ('relationships', 'relation')):
            for x in m.get(sous, []):
                x = dict(x)
                if x.get('rename_from'):
                    op('rename', t, x.pop('rename_from'), nouveau=x['name'], modele=m['name'])
                op('upsert', t, x.pop('name'), data=x or None, modele=m['name'])
    for n in p['remove_endpoint_groups']:
        op('remove', 'groupe_endpoints', n)
    for g in p['endpoint_groups']:
        g = dict(g)
        if g.get('rename_from'):
            op('rename', 'groupe_endpoints', g.pop('rename_from'), nouveau=g['name'])
        op('upsert', 'groupe_endpoints', g['name'], data={k: g[k] for k in ('description', 'order') if k in g} or None)
        for methode, chemin in g.get('remove_endpoints', []):
            op('remove', 'endpoint', f'{methode} {chemin}', groupe=g['name'])
        for e in g.get('endpoints', []):
            e = dict(e)
            nom = f"{e.pop('method')} {e.pop('path')}"
            op('upsert', 'endpoint', nom, data=e or None, groupe=g['name'])
    for n in p['remove_services']:
        op('remove', 'service', n)
    for sv in p['services']:
        sv = dict(sv)
        if sv.get('rename_from'):
            op('rename', 'service', sv.pop('rename_from'), nouveau=sv['name'])
        op('upsert', 'service', sv.pop('name'), data=sv or None)
    for n in p['remove_pages']:
        op('remove', 'page', n)
    for pg in p['pages']:
        pg = dict(pg)
        if pg.get('rename_from'):
            op('rename', 'page', pg.pop('rename_from'), nouveau=pg['name'])
        data = {k: v for k, v in pg.items() if k not in ('name', 'interactions', 'pipelines', 'remove_interactions',
                                                          'remove_pipelines')}
        op('upsert', 'page', pg['name'], data=data or None)
        for sous, t in (('remove_interactions', 'interaction'), ('remove_pipelines', 'pipeline')):
            for n in pg.get(sous, []):
                op('remove', t, n, page=pg['name'])
        for sous, t in (('interactions', 'interaction'), ('pipelines', 'pipeline')):
            for x in pg.get(sous, []):
                x = dict(x)
                if x.get('rename_from'):
                    op('rename', t, x.pop('rename_from'), nouveau=x['name'], page=pg['name'])
                op('upsert', t, x.pop('name'), data=x or None, page=pg['name'])
    return ops
