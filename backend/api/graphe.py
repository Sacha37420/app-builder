"""Le graphe d'une spécification, du plus large au plus fin.

Une seule description, lue par l'interface à cinq échelles :

- `overview`     : la place de l'app dans le lab (groupes → Keycloak → interface → API → base, storage, email) ;
- `architecture` : pages, services, groupes d'endpoints et leurs endpoints ;
- `data`         : modèles et relations ;
- `pipelines`    : interactions, pipelines et leurs étapes ;
- `roadmap`      : les lots de la feuille de route générée, reliés à ce qu'ils construisent.

Chaque nœud dit à quelle échelle il appartient et de quel nœud plus large il
descend (`parent`) : c'est ce qui permet de passer d'une échelle à l'autre sans
perdre le fil. Fonction pure de la spec sérialisée — ni base, ni réseau.
"""
from . import conformite, remise

ECHELLES = (
    {'id': 'overview', 'label': 'Dans le lab'},
    {'id': 'architecture', 'label': 'Architecture'},
    {'id': 'data', 'label': 'Données'},
    {'id': 'pipelines', 'label': 'Pipelines'},
    {'id': 'roadmap', 'label': 'Feuille de route'},
)


def _dicts(v):
    return [x for x in (v if isinstance(v, list) else []) if isinstance(x, dict)]


def _nom(v) -> str:
    return remise._ligne(v, 120)


def graphe(spec: dict, lots: list[dict] | None = None) -> dict:
    """Nœuds et liens de la spec. `lots` : ceux de `remise.lots(spec)` (recalculés si absents)."""
    lots = remise.lots(spec) if lots is None else lots
    empreinte = conformite.empreinte(spec)
    app_type = spec.get('app_type')
    inconnu = app_type not in conformite.TYPES_CONSTRUCTIBLES
    backend = inconnu or conformite.a_un_backend(app_type)
    frontend = inconnu or conformite.a_un_frontend(app_type)
    noeuds, liens, vus = [], [], set()

    def noeud(ident, kind, scale, label, parent=None, **plus):
        if ident in vus:
            return False
        vus.add(ident)
        noeuds.append({'id': ident, 'kind': kind, 'scale': scale, 'label': label, 'parent': parent,
                       'detail': plus.pop('detail', ''), **plus})
        return True

    def lien(source, target, kind, label=''):
        if source in vus and target in vus:
            liens.append({'source': source, 'target': target, 'kind': kind, 'label': label})

    # ── Vue d'ensemble : la place dans le lab ─────────────────────────────────
    groupes = empreinte['keycloak']['required_groups']
    noeud('infra:groups', 'groups', 'overview', 'Groupes autorisés',
          detail=', '.join(groupes) if groupes else 'aucun — app ouverte à tout compte du lab', count=len(groupes))
    noeud('infra:keycloak', 'keycloak', 'overview', 'Keycloak',
          detail=f"client {empreinte['keycloak']['client_id']} — flow à la connexion, puis contrôle par l'API")
    lien('infra:groups', 'infra:keycloak', 'flow', 'se connectent')
    if frontend:
        noeud('infra:frontend', 'frontend', 'overview', 'Interface Angular', opens='architecture',
              detail=empreinte['paths']['frontend'] or '', count=len(_dicts(spec.get('pages'))))
        lien('infra:keycloak', 'infra:frontend', 'flow', 'jeton')
    if backend:
        noeud('infra:api', 'api', 'overview', 'API Django', opens='architecture',
              detail=empreinte['paths']['api'] or '', count=len(conformite.endpoints(spec)))
        lien('infra:frontend' if frontend else 'infra:keycloak', 'infra:api', 'flow',
             'appels avec jeton' if frontend else 'jeton')
        noeud('infra:database', 'database', 'overview', 'Base PostgreSQL', opens='data',
              detail=f"schéma {empreinte['database']['schema']}" if empreinte['database'] else '',
              count=len(_dicts(spec.get('data_models'))))
        lien('infra:api', 'infra:database', 'flow', 'lit et écrit')
        if empreinte['storage']['used']:
            noeud('infra:storage', 'storage', 'overview', 'Service storage du lab',
                  detail=', '.join(empreinte['storage']['fields']), count=len(empreinte['storage']['fields']))
            lien('infra:api', 'infra:storage', 'flow', 'fichiers des utilisateurs')
        if empreinte['email']['used']:
            noeud('infra:email', 'email', 'overview', 'Email', detail='send_mail, compte réglé dans lab-admin')
            lien('infra:api', 'infra:email', 'flow', 'envoie')
    racine_api = 'infra:api' if backend else None
    racine_ui = 'infra:frontend' if frontend else None

    for r in _dicts(spec.get('business_rules')):
        titre = _nom(r.get('title'))
        if titre and noeud(f'rule:{titre}', 'business_rule', 'overview', titre, racine_api or racine_ui,
                           detail=remise._ligne(r.get('description'), 300)):
            lien(racine_api or racine_ui, f'rule:{titre}', 'contains')

    # ── Données ───────────────────────────────────────────────────────────────
    modeles = _dicts(spec.get('data_models'))
    for m in modeles:
        nom = _nom(m.get('name'))
        champs = _dicts(m.get('fields'))
        if nom and noeud(f'model:{nom}', 'data_model', 'data', nom, 'infra:database' if backend else None,
                         detail=remise._ligne(m.get('description'), 300), count=len(champs),
                         fields=[{'name': _nom(f.get('name')), 'type': _nom(f.get('type')) or 'string'} for f in champs]):
            lien('infra:database', f'model:{nom}', 'contains')
    for m in modeles:
        for r in _dicts(m.get('relationships')):
            lien(f"model:{_nom(m.get('name'))}", f"model:{_nom(r.get('to_model'))}", 'relation',
                 f"{_nom(r.get('name'))} ({_nom(r.get('rel_type')) or 'FK'})")

    # ── Architecture ──────────────────────────────────────────────────────────
    groupes_par_id = {}
    for g in _dicts(spec.get('endpoint_groups')):
        nom = _nom(g.get('name'))
        points = _dicts(g.get('endpoints'))
        if not nom or not noeud(f'group:{nom}', 'endpoint_group', 'architecture', nom, racine_api,
                                detail=remise._ligne(g.get('description'), 300), count=len(points)):
            continue
        groupes_par_id[g.get('id')] = nom
        lien(racine_api, f'group:{nom}', 'contains')
        for e in points:
            route = remise._route(e)
            ident = f'endpoint:{nom}/{route}'
            if noeud(ident, 'endpoint', 'architecture', route, f'group:{nom}',
                     detail=remise._ligne(e.get('description'), 300), public=e.get('auth_required') is False,
                     roles=remise._noms(e.get('required_roles'))):
                lien(f'group:{nom}', ident, 'contains')
                lien(ident, f"model:{_nom(e.get('linked_model_name'))}", 'reads')

    services_par_id = {}
    for s in _dicts(spec.get('services')):
        nom = _nom(s.get('name'))
        if not nom or not noeud(f'service:{nom}', 'service', 'architecture', nom, racine_ui):
            continue
        services_par_id[s.get('id')] = nom
        lien(racine_ui, f'service:{nom}', 'contains')
        for i in s.get('endpoint_group_ids') if isinstance(s.get('endpoint_group_ids'), list) else []:
            if i in groupes_par_id:
                lien(f'service:{nom}', f'group:{groupes_par_id[i]}', 'calls')

    for p in _dicts(spec.get('pages')):
        nom = _nom(p.get('name'))
        pipelines = _dicts(p.get('pipelines'))
        if not nom or not noeud(f'page:{nom}', 'page', 'architecture', nom, racine_ui, opens='pipelines',
                                detail=_nom(p.get('route')), count=len(pipelines)):
            continue
        lien(racine_ui, f'page:{nom}', 'contains')
        for i in p.get('service_ids') if isinstance(p.get('service_ids'), list) else []:
            if i in services_par_id:
                lien(f'page:{nom}', f'service:{services_par_id[i]}', 'uses')
        for c in _dicts(p.get('components')):
            lien(f'page:{nom}', f"model:{_nom(c.get('linked_model'))}", 'reads')

        # ── Pipelines ─────────────────────────────────────────────────────────
        for i in _dicts(p.get('interactions')):
            titre = _nom(i.get('name'))
            if titre and noeud(f'interaction:{nom}/{titre}', 'interaction', 'pipelines', titre, f'page:{nom}',
                               detail=_nom(i.get('type'))):
                lien(f'page:{nom}', f'interaction:{nom}/{titre}', 'contains')
        for pl in pipelines:
            titre = _nom(pl.get('name'))
            etapes = _dicts(pl.get('steps'))
            ident = f'pipeline:{nom}/{titre}'
            if not titre or not noeud(ident, 'pipeline', 'pipelines', titre, f'page:{nom}',
                                      detail=remise._ligne(pl.get('description'), 300), count=len(etapes)):
                continue
            lien(f'page:{nom}', ident, 'contains')
            lien(f"interaction:{nom}/{_nom(pl.get('trigger_interaction'))}", ident, 'triggers')
            precedent = None
            for rang, st in enumerate(etapes):
                etape = f'step:{nom}/{titre}/{rang}'
                noeud(etape, 'step', 'pipelines', _nom(st.get('label')) or f'étape {rang + 1}', ident,
                      detail=_nom(st.get('type')), order=rang)
                lien(ident, etape, 'contains')
                lien(precedent, etape, 'next')
                lien(etape, f"service:{_nom(st.get('service_name'))}", 'invokes')
                precedent = etape

    # ── Feuille de route ──────────────────────────────────────────────────────
    cibles = {'data_model': 'model:{name}', 'endpoint_group': 'group:{name}', 'business_rule': 'rule:{name}',
              'service': 'service:{name}', 'page': 'page:{name}', 'pipeline': 'pipeline:{page}/{name}'}
    for lot in lots:
        ident = f"lot:{lot['number']}"
        noeud(ident, 'lot', 'roadmap', f"Lot {lot['number']} — {lot['title']}", detail=lot['objective'],
              family=lot['family'], tokens=lot['tokens'], order=lot['number'])
        for e in lot['elements']:
            lien(ident, cibles[e['kind']].format(name=e['name'], page=e.get('page', '')), 'builds')
    for lot in lots[1:]:
        lien(f"lot:{lot['number'] - 1}", f"lot:{lot['number']}", 'next')

    return {'scales': [dict(e) for e in ECHELLES], 'nodes': noeuds, 'links': liens}
