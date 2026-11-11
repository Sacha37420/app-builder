"""Le graphe d'une spécification, du plus large au plus fin (interface I6, version 2).

Une seule description, lue par l'interface à dix échelles. Les cinq premières
sont celles de la version 1 (mêmes ids, même ordre, mêmes nœuds) :

- `overview`     : la place de l'app dans le lab (groupes → Keycloak → interface → API → base, storage, email) ;
- `architecture` : pages, services, groupes d'endpoints et leurs endpoints ;
- `data`         : modèles et relations ;
- `pipelines`    : interactions, pipelines et leurs étapes ;
- `roadmap`      : les lots de la feuille de route générée, reliés à ce qu'ils construisent ;

puis `api` (arbre des routes), `pages` (plan du site), `security` (matrice qui
voit quoi), `lifecycles` (états des modèles) et `jobs` (tâches de fond).

Chaque nœud dit à quelle échelle il appartient, de quel nœud plus large il
descend (`parent`), à quel élément de la spec il renvoie (`ref`) et où l'éditer
(`edit`). Les défauts que la v1 taisait (doublon, référence vers un nom inconnu)
sont rendus dans `issues`. Fonction pure et déterministe de la spec sérialisée —
ni base, ni réseau ; toute clé peut manquer ou être de mauvais type.
"""
from . import conformite, remise

VERSION = 2

ECHELLES = (
    {'id': 'overview', 'label': 'Dans le lab', 'notation': 'c4'},
    {'id': 'architecture', 'label': 'Architecture', 'notation': 'c4'},
    {'id': 'data', 'label': 'Données', 'notation': 'er'},
    {'id': 'pipelines', 'label': 'Pipelines', 'notation': 'sequence'},
    {'id': 'roadmap', 'label': 'Feuille de route', 'notation': 'kanban'},
    {'id': 'api', 'label': 'API', 'notation': 'tree'},
    {'id': 'pages', 'label': 'Pages', 'notation': 'sitemap'},
    {'id': 'security', 'label': 'Sécurité', 'notation': 'matrix'},
    {'id': 'lifecycles', 'label': 'Cycles de vie', 'notation': 'statechart'},
    {'id': 'jobs', 'label': 'Tâches de fond', 'notation': 'timeline'},
)
_ORDRE_ECHELLES = [e['id'] for e in ECHELLES]

# Libellé et classe de couleur de chaque genre. Les classes sont celles que définit
# déjà l'interface (`overview.component.scss` : blue, purple, green, amber, cyan, gray) ;
# les genres v1 gardent celles de `overview.store.ts`.
GENRES = {
    'groups': ('Accès', 'k-amber'),
    'keycloak': ('Connexion', 'k-purple'),
    'frontend': ('Interface', 'k-green'),
    'api': ('API', 'k-blue'),
    'database': ('Base de données', 'k-cyan'),
    'storage': ('Fichiers', 'k-gray'),
    'email': ('Email', 'k-gray'),
    'business_rule': ('Règle métier', 'k-amber'),
    'endpoint_group': ("Groupe d'endpoints", 'k-blue'),
    'endpoint': ('Route', 'k-blue'),
    'service': ('Service', 'k-purple'),
    'page': ('Page', 'k-green'),
    'data_model': ('Modèle', 'k-cyan'),
    'interaction': ('Interaction', 'k-amber'),
    'pipeline': ('Pipeline', 'k-green'),
    'step': ('Étape', 'k-gray'),
    'lot': ('Lot', 'k-purple'),
    'role': ('Rôle', 'k-amber'),
    'job': ('Tâche de fond', 'k-purple'),
    'integration': ('Service du lab', 'k-gray'),
    'external_api': ('API externe', 'k-gray'),
    'state': ('État', 'k-cyan'),
    'transition': ('Transition', 'k-gray'),
}

OPERATIONS_CRUD = ('list', 'create', 'retrieve', 'update', 'partial_update', 'delete', 'custom')
_CARDINALITES = {'FK': ('N', '1'), 'O2O': ('1', '1'), 'M2M': ('N', 'N')}

# Nœuds d'infrastructure : où les régler dans l'interface. Groupes, client Keycloak,
# interface, API et base relèvent de la fiche générale de l'app (`meta` : nom,
# type, groupes requis) ; storage et email sont des services du lab, donc des
# intégrations (I1 `integrations[].type` : storage, email).
_SECTION_INFRA = {'groups': 'meta', 'keycloak': 'meta', 'frontend': 'meta', 'api': 'meta',
                  'database': 'meta', 'storage': 'integrations', 'email': 'integrations'}


def _dicts(v):
    return [x for x in (v if isinstance(v, list) else []) if isinstance(x, dict)]


def _dict(v):
    return v if isinstance(v, dict) else {}


def _nom(v) -> str:
    return remise._ligne(v, 120)


def _id(v):
    """L'identifiant numérique d'un élément de la spec, ou None."""
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _ref(collection, element=None, name=''):
    ident = _id(element.get('id')) if isinstance(element, dict) else None
    ref = {'collection': collection, 'id': ident}
    if ident is None:
        ref['name'] = name
    return ref


def _infra(section):
    return {'route': '/infra', 'query': {'section': section}}


def graphe(spec: dict, lots: list[dict] | None = None) -> dict:
    """Nœuds, liens, matrices et séquences de la spec.

    `lots` : ceux de `remise.lots(spec)` (recalculés si absents)."""
    spec = spec if isinstance(spec, dict) else {}
    lots = remise.lots(spec) if lots is None else lots
    lots = [lot for lot in (lots if isinstance(lots, list) else []) if isinstance(lot, dict)]
    empreinte = conformite.empreinte(spec)
    app_type = spec.get('app_type')
    inconnu = app_type not in conformite.TYPES_CONSTRUCTIBLES
    backend = inconnu or conformite.a_un_backend(app_type)
    frontend = inconnu or conformite.a_un_frontend(app_type)
    noeuds, liens, problemes = [], [], []
    par_id = {}

    def signaler(code, message, ident=None):
        probleme = {'code': code, 'message': message}
        if ident is not None:
            probleme['node'] = ident
            if ident in par_id:
                par_id[ident]['issues'].append({'code': code, 'message': message})
        problemes.append(probleme)

    def noeud(ident, kind, scale, label, parent=None, *, ref, edit, attrs=None, **plus):
        if ident in par_id:
            signaler('duplicate_name', f"Deux éléments donnent l'identifiant « {ident} » : le second est ignoré.", ident)
            return False
        n = {'id': ident, 'kind': kind, 'scale': scale, 'label': label, 'parent': parent,
             'detail': plus.pop('detail', ''), **plus,
             'ref': ref, 'edit': edit, 'attrs': attrs or {}, 'lots': [], 'appears_in': [], 'issues': []}
        par_id[ident] = n
        noeuds.append(n)
        return True

    def lien(source, target, kind, label='', cardinality=None):
        if source in par_id and target in par_id:
            liens.append({'id': f'l{len(liens) + 1}', 'source': source, 'target': target, 'kind': kind,
                          'label': label, 'cardinality': cardinality})
            return True
        return False

    def lien_nomme(source, prefixe, valeur, kind, genre, label='', cardinality=None, inverse=False):
        """Lien vers l'élément `prefixe + valeur` ; un nom non vide inconnu est signalé."""
        valeur = valeur if isinstance(valeur, str) else ('' if valeur is None else str(valeur))
        valeur = _nom(valeur)
        if not valeur or source not in par_id:
            return
        cible = prefixe + valeur
        if cible not in par_id:
            signaler('dangling_ref', f"{genre} « {valeur} » inconnu (référencé par « {source} »).", source)
            return
        if inverse:
            lien(cible, source, kind, label, cardinality)
        else:
            lien(source, cible, kind, label, cardinality)

    # ── Vue d'ensemble : la place dans le lab ─────────────────────────────────
    groupes = empreinte['keycloak']['required_groups']

    def infra(ident, kind, label, **plus):
        return noeud(ident, kind, 'overview', label, ref=_ref('infra', name=kind),
                     edit=_infra(_SECTION_INFRA[kind]), **plus)

    infra('infra:groups', 'groups', 'Groupes autorisés',
          detail=', '.join(groupes) if groupes else 'aucun — app ouverte à tout compte du lab', count=len(groupes),
          attrs={'groups': list(groupes)})
    infra('infra:keycloak', 'keycloak', 'Keycloak',
          detail=f"client {empreinte['keycloak']['client_id']} — flow à la connexion, puis contrôle par l'API",
          attrs={'client_id': empreinte['keycloak']['client_id']})
    lien('infra:groups', 'infra:keycloak', 'flow', 'se connectent')
    if frontend:
        infra('infra:frontend', 'frontend', 'Interface Angular', opens='architecture',
              detail=empreinte['paths']['frontend'] or '', count=len(_dicts(spec.get('pages'))),
              attrs={'path': empreinte['paths']['frontend']})
        lien('infra:keycloak', 'infra:frontend', 'flow', 'jeton')
    if backend:
        infra('infra:api', 'api', 'API Django', opens='architecture',
              detail=empreinte['paths']['api'] or '', count=len(conformite.endpoints(spec)),
              attrs={'path': empreinte['paths']['api']})
        lien('infra:frontend' if frontend else 'infra:keycloak', 'infra:api', 'flow',
             'appels avec jeton' if frontend else 'jeton')
        infra('infra:database', 'database', 'Base PostgreSQL', opens='data',
              detail=f"schéma {empreinte['database']['schema']}" if empreinte['database'] else '',
              count=len(_dicts(spec.get('data_models'))),
              attrs={'schema': empreinte['database']['schema'] if empreinte['database'] else None})
        lien('infra:api', 'infra:database', 'flow', 'lit et écrit')
        if empreinte['storage']['used']:
            infra('infra:storage', 'storage', 'Service storage du lab',
                  detail=', '.join(empreinte['storage']['fields']), count=len(empreinte['storage']['fields']),
                  attrs={'fields': list(empreinte['storage']['fields'])})
            lien('infra:api', 'infra:storage', 'flow', 'fichiers des utilisateurs')
        if empreinte['email']['used']:
            infra('infra:email', 'email', 'Email', detail='send_mail, compte réglé dans lab-admin')
            lien('infra:api', 'infra:email', 'flow', 'envoie')
    racine_api = 'infra:api' if backend else None
    racine_ui = 'infra:frontend' if frontend else None

    for r in _dicts(spec.get('business_rules')):
        titre = _nom(r.get('title'))
        if titre and noeud(f'rule:{titre}', 'business_rule', 'overview', titre, racine_api or racine_ui,
                           detail=remise._ligne(r.get('description'), 300),
                           ref=_ref('business_rules', name=titre), edit=_infra('rules'),
                           attrs={'kind': _nom(r.get('kind')), 'applies_to': _nom(r.get('applies_to')),
                                  'enforced_by': remise._noms(r.get('enforced_by'))}):
            lien(racine_api or racine_ui, f'rule:{titre}', 'contains')

    # ── Données ───────────────────────────────────────────────────────────────
    modeles = _dicts(spec.get('data_models'))
    edit_modele = {}
    for m in modeles:
        nom = _nom(m.get('name'))
        champs = _dicts(m.get('fields'))
        relations = _dicts(m.get('relationships'))
        edit = {'route': '/models', 'query': {'modele': _id(m.get('id'))}}
        if nom and noeud(f'model:{nom}', 'data_model', 'data', nom, 'infra:database' if backend else None,
                         detail=remise._ligne(m.get('description'), 300), count=len(champs),
                         fields=[{'name': _nom(f.get('name')), 'type': _nom(f.get('type')) or 'string'} for f in champs],
                         ref=_ref('data_models', m, nom), edit=edit,
                         attrs={'kind': _nom(m.get('kind')) or 'entity', 'pk': 'id',
                                'scope': _nom(_dict(m.get('access')).get('scope')),
                                'fk': [_nom(r.get('name')) for r in relations
                                       if (_nom(r.get('rel_type')) or 'FK') in ('FK', 'O2O')],
                                'required': [_nom(f.get('name')) for f in champs if f.get('required') is True],
                                'storage_fields': [_nom(f.get('name')) for f in champs if f.get('type') == 'storage_file'],
                                'constraints': len(_dicts(m.get('constraints')))}):
            edit_modele[nom] = edit
            lien('infra:database', f'model:{nom}', 'contains')
    for m in modeles:
        source = f"model:{_nom(m.get('name'))}"
        for r in _dicts(m.get('relationships')):
            genre = _nom(r.get('rel_type')) or 'FK'
            card = _CARDINALITES.get(genre)
            lien_nomme(source, 'model:', r.get('to_model'), 'relation', 'Modèle',
                       f"{_nom(r.get('name'))} ({genre})",
                       {'source': card[0], 'target': card[1]} if card else None)

    # ── Rôles ─────────────────────────────────────────────────────────────────
    roles = []
    for r in _dicts(spec.get('roles')):
        nom = _nom(r.get('name'))
        if nom and noeud(f'role:{nom}', 'role', 'security', nom, 'infra:groups',
                         detail=remise._ligne(r.get('description'), 300),
                         ref=_ref('roles', name=nom), edit=_infra('roles'),
                         attrs={'kind': _nom(r.get('kind')) or 'keycloak_group',
                                'implies': remise._noms(r.get('implies')), 'on_model': _nom(r.get('on_model'))}):
            roles.append(nom)
            lien('infra:groups', f'role:{nom}', 'contains')
    for r in _dicts(spec.get('roles')):
        source = f"role:{_nom(r.get('name'))}"
        for autre in remise._noms(r.get('implies')):
            lien_nomme(source, 'role:', autre, 'implies', 'Rôle', 'implique')
        lien_nomme(source, 'model:', r.get('on_model'), 'scoped_by', 'Modèle', 'sur')

    # ── Architecture ──────────────────────────────────────────────────────────
    groupes_par_id = {}
    endpoints_du_groupe = {}
    acces = {}                   # endpoint → (ouvert, rôles requis)
    route_vers_endpoint = {}
    for g in _dicts(spec.get('endpoint_groups')):
        nom = _nom(g.get('name'))
        points = _dicts(g.get('endpoints'))
        gid = _id(g.get('id'))
        if not nom or not noeud(f'group:{nom}', 'endpoint_group', 'architecture', nom, racine_api,
                                detail=remise._ligne(g.get('description'), 300), count=len(points),
                                ref=_ref('endpoint_groups', g, nom),
                                edit={'route': '/endpoints', 'query': {'groupe': gid}}):
            continue
        groupes_par_id[g.get('id')] = nom
        endpoints_du_groupe[nom] = []
        lien(racine_api, f'group:{nom}', 'contains')
        for e in points:
            route = remise._route(e)
            ident = f'endpoint:{nom}/{route}'
            auth = _dict(e.get('auth'))
            public = e.get('auth_required') is False
            mode = _nom(auth.get('mode')) or ('public' if public else 'jwt')
            requis = remise._noms(e.get('required_roles'))
            if noeud(ident, 'endpoint', 'architecture', route, f'group:{nom}',
                     detail=remise._ligne(e.get('description'), 300), public=public, roles=requis,
                     ref=_ref('endpoints', e, route),
                     edit={'route': '/endpoints', 'query': {'groupe': gid, 'endpoint': _id(e.get('id'))}},
                     attrs={'method': _nom(e.get('method')) or 'GET', 'path': remise._ligne(e.get('path'), 300) or '/',
                            'operation': _nom(e.get('operation')), 'auth': mode,
                            'model': _nom(e.get('linked_model_name'))}):
                endpoints_du_groupe[nom].append(ident)
                acces[ident] = (public or mode != 'jwt', requis)
                route_vers_endpoint.setdefault(route, ident)
                lien(f'group:{nom}', ident, 'contains')
                lien_nomme(ident, 'model:', e.get('linked_model_name'), 'reads', 'Modèle')

    services_par_id = {}
    groupes_du_service = {}
    for s in _dicts(spec.get('services')):
        nom = _nom(s.get('name'))
        if not nom or not noeud(f'service:{nom}', 'service', 'architecture', nom, racine_ui,
                                # Hors table I6 : les services se règlent avec les pages (`/pages-config`).
                                ref=_ref('services', s, nom),
                                edit={'route': '/pages-config', 'query': {'service': _id(s.get('id'))}},
                                attrs={'endpoint_groups': []}):
            continue
        services_par_id[s.get('id')] = nom
        groupes_du_service[nom] = []
        lien(racine_ui, f'service:{nom}', 'contains')
        for i in s.get('endpoint_group_ids') if isinstance(s.get('endpoint_group_ids'), list) else []:
            if not isinstance(i, (int, str)) or isinstance(i, bool):
                continue
            if i in groupes_par_id:
                if lien(f'service:{nom}', f'group:{groupes_par_id[i]}', 'calls'):
                    groupes_du_service[nom].append(groupes_par_id[i])
                    par_id[f'service:{nom}']['attrs']['endpoint_groups'].append(groupes_par_id[i])
            else:
                signaler('dangling_ref', f"Groupe d'endpoints n° « {i} » inconnu (référencé par « service:{nom} »).",
                         f'service:{nom}')

    services_de_page = {}
    pipelines_emis = []          # (ident, nom de page, étapes)
    for p in _dicts(spec.get('pages')):
        nom = _nom(p.get('name'))
        pipelines = _dicts(p.get('pipelines'))
        pid = _id(p.get('id'))
        page = f'page:{nom}'
        if not nom or not noeud(page, 'page', 'architecture', nom, racine_ui, opens='pipelines',
                                detail=_nom(p.get('route')), count=len(pipelines),
                                ref=_ref('pages', p, nom), edit={'route': '/pages-config', 'query': {'page': pid}},
                                attrs={'route': _nom(p.get('route')), 'layout': _nom(p.get('layout')),
                                       'public': p.get('public') is True,
                                       'public_reason': remise._ligne(p.get('public_reason'), 300),
                                       'required_roles': remise._noms(p.get('required_roles')),
                                       'components': len(_dicts(p.get('components')))}):
            continue
        services_de_page[nom] = []
        lien(racine_ui, page, 'contains')
        for i in p.get('service_ids') if isinstance(p.get('service_ids'), list) else []:
            if not isinstance(i, (int, str)) or isinstance(i, bool):
                continue
            if i in services_par_id:
                if lien(page, f'service:{services_par_id[i]}', 'uses'):
                    services_de_page[nom].append(services_par_id[i])
            else:
                signaler('dangling_ref', f"Service n° « {i} » inconnu (référencé par « {page} »).", page)
        for c in _dicts(p.get('components')):
            lien_nomme(page, 'model:', c.get('linked_model'), 'reads', 'Modèle')

        # ── Pipelines ─────────────────────────────────────────────────────────
        for i in _dicts(p.get('interactions')):
            titre = _nom(i.get('name'))
            if titre and noeud(f'interaction:{nom}/{titre}', 'interaction', 'pipelines', titre, page,
                               detail=_nom(i.get('type')), ref=_ref('interactions', i, titre),
                               edit={'route': '/pipelines', 'query': {'page': pid}},
                               attrs={'type': _nom(i.get('type'))}):
                lien(page, f'interaction:{nom}/{titre}', 'contains')
        for pl in pipelines:
            titre = _nom(pl.get('name'))
            etapes = _dicts(pl.get('steps'))
            ident = f'pipeline:{nom}/{titre}'
            edit = {'route': '/pipelines', 'query': {'page': pid, 'pipeline': _id(pl.get('id'))}}
            if not titre or not noeud(ident, 'pipeline', 'pipelines', titre, page,
                                      detail=remise._ligne(pl.get('description'), 300), count=len(etapes),
                                      ref=_ref('pipelines', pl, titre), edit=edit,
                                      attrs={'trigger': _nom(pl.get('trigger_interaction'))}):
                continue
            lien(page, ident, 'contains')
            lien_nomme(ident, f'interaction:{nom}/', pl.get('trigger_interaction'), 'triggers', 'Interaction',
                       inverse=True)
            precedent = None
            for rang, st in enumerate(etapes):
                etape = f'step:{nom}/{titre}/{rang}'
                noeud(etape, 'step', 'pipelines', _nom(st.get('label')) or f'étape {rang + 1}', ident,
                      detail=_nom(st.get('type')), order=rang,
                      ref={'collection': 'steps', 'id': None, 'name': f'{nom}/{titre}/{rang}'}, edit=edit,
                      attrs={'type': _nom(st.get('type')), 'service': _nom(st.get('service_name')),
                             'method': _nom(st.get('service_method'))})
                lien(ident, etape, 'contains')
                if precedent:
                    lien(precedent, etape, 'next')
                lien_nomme(etape, 'service:', st.get('service_name'), 'invokes', 'Service')
                precedent = etape
            pipelines_emis.append((ident, nom, etapes, _nom(pl.get('trigger_interaction'))))

    # ── Cycles de vie : états et transitions des modèles ──────────────────────
    faits = set()
    for m in modeles:
        nom = _nom(m.get('name'))
        modele = f'model:{nom}'
        if not nom or nom not in edit_modele or nom in faits:   # un doublon est déjà signalé
            continue
        faits.add(nom)
        etats = _dict(m.get('states'))
        valeurs = remise._noms(etats.get('values'))
        if not valeurs:
            continue
        initial = _nom(etats.get('initial'))
        figes = remise._noms(etats.get('frozen_in'))
        ref_etats = {'collection': 'states', 'id': None}
        for v in valeurs:
            if noeud(f'state:{nom}/{v}', 'state', 'lifecycles', v, modele, detail=_nom(etats.get('field')),
                     ref={**ref_etats, 'name': f'{nom}/{v}'}, edit=edit_modele[nom],
                     attrs={'value': v, 'field': _nom(etats.get('field')), 'initial': v == initial,
                            'frozen': v in figes}):
                lien(modele, f'state:{nom}/{v}', 'contains')
        if initial and f'state:{nom}/{initial}' not in par_id:
            signaler('dangling_ref', f"État initial « {initial} » inconnu (modèle « {nom} »).", modele)
        for rang, t in enumerate(_dicts(etats.get('transitions'))):
            ident = f'transition:{nom}/{rang}'
            vers = _nom(t.get('to'))
            depuis = remise._noms(t.get('from'))
            action = _nom(t.get('action'))
            if not noeud(ident, 'transition', 'lifecycles', action or f"→ {vers or '?'}", modele,
                         ref={'collection': 'transitions', 'id': None, 'name': f'{nom}/{rang}'}, edit=edit_modele[nom],
                         order=rang,
                         attrs={'from': depuis, 'to': vers, 'by': remise._noms(t.get('by')), 'action': action,
                                'side_effects': remise._noms(t.get('side_effects'))}):
                continue
            lien(modele, ident, 'contains')
            for d in depuis:
                lien_nomme(ident, f'state:{nom}/', d, 'transition', 'État', 'depuis', inverse=True)
            lien_nomme(ident, f'state:{nom}/', vers, 'transition', 'État', 'vers')
            if action in route_vers_endpoint:
                lien(route_vers_endpoint[action], ident, 'performs')

    # ── Tâches de fond, intégrations du lab, API externes ─────────────────────
    for j in _dicts(spec.get('jobs')):
        nom = _nom(j.get('name'))
        ident = f'job:{nom}'
        declencheur = _nom(j.get('trigger'))
        if not nom or not noeud(ident, 'job', 'jobs', nom, racine_api,
                                detail=remise._ligne(j.get('description'), 300),
                                ref=_ref('jobs', name=nom), edit=_infra('jobs'),
                                attrs={'kind': _nom(j.get('kind')) or 'async', 'trigger': declencheur,
                                       'input_model': _nom(j.get('input_model')),
                                       'tracked_by': _nom(j.get('tracked_by')),
                                       'concurrency': _nom(j.get('concurrency')), 'heavy': j.get('heavy') is True}):
            continue
        if racine_api:
            lien(racine_api, ident, 'contains')
        lien_nomme(ident, 'model:', j.get('input_model'), 'reads', 'Modèle', 'entrée')
        lien_nomme(ident, 'model:', j.get('tracked_by'), 'tracks', 'Modèle', 'suivi')
        if declencheur in route_vers_endpoint:
            lien(route_vers_endpoint[declencheur], ident, 'enqueues')

    for it in _dicts(spec.get('integrations')):
        genre = _nom(it.get('type'))
        if genre and noeud(f'integration:{genre}', 'integration', 'overview', genre, racine_api or racine_ui,
                           detail=remise._ligne(it.get('description'), 300),
                           ref=_ref('integrations', name=genre), edit=_infra('integrations'),
                           attrs={'type': genre, 'mode': _nom(it.get('mode'))}):
            lien(racine_api or racine_ui, f'integration:{genre}', 'uses')

    for x in _dicts(spec.get('external_apis')):
        nom = _nom(x.get('name'))
        if nom and noeud(f'external_api:{nom}', 'external_api', 'overview', nom, racine_api or racine_ui,
                         detail=remise._ligne(x.get('description'), 300),
                         ref=_ref('external_apis', name=nom), edit=_infra('external_apis'),
                         attrs={'purpose': _nom(x.get('purpose')), 'auth': _nom(x.get('auth')) or 'none',
                                'called_from': _nom(x.get('called_from')) or 'backend'}):
            lien(racine_api or racine_ui, f'external_api:{nom}', 'calls')

    # ── Feuille de route ──────────────────────────────────────────────────────
    cibles = {'data_model': 'model:{name}', 'endpoint_group': 'group:{name}', 'business_rule': 'rule:{name}',
              'service': 'service:{name}', 'page': 'page:{name}', 'pipeline': 'pipeline:{page}/{name}',
              'job': 'job:{name}', 'role': 'role:{name}'}
    numeros = []
    for lot in lots:
        numero = lot.get('number')
        if not isinstance(numero, int) or isinstance(numero, bool):
            continue
        ident = f'lot:{numero}'
        if not noeud(ident, 'lot', 'roadmap', f"Lot {numero} — {_nom(lot.get('title'))}",
                     detail=remise._ligne(lot.get('objective'), 600), family=lot.get('family'),
                     tokens=lot.get('tokens'), order=numero,
                     ref={'collection': 'lots', 'id': None, 'name': str(numero)},
                     edit={'route': '/preview', 'query': {'lot': numero}},
                     attrs={'family': lot.get('family'), 'tokens': lot.get('tokens')}):
            continue
        numeros.append(numero)
        for e in _dicts(lot.get('elements')):
            gabarit = cibles.get(e.get('kind'))
            if gabarit is None:
                continue
            cible = gabarit.format(name=_nom(e.get('name')), page=_nom(e.get('page')))
            if lien(ident, cible, 'builds') and numero not in par_id[cible]['lots']:
                par_id[cible]['lots'].append(numero)
    for avant, apres in zip(numeros, numeros[1:]):
        if apres == avant + 1:
            lien(f'lot:{avant}', f'lot:{apres}', 'next')
    # Une étape est construite avec son pipeline ; un endpoint avec son groupe ; un état avec son modèle.
    for n in noeuds:
        if n['kind'] in ('step', 'endpoint', 'state', 'transition') and n['parent'] in par_id and not n['lots']:
            n['lots'] = list(par_id[n['parent']]['lots'])

    # ── Matrices ──────────────────────────────────────────────────────────────
    matrices = {'security': _matrice_securite(spec, par_id, acces, endpoints_du_groupe, groupes_du_service,
                                              services_de_page, groupes, roles),
                'crud': _matrice_crud(spec, par_id, acces)}

    # ── Séquences : une par pipeline ──────────────────────────────────────────
    sequences = []
    for ident, page_nom, etapes, declencheur in pipelines_emis:
        sequences.append(_sequence(ident, page_nom, etapes, declencheur, par_id, groupes_du_service, backend))

    # ── Où chaque nœud apparaît ───────────────────────────────────────────────
    modeles_api = {r for r, cases in zip(matrices['crud']['rows'], matrices['crud']['cells']) if any(cases)}
    for n in noeuds:
        vues = {n['scale']}
        k = n['kind']
        if k in ('endpoint', 'endpoint_group'):
            vues.add('api')
        if k in ('endpoint', 'page', 'role'):
            vues.add('security')
        if k in ('page', 'service'):
            vues.add('pages')
        if k == 'role':
            vues.add('overview')
        if k == 'data_model':
            if n['label'] in modeles_api:
                vues.add('api')
            if any(c['kind'] == 'state' and c['parent'] == n['id'] for c in noeuds):
                vues.add('lifecycles')
        if k in ('state', 'transition'):
            vues.add('data')
        n['appears_in'] = [e for e in _ORDRE_ECHELLES if e in vues]
    for lien_ in liens:
        if lien_['kind'] in ('reads', 'tracks') and lien_['source'].startswith('job:'):
            cible = par_id[lien_['target']]
            if 'jobs' not in cible['appears_in']:
                cible['appears_in'] = [e for e in _ORDRE_ECHELLES if e in set(cible['appears_in']) | {'jobs'}]

    # ── Échelles disponibles ──────────────────────────────────────────────────
    genres_emis = {n['kind'] for n in noeuds}
    raisons = {
        'api': None if 'endpoint' in genres_emis else "La spec ne décrit aucun endpoint.",
        'pages': None if 'page' in genres_emis else "La spec ne décrit aucune page.",
        'security': None if genres_emis & {'endpoint', 'page'} else "Ni endpoint ni page : rien à protéger.",
        'lifecycles': None if 'state' in genres_emis else "Aucun modèle ne décrit d'états (`states`).",
        'jobs': None if 'job' in genres_emis else "La spec ne décrit aucune tâche de fond (`jobs`).",
    }
    echelles = []
    for e in ECHELLES:
        entree = dict(e)
        raison = raisons.get(e['id'])
        entree['available'] = raison is None
        if raison:
            entree['reason'] = raison
        echelles.append(entree)

    genres = {}
    for n in noeuds:
        if n['kind'] not in genres:
            label, cat = GENRES.get(n['kind'], (n['kind'], 'k-gray'))
            genres[n['kind']] = {'label': label, 'cat': cat}

    return {'version': VERSION, 'scales': echelles, 'kinds': genres, 'nodes': noeuds, 'links': liens,
            'issues': problemes, 'matrices': matrices, 'sequences': sequences}


def _autorise(ligne: str, requis: list[str]) -> bool:
    """Une ligne non publique (`groupe:g` ou `role:r`) passe-t-elle une liste de rôles requis ?"""
    if not requis:
        return True
    return ligne.split(':', 1)[1] in requis


def _matrice_securite(spec, par_id, acces, endpoints_du_groupe, groupes_du_service, services_de_page,
                      groupes, roles) -> dict:
    lignes = ['public']
    for g in groupes:
        if f'groupe:{g}' not in lignes:
            lignes.append(f'groupe:{g}')
    for r in roles:
        if f'role:{r}' not in lignes:
            lignes.append(f'role:{r}')
    colonnes_ep = list(acces)
    colonnes_pages = [n['id'] for n in par_id.values() if n['kind'] == 'page']

    def endpoint(ligne, ident):
        ouvert, requis = acces[ident]
        if ouvert:
            return 'allow'
        if ligne == 'public':
            return 'deny'
        return 'allow' if _autorise(ligne, requis) else 'deny'

    cellules, notes = [], {}
    for i, ligne in enumerate(lignes):
        rang = [endpoint(ligne, c) for c in colonnes_ep]
        for j, page in enumerate(colonnes_pages, len(colonnes_ep)):
            attrs = par_id[page]['attrs']
            if attrs['public']:
                case = 'allow'
            elif ligne == 'public':
                case = 'deny'
            else:
                case = 'allow' if _autorise(ligne, attrs['required_roles']) else 'deny'
            if case == 'allow':
                appels = [ep for s in services_de_page.get(par_id[page]['label'], [])
                          for g in groupes_du_service.get(s, []) for ep in endpoints_du_groupe.get(g, [])]
                refuses = list(dict.fromkeys(ep for ep in appels if endpoint(ligne, ep) == 'deny'))
                if refuses:
                    case = 'inconsistent'
                    notes[f'{i},{j}'] = (f"La page « {par_id[page]['label']} » est ouverte à « {ligne} » mais appelle "
                                         + ', '.join(f"« {par_id[ep]['label']} »" for ep in refuses)
                                         + ', refusé(s) à cette ligne.')
            rang.append(case)
        cellules.append(rang)
    return {'rows': lignes, 'cols': colonnes_ep + colonnes_pages, 'cells': cellules, 'notes': notes}


def _matrice_crud(spec, par_id, acces) -> dict:
    lignes = [n['label'] for n in par_id.values() if n['kind'] == 'data_model']
    cases = {m: {op: [] for op in OPERATIONS_CRUD} for m in lignes}
    for ident in acces:
        attrs = par_id[ident]['attrs']
        modele = attrs['model']
        if modele in cases:
            op = attrs['operation'] if attrs['operation'] in OPERATIONS_CRUD else 'custom'
            cases[modele][op].append(par_id[ident]['label'])
    return {'rows': lignes, 'cols': list(OPERATIONS_CRUD),
            'cells': [[cases[m][op] for op in OPERATIONS_CRUD] for m in lignes]}


def _sequence(ident, page_nom, etapes, declencheur, par_id, groupes_du_service, backend) -> dict:
    page = f'page:{page_nom}'
    lignes = ['user', page]
    messages = []

    def ligne(x):
        if x not in lignes:
            lignes.append(x)
        return lignes.index(x)

    # Toutes les lignes de vie d'abord, dans l'ordre des étapes, puis les messages.
    services = []
    for st in etapes:
        s = f"service:{_nom(st.get('service_name'))}"
        if s in par_id and s not in services:
            services.append(s)
    for s in services:
        ligne(s)
    for s in services:
        for g in groupes_du_service.get(par_id[s]['label'], []):
            ligne(f'group:{g}')
    if backend and 'infra:database' in par_id:
        ligne('infra:database')

    messages.append({'from': 0, 'to': 1, 'label': declencheur or 'ouvre la page'})
    for rang, st in enumerate(etapes):
        etape = f'step:{ident[len("pipeline:"):]}/{rang}'
        libelle = par_id[etape]['label'] if etape in par_id else f'étape {rang + 1}'
        s = f"service:{_nom(st.get('service_name'))}"
        if s not in par_id:
            messages.append({'from': 1, 'to': 1, 'label': libelle, 'step': etape})
            continue
        messages.append({'from': 1, 'to': lignes.index(s), 'label': _nom(st.get('service_method')) or libelle,
                         'step': etape})
        for g in groupes_du_service.get(par_id[s]['label'], []):
            messages.append({'from': lignes.index(s), 'to': lignes.index(f'group:{g}'), 'label': 'requête HTTP',
                             'step': etape})
            if 'infra:database' in lignes:
                messages.append({'from': lignes.index(f'group:{g}'), 'to': lignes.index('infra:database'),
                                 'label': 'lit et écrit', 'step': etape})
    return {'pipeline': ident, 'lifelines': lignes, 'messages': messages}
