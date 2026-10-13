"""Conformité d'une spécification au cadriciel du lab.

Une spécification est « prête » quand le moteur du lab saurait créer l'app
qu'elle décrit sans rien contredire de ses règles : type constructible, nom de
projet bien formé, groupes requis, aucun fichier stocké hors du service
`storage`, aucune référence morte.

Tout ici est calculé à partir de la spec sérialisée (celle que rend
`AppSpecSerializer`), sans base ni réseau : mêmes fonctions pour l'éditeur,
pour l'API de remise au lab et pour les tests.
"""
import re

# Types que `create_app` (moteur du lab) sait créer. L'ordre est celui de l'interface.
TYPES_CONSTRUCTIBLES = ('django-angular', 'django', 'angular')

# Types de champ d'un modèle. `storage_file` : un fichier déposé par l'utilisateur
# dans le service `storage` du lab — le modèle n'en garde que le chemin.
TYPES_DE_CHAMP = ('string', 'text', 'int', 'decimal', 'bool', 'datetime', 'json', 'storage_file')
# Ancien type « fichier » (FileField / blob) : contraire à la règle du lab. Une
# spec qui en porte encore reste lisible ; il ne peut plus être introduit.
TYPE_FICHIER_ANCIEN = 'file'

# Règle 1 de scripts/check-app-name.sh (la forme seulement : l'unicité et les
# noms réservés sont vérifiés par le moteur au moment de créer).
_NOM_DE_PROJET = re.compile(r'^[a-z][a-z0-9-]{1,38}[a-z0-9]$')


def erreur_nom_de_projet(nom) -> str | None:
    """`None` si `nom` a la forme d'un nom de projet du lab, sinon la raison."""
    if not isinstance(nom, str) or not _NOM_DE_PROJET.match(nom):
        return ('Le nom de projet fait 3 à 40 caractères : minuscules, chiffres et tirets, '
                'commence par une lettre et ne finit pas par un tiret.')
    if '--' in nom:
        return 'Le nom de projet ne contient pas deux tirets de suite.'
    return None


def a_un_backend(app_type) -> bool:
    return app_type in ('django-angular', 'django')


def a_un_frontend(app_type) -> bool:
    return app_type in ('django-angular', 'angular')


def _liste(v):
    return v if isinstance(v, list) else []


def _dicts(v):
    return [x for x in _liste(v) if isinstance(x, dict)]


def _champs_de_type(spec: dict, type_de_champ: str) -> list[str]:
    return [f"{m.get('name')}.{f.get('name')}"
            for m in _dicts(spec.get('data_models'))
            for f in _dicts(m.get('fields')) if f.get('type') == type_de_champ]


def champs_fichier_anciens(spec: dict) -> list[str]:
    """« Modele.champ » de chaque champ encore de type `file`."""
    return _champs_de_type(spec, TYPE_FICHIER_ANCIEN)


def champs_storage(spec: dict) -> list[str]:
    """« Modele.champ » de chaque champ référençant un fichier du service `storage`."""
    return _champs_de_type(spec, 'storage_file')


def endpoints(spec: dict) -> list[dict]:
    """Tous les endpoints, chacun avec le nom de son groupe sous `group`."""
    return [{**e, 'group': g.get('name')}
            for g in _dicts(spec.get('endpoint_groups')) for e in _dicts(g.get('endpoints'))]


def routes_publiques(spec: dict) -> list[dict]:
    """Endpoints sans authentification : [{method, path, group, reason}]."""
    return [{'method': e.get('method'), 'path': e.get('path'), 'group': e['group'],
             'reason': (e.get('public_reason') or '').strip()}
            for e in endpoints(spec) if e.get('auth_required') is False]


def references_orphelines(spec: dict) -> list[str]:
    """Références vers un élément absent de la spec, en phrases, triées."""
    from . import patching  # import tardif : patching importe les sérialiseurs, qui importent ce module
    return sorted(patching._orphelins(patching._vers_noms(spec)))


def blocages(spec: dict) -> list[dict]:
    """Ce qui empêche de lancer la construction : [{code, message}], vide si rien.

    Codes (liste fermée, partagée avec lab-admin) : `project_name`, `app_type`,
    `required_groups`, `empty`, `file_field`, `orphan_reference`. Le code
    `context_budget` est ajouté par `remise.blocages`, qui a besoin des lots générés.
    """
    resultat = []

    def bloque(code, message):
        resultat.append({'code': code, 'message': message})

    nom = spec.get('project_name') or ''
    if not nom:
        bloque('project_name', "Le nom de projet n'est pas encore choisi.")
    elif erreur_nom_de_projet(nom):
        bloque('project_name', f'Nom de projet « {nom} » refusé. {erreur_nom_de_projet(nom)}')

    if spec.get('app_type') not in TYPES_CONSTRUCTIBLES:
        bloque('app_type', f"Le lab ne sait pas créer une app de type « {spec.get('app_type')} » : "
                           'choisissez Django + Angular, Django seul ou Angular seul.')

    if not [g for g in _liste(spec.get('required_groups')) if isinstance(g, str) and g.strip()]:
        bloque('required_groups', "Aucun groupe requis : l'app serait ouverte à tout compte du lab.")

    if not (_dicts(spec.get('data_models')) or _dicts(spec.get('pages')) or endpoints(spec)):
        bloque('empty', 'La spécification ne décrit encore ni modèle, ni endpoint, ni page.')

    anciens = champs_fichier_anciens(spec)
    if anciens:
        bloque('file_field', 'Champ(s) de type fichier à convertir en référence au service storage : '
                             + ', '.join(anciens) + '.')

    orphelines = references_orphelines(spec)
    if orphelines:
        phrase = ' ; '.join(orphelines[:3]) + (f' ; et {len(orphelines) - 3} autre(s)' if len(orphelines) > 3 else '')
        bloque('orphan_reference', 'Référence(s) vers un élément absent : ' + phrase + '.')
    return resultat


def empreinte(spec: dict) -> dict:
    """Ce que l'app occupera dans le lab une fois créée par le moteur.

    Reprend ce que posent `new-app.sh` et `create-app-client.sh` : conteneurs,
    chemins Caddy, client Keycloak et ses deux verrous, base, storage, email.
    """
    nom = spec.get('project_name') or ''
    valide = bool(nom) and erreur_nom_de_projet(nom) is None
    app_type = spec.get('app_type')
    affiche = nom if valide else '<nom-de-projet>'
    groupes = [g for g in _liste(spec.get('required_groups')) if isinstance(g, str) and g.strip()]

    if app_type == 'django-angular':
        conteneurs = [{'name': f'{affiche}-backend', 'role': 'API Django (gunicorn)'},
                      {'name': f'{affiche}-frontend', 'role': 'Interface Angular (nginx)'}]
        chemins = {'frontend': f'/{affiche}', 'api': f'/{affiche}-api'}
    elif app_type == 'django':
        conteneurs = [{'name': f'{affiche}-app', 'role': 'API Django (gunicorn)'}]
        chemins = {'frontend': None, 'api': f'/{affiche}'}
    elif app_type == 'angular':
        conteneurs = [{'name': f'{affiche}-app', 'role': 'Interface Angular (nginx)'}]
        chemins = {'frontend': f'/{affiche}', 'api': None}
    else:
        conteneurs, chemins = [], {'frontend': None, 'api': None}

    stockage = champs_storage(spec)
    return {
        'project_name': nom,
        'project_name_valid': valide,
        'app_type': app_type,
        'constructible': app_type in TYPES_CONSTRUCTIBLES,
        'containers': conteneurs,
        'paths': chemins,
        'keycloak': {
            'client_id': affiche,
            'required_groups': groupes,
            'locks': [
                f'Flow Keycloak « require-{affiche} » : refuse à la connexion qui n\'est dans aucun groupe requis.',
                'API : `api/authentication.py` vérifie que le jeton vient de ce client (`azp`) et que ses '
                '`groups` croisent `KEYCLOAK_REQUIRED_GROUPS`.' if a_un_backend(app_type) else
                "Pas d'API propre : aucune donnée n'est servie par cette app.",
            ],
        },
        'database': ({'instance': 'postgres', 'database': 'base du propriétaire (dev_<uid>)',
                      'schema': affiche.replace('-', '_') if valide else '<nom_de_projet>',
                      'tables': len(_dicts(spec.get('data_models')))}
                     if a_un_backend(app_type) else None),
        'storage': {'used': bool(stockage), 'fields': stockage, 'legacy_file_fields': champs_fichier_anciens(spec),
                    'rule': "Fichiers des utilisateurs : par l'API du service storage du lab, jamais de volume "
                            'média ni de blob en base ; le modèle garde le chemin.'},
        'email': {'used': bool(spec.get('uses_email')),
                  'rule': 'Envoi par `send_mail` de Django ; le compte SMTP se règle dans lab-admin '
                          '(carte « Email » du projet).'},
        'public_routes': routes_publiques(spec),
        'deployment': 'Créée et déployée par le moteur du lab (lab-admin → Projets) : seul un commit '
                      'poussé sur GitHub est déployé, après les tests backend.',
    }
