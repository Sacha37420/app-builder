"""Serveur MCP d'App Builder et jetons personnels (I5 du chantier app-builder-v2).

Un Claude Code ou un Mistral Vibe pilote une spécification avec SON abonnement :
App Builder n'expose que des outils, sans boucle ni appel à une IA. C'est le
client qui raisonne et qui paie.

- Gestion des jetons (`/api/mcp-tokens/`, `/api/mcp/info/`) : serrure Keycloak
  ordinaire (azp + groupes), comme tout le reste de l'API.
- Point MCP (`POST /api/mcp/`) : JSON-RPC 2.0 en « streamable HTTP » sans SSE et
  sans état. N'accepte QUE `Authorization: Bearer abt_…` (McpTokenAuthentication) ;
  un jeton Keycloak y est refusé, et un `abt_` est refusé partout ailleurs (ce
  n'est pas un JWT).
- Un jeton n'agit que sur les specs de son propriétaire, et sur la seule spec à
  laquelle il est lié s'il l'est ; portée `lire` ⇒ aucun outil d'écriture.
- Journal : nom d'outil, email, spec — jamais les arguments ni le jeton.
"""
import hashlib
import json
import logging
import secrets
from datetime import timedelta

from decouple import config
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import MethodNotAllowed, ParseError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import conformite, lecture, patching, remise
from .authentication import McpTokenAuthentication, McpUser
from .ia.prompt import REGLES
from .models import AppSpec, McpToken, PatchApplication
from .serializers import AppSpecSerializer

log = logging.getLogger(__name__)

PORTEES = ('lire', 'ecrire')
JOURS_DEFAUT, JOURS_MAX = 30, 90
NOM_SERVEUR = 'app-builder'
VERSIONS_PROTOCOLE = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')


# ── Adresse publique ──────────────────────────────────────────────────────────

def url_publique() -> str:
    """`https://<DOMAIN><SCRIPT_NAME>/api/mcp/` — variables existantes du .env.
    Sans domaine (HTTP local) : `BACKEND_URL` (adresse directe du backend)."""
    domaine = (config('DOMAIN', default='') or '').strip()
    prefixe = (settings.FORCE_SCRIPT_NAME or '').rstrip('/')
    if domaine and domaine != 'CHANGE_ME':
        return f'https://{domaine}{prefixe}/api/mcp/'
    base = (config('BACKEND_URL', default='') or 'http://localhost:8000').rstrip('/')
    return f'{base}/api/mcp/'


# ── Gestion des jetons (serrure Keycloak) ─────────────────────────────────────

def _jeton_public(j: McpToken) -> dict:
    return {'id': j.pk, 'name': j.name, 'prefix': j.prefix, 'scope': j.scope, 'spec_id': j.spec_id,
            'created_at': j.created_at, 'expires_at': j.expires_at, 'last_used_at': j.last_used_at,
            'revoked': j.revoked_at is not None}


class McpTokenListCreateView(APIView):
    """GET /api/mcp-tokens/ — mes jetons ; POST {name, scope, spec_id?, days?} — 201 + `token` une seule fois."""

    def get(self, request):
        return Response([_jeton_public(j) for j in
                         McpToken.objects.filter(owner_email=request.user.email).order_by('-created_at')])

    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        nom = d.get('name')
        if not isinstance(nom, str) or not nom.strip() or len(nom.strip()) > 80:
            return Response({'error': 'name : 1 à 80 caractères.'}, status=status.HTTP_400_BAD_REQUEST)
        portee = d.get('scope', 'lire')
        if portee not in PORTEES:
            return Response({'error': 'scope : « lire » ou « ecrire ».'}, status=status.HTTP_400_BAD_REQUEST)
        jours = d.get('days', JOURS_DEFAUT)
        if isinstance(jours, bool) or not isinstance(jours, int) or not 1 <= jours <= JOURS_MAX:
            return Response({'error': f'days : entier de 1 à {JOURS_MAX}.'}, status=status.HTTP_400_BAD_REQUEST)
        spec = None
        if d.get('spec_id') is not None:
            spec = AppSpec.objects.filter(pk=d['spec_id'] if isinstance(d['spec_id'], int) else -1,
                                          owner_email=request.user.email).first()
            if spec is None:
                return Response({'error': 'spec_id : spécification introuvable.'}, status=status.HTTP_400_BAD_REQUEST)
        valeur = 'abt_' + secrets.token_urlsafe(32)          # 43 caractères après le préfixe
        jeton = McpToken.objects.create(
            owner_email=request.user.email, name=nom.strip(), prefix=valeur[:12],
            token_hash=hashlib.sha256(valeur.encode()).hexdigest(), scope=portee, spec=spec,
            expires_at=timezone.now() + timedelta(days=jours))
        log.info('MCP : jeton %s créé par %s (portée %s).', jeton.prefix, request.user.email, portee)
        return Response({**_jeton_public(jeton), 'token': valeur}, status=status.HTTP_201_CREATED)


class McpTokenDetailView(APIView):
    """DELETE /api/mcp-tokens/<id>/ — révoque (204) ; jeton d'autrui ou inconnu : 404."""

    def delete(self, request, pk):
        jeton = McpToken.objects.filter(pk=pk, owner_email=request.user.email).first()
        if jeton is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if jeton.revoked_at is None:
            jeton.revoked_at = timezone.now()
            jeton.save(update_fields=['revoked_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class McpInfoView(APIView):
    """GET /api/mcp/info/ — l'adresse et les commandes à copier (avec `<JETON>` littéral)."""

    def get(self, request):
        url = url_publique()
        return Response({
            'url': url,
            'claude': (f'claude mcp add --scope user --transport http {NOM_SERVEUR} {url} '
                       '--header "Authorization: Bearer <JETON>"'),
            'vibe': ("export APP_BUILDER_MCP_TOKEN='<JETON>' && VIBE_CLI=python vibe mcp add "
                     f"{NOM_SERVEUR} --url {url} --transport streamable-http --api-key-env APP_BUILDER_MCP_TOKEN "
                     "--api-key-header Authorization --api-key-format 'Bearer {token}'"),
        })


# ── Outils MCP ────────────────────────────────────────────────────────────────

INSTRUCTIONS = (REGLES + """

## Méthode avec ce serveur MCP
Tu pilotes une spécification d'App Builder. Commence par lister_specs puis lire_index(spec_id) ; lis le
détail avec lire_elements avant toute modification. Prépare tes changements en opérations, vérifie-les
avec essayer_operations, puis applique-les avec appliquer_operations en passant la `version` rendue par
lire_index (une spec modifiée entre-temps est refusée : relis-la). Pose tes questions à l'utilisateur
toi-même (pas d'outil de choix ici). Toute application est annulable (historique, annuler). Avant de
déclarer la spécification prête, appelle verifier_spec. lire_livrables rend le cahier des charges et la
feuille de route qui seront remis au lab. Une erreur d'outil est un objet JSON {error, detail}.""")

_SPEC = {'spec_id': {'type': 'integer', 'description': 'Identifiant de la spécification (lister_specs).'}}
_OPS = {'operations': {'type': 'array', 'minItems': 1, 'maxItems': 80,
                       'items': {'type': 'object'},
                       'description': 'Opérations atomiques {op, cible, nouveau_nom?, data?} (voir les instructions).'}}

OUTILS = {
    'lister_specs': ('Mes spécifications (id, nom, nom de projet, version).', {}, [], False),
    'creer_spec': ('Crée une spécification vide.', {'name': {'type': 'string'}}, ['name'], True),
    'lire_index': ('Index compact de la spécification, sa version et ses blocages.', _SPEC, ['spec_id'], False),
    'lire_elements': ("Détail JSON d'éléments d'une section (noms vides = toute la section).",
                      {**_SPEC, 'section': {'type': 'string', 'enum': list(lecture.SECTIONS)},
                       'noms': {'type': 'array', 'items': {'type': 'string'}}}, ['spec_id', 'section'], False),
    'verifier_spec': ('Blocages du lab et avertissements de qualité.', _SPEC, ['spec_id'], False),
    'essayer_operations': ('Essai à blanc d’opérations : erreurs ou résumé, rien n’est écrit.',
                           {**_SPEC, **_OPS}, ['spec_id', 'operations'], False),
    'appliquer_operations': ('Applique des opérations (tout ou rien) ; base_version = version lue.',
                             {**_SPEC, **_OPS, 'base_version': {'type': 'string'}},
                             ['spec_id', 'operations', 'base_version'], True),
    'historique': ('Modifications appliquées, de la plus récente à la plus ancienne.', _SPEC, ['spec_id'], False),
    'annuler': ('Annule la dernière modification appliquée.',
                {**_SPEC, 'application_id': {'type': 'integer'}}, ['spec_id', 'application_id'], True),
    'lire_livrables': ('Cahier des charges et feuille de route tels qu’ils seraient remis au lab.',
                       _SPEC, ['spec_id'], False),
}


class ErreurOutil(Exception):
    def __init__(self, error: str, detail, **extra):
        super().__init__(error)
        self.charge = {'error': error, 'detail': detail, **extra}


def _outils_visibles(user: McpUser) -> list[str]:
    jeton = user.jeton
    noms = []
    for nom, (_d, _p, _r, ecriture) in OUTILS.items():
        if ecriture and jeton.scope != 'ecrire':
            continue
        if nom == 'creer_spec' and jeton.spec_id is not None:
            continue
        noms.append(nom)
    return noms


def _liste_outils(user: McpUser) -> list[dict]:
    return [{'name': nom, 'description': OUTILS[nom][0],
             'inputSchema': {'type': 'object', 'properties': OUTILS[nom][1], 'required': OUTILS[nom][2]}}
            for nom in _outils_visibles(user)]


def _specs(user: McpUser):
    qs = AppSpec.objects.filter(owner_email=user.email)
    if user.jeton.spec_id is not None:
        qs = qs.filter(pk=user.jeton.spec_id)
    return qs


def _spec(user: McpUser, args: dict) -> AppSpec:
    sid = args.get('spec_id')
    app = _specs(user).filter(pk=sid).first() if isinstance(sid, int) and not isinstance(sid, bool) else None
    if app is None:
        raise ErreurOutil('introuvable', 'Spécification introuvable (ou hors de la portée de ce jeton).')
    return app


def _operations(args: dict) -> list:
    ops = args.get('operations')
    if not isinstance(ops, list) or not ops or len(ops) > 80 or not all(isinstance(o, dict) for o in ops):
        raise ErreurOutil('arguments', 'operations : une liste de 1 à 80 objets est attendue.')
    return ops


def _application(a: PatchApplication) -> dict:
    return {'id': a.pk, 'mode': a.mode, 'summary': a.summary,
            'created_at': a.created_at.isoformat(), 'undone_at': a.undone_at.isoformat() if a.undone_at else None}


def _executer(nom: str, user: McpUser, args: dict):
    if nom == 'lister_specs':
        return [{'id': a.pk, 'name': a.name, 'project_name': a.project_name, 'version': patching.version_de(a)}
                for a in _specs(user).order_by('-updated_at')]
    if nom == 'creer_spec':
        name = args.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ErreurOutil('arguments', 'name : 1 à 200 caractères.')
        s = AppSpecSerializer(data={'name': name.strip()})
        if not s.is_valid():
            raise ErreurOutil('refus', 'Spécification refusée.')
        app = s.save(owner_email=user.email)
        return {'id': app.pk, 'name': app.name, 'version': patching.version_de(app)}

    app = _spec(user, args)
    if nom == 'lire_index':
        spec = patching.spec_de(app)
        return {'index': lecture.index_spec(spec), 'version': patching.version_de(app),
                'blocages': conformite.blocages(spec)}
    if nom == 'lire_elements':
        section, noms = args.get('section'), args.get('noms') or []
        if section not in lecture.SECTIONS or not isinstance(noms, list) or not all(isinstance(n, str) for n in noms):
            raise ErreurOutil('arguments', 'section inconnue ou noms mal formés.')
        r = lecture.lire_elements(patching.spec_de(app), section, noms)
        if isinstance(r, dict) and r.get('erreur'):
            raise ErreurOutil(r['erreur'], r.get('message', ''))
        return r
    if nom == 'verifier_spec':
        return conformite.verifier(patching.spec_de(app))
    if nom == 'essayer_operations':
        ops = _operations(args)
        avant = patching.spec_de(app)
        try:
            apres = patching.essayer_operations(avant, ops)
        except patching.PatchRefuse as refus:
            return {'ok': False, 'erreurs': list(refus.erreurs), 'resume': None}
        return {'ok': True, 'erreurs': [], 'resume': patching.resume_operations(avant, ops, apres),
                'base_version': patching.version_de(app)}
    if nom == 'appliquer_operations':
        ops = _operations(args)
        base = args.get('base_version')
        if not isinstance(base, str) or not base:
            raise ErreurOutil('arguments', 'base_version : la version lue par lire_index est attendue.')
        try:
            application = patching.appliquer_operations(app, ops, base)
        except patching.VersionPerimee:
            app.refresh_from_db()
            raise ErreurOutil('version_perimee', 'La spécification a changé : relis-la (lire_index).',
                              version=patching.version_de(app))
        except patching.PatchRefuse as refus:
            raise ErreurOutil('refus', list(refus.erreurs))
        app.refresh_from_db()
        return {'application': _application(application), 'version': patching.version_de(app)}
    if nom == 'historique':
        return [_application(a) for a in app.patch_applications.all()]
    if nom == 'annuler':
        aid = args.get('application_id')
        application = (app.patch_applications.filter(pk=aid).first()
                       if isinstance(aid, int) and not isinstance(aid, bool) else None)
        if application is None:
            raise ErreurOutil('introuvable', 'Modification introuvable.')
        try:
            patching.annuler(application)
        except patching.AnnulationImpossible as exc:
            raise ErreurOutil('annulation_impossible', str(exc))
        except patching.PatchRefuse as refus:
            raise ErreurOutil('refus', list(refus.erreurs))
        app.refresh_from_db()
        application.refresh_from_db()
        return {'application': _application(application), 'version': patching.version_de(app)}
    if nom == 'lire_livrables':
        from .handoff import horodatage
        l = remise.livrables(patching.spec_de(app), app.pk, horodatage(app.updated_at))
        return {'ready': l['ready'], 'blockers': l['blockers'],
                'cahier_des_charges_md': l['cahier_des_charges_md'], 'lots_md': l['lots_md']}
    raise ErreurOutil('outil_inconnu', nom)


# ── Point JSON-RPC ────────────────────────────────────────────────────────────

def _rpc_erreur(ident, code: int, message: str) -> dict:
    return {'jsonrpc': '2.0', 'id': ident, 'error': {'code': code, 'message': message}}


def _texte(objet) -> str:
    return json.dumps(objet, ensure_ascii=False, default=str)


class McpView(APIView):
    """POST /api/mcp/ — JSON-RPC 2.0 sans état. Toute autre méthode : 405."""

    authentication_classes = [McpTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        if request.method != 'POST':
            raise MethodNotAllowed(request.method)
        super().initial(request, *args, **kwargs)
        if not isinstance(request.user, McpUser):
            # Défense en profondeur : seule McpTokenAuthentication est branchée ici.
            from rest_framework.exceptions import NotAuthenticated
            raise NotAuthenticated()

    def post(self, request):
        try:
            message = request.data
        except ParseError:
            return Response(_rpc_erreur(None, -32700, 'Parse error'))
        if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str):
            return Response(_rpc_erreur(message.get('id') if isinstance(message, dict) else None,
                                        -32600, 'Invalid Request'))
        methode, ident = message['method'], message.get('id')
        params = message.get('params') if isinstance(message.get('params'), dict) else {}
        if 'id' not in message:          # notification : rien à rendre
            return Response(status=status.HTTP_202_ACCEPTED)
        user = request.user
        if methode == 'initialize':
            demandee = params.get('protocolVersion')
            version = demandee if demandee in VERSIONS_PROTOCOLE else VERSIONS_PROTOCOLE[1]
            return Response({'jsonrpc': '2.0', 'id': ident, 'result': {
                'protocolVersion': version,
                'capabilities': {'tools': {'listChanged': False}},
                'serverInfo': {'name': NOM_SERVEUR, 'version': '2'},
                'instructions': INSTRUCTIONS}})
        if methode == 'ping':
            return Response({'jsonrpc': '2.0', 'id': ident, 'result': {}})
        if methode == 'tools/list':
            return Response({'jsonrpc': '2.0', 'id': ident, 'result': {'tools': _liste_outils(user)}})
        if methode != 'tools/call':
            return Response(_rpc_erreur(ident, -32601, 'Method not found'))

        nom = params.get('name')
        args = params.get('arguments') if isinstance(params.get('arguments'), dict) else {}
        if nom not in OUTILS:
            return Response(_rpc_erreur(ident, -32602, 'Outil inconnu.'))
        spec_journal = args.get('spec_id') if isinstance(args.get('spec_id'), int) else '-'
        log.info('MCP : outil %s par %s (spec %s).', nom, user.email, spec_journal)
        if nom not in _outils_visibles(user):
            charge, erreur = {'error': 'portee', 'detail': 'Ce jeton ne permet pas cet outil (portée « lire » ou '
                                                          'jeton lié à une spécification).'}, True
        else:
            try:
                with transaction.atomic():
                    charge, erreur = _executer(nom, user, args), False
            except ErreurOutil as exc:
                charge, erreur = exc.charge, True
        return Response({'jsonrpc': '2.0', 'id': ident, 'result': {
            'content': [{'type': 'text', 'text': _texte(charge)}], 'isError': erreur}})
