import logging
import time

import requests as http_requests  # noqa: F401 — gardé : des tests y vérifient qu'aucun appel ne part
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import budget, conformite, patching
from .ia import boucle, fournisseurs
from .models import AiKeyVault, AppSpec, PatchApplication
from .serializers import AppSpecSerializer

log = logging.getLogger(__name__)

# ── Vues ───────────────────────────────────────────────────────────────────────

class MeView(APIView):
    def get(self, request):
        return Response({
            'email':    request.user.email,
            'username': request.user.username,
            'groups':   request.user.claims.get('groups', []),
        })


class AppSpecListCreateView(generics.ListCreateAPIView):
    serializer_class = AppSpecSerializer

    def get_queryset(self):
        return AppSpec.objects.filter(owner_email=self.request.user.email)

    def perform_create(self, serializer):
        serializer.save(owner_email=self.request.user.email)


class AppSpecDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AppSpecSerializer

    def get_queryset(self):
        return AppSpec.objects.filter(owner_email=self.request.user.email)

    def retrieve(self, request, *args, **kwargs):
        # `version` (I4) : lue ici, pas dans le sérialiseur — elle sert de
        # `base_version` aux opérations (409 si la spec a changé entre-temps).
        app = self.get_object()
        return Response({**self.get_serializer(app).data, 'version': patching.version_de(app)})


def _spec_de_l_appelant(request, pk):
    """La spec `pk` si elle appartient à l'appelant, sinon None (⇒ 404)."""
    try:
        return AppSpec.objects.get(pk=int(pk), owner_email=request.user.email)
    except (AppSpec.DoesNotExist, TypeError, ValueError):
        return None


_TROP_LONG = ("La spécification et la conversation dépassent ce que le modèle « {modele} » peut traiter "
              "(environ {total} jetons pour {disponible} disponibles). Choisissez un modèle à plus grande "
              "fenêtre, effacez la conversation, ou réduisez la spécification.")
_INTROUVABLE = {'error': 'Spécification introuvable.'}


def _preparer(donnees, spec: dict) -> dict:
    """Ce qui partirait vers le fournisseur pour cette demande, et ce que ça pèse.
    `spec` est lue EN BASE par l'appelant ; `app_spec` du corps n'est jamais lu."""
    donnees = donnees if isinstance(donnees, dict) else {}
    provider = budget.fournisseur(donnees.get('provider', 'claude'))
    model = donnees.get('model')
    model = (model.strip() or None) if isinstance(model, str) else None
    fiche = budget.modele(provider, model)
    tous = budget.nettoyer(donnees.get('messages'))
    vide = boucle.mesure(fiche, spec, [])
    place = vide['available_tokens'] - vide['system_tokens']
    messages, retires = budget.borner(tous, place)
    return {'provider': provider, 'model': fiche['id'], 'fiche': fiche, 'messages': messages,
            'context': boucle.mesure(fiche, spec, messages, retires)}


def _spec_de_la_demande(request):
    """(app, spec) d'après `app_id` du corps ; (None, None) si absente ou d'autrui."""
    donnees = request.data if isinstance(request.data, dict) else {}
    app = _spec_de_l_appelant(request, donnees.get('app_id'))
    return (app, patching.spec_de(app)) if app else (None, None)


class ModelsView(APIView):
    """GET /api/models/ — les modèles proposés et ce que chacun peut tenir."""

    def get(self, request):
        return Response(budget.catalogue())


class ChatEstimateView(APIView):
    """POST /api/chat/estimate/ — la place qu'occuperait un envoi, sans rien envoyer.
    Même corps que /api/chat/, sans clé d'API. Aucun appel à un fournisseur. Sans
    `app_id` : estimation pour une spec vide ; `app_id` d'autrui ou inconnu : 404."""

    def post(self, request):
        donnees = request.data if isinstance(request.data, dict) else {}
        if donnees.get('app_id') is None:
            spec = {}
        else:
            app, spec = _spec_de_la_demande(request)
            if app is None:
                return Response(_INTROUVABLE, status=status.HTTP_404_NOT_FOUND)
        return Response({'context': _preparer(request.data, spec)['context']})


# ── Coffre des clés d'API (contrat « failles », I3) ───────────────────────────

_VAULT_FIELDS = {'claude_key': 'claude', 'mistral_key': 'mistral'}
_KEY_MAX_LEN = 512


def cle_du_coffre(email: str, provider: str) -> str:
    """La clé `provider` du compte `email`, '' si elle n'est pas configurée."""
    coffre = AiKeyVault.objects.filter(owner_email=email).first()
    if not coffre:
        return ''
    return (coffre.claude_key if provider == 'claude' else coffre.mistral_key) or ''


class AiKeysView(APIView):
    """GET /api/ai-keys/ → {"claude_key_configured": bool, "mistral_key_configured": bool}
    — jamais la valeur, ni un extrait.
    PUT /api/ai-keys/ {"claude_key": "…"} et/ou {"mistral_key": "…"} → 204 ;
    chaîne vide ⇒ la clé est supprimée ; champ absent ⇒ inchangée."""

    def get(self, request):
        coffre = AiKeyVault.objects.filter(owner_email=request.user.email).first()
        return Response({f'{champ}_configured': bool(coffre and getattr(coffre, champ))
                         for champ in _VAULT_FIELDS})

    def put(self, request):
        donnees = request.data if isinstance(request.data, dict) else None
        if not donnees:
            return Response({'error': 'Corps attendu : {"claude_key": "…"} et/ou {"mistral_key": "…"}.'},
                            status=status.HTTP_400_BAD_REQUEST)
        inconnus = sorted(set(donnees) - set(_VAULT_FIELDS))
        if inconnus:
            return Response({'error': f'Champ(s) inconnu(s) : {", ".join(inconnus)}.'},
                            status=status.HTTP_400_BAD_REQUEST)
        valeurs = {}
        for champ, valeur in donnees.items():
            if not isinstance(valeur, str):
                return Response({'error': f'{champ} : une chaîne est attendue.'}, status=status.HTTP_400_BAD_REQUEST)
            valeur = valeur.strip()
            if len(valeur) > _KEY_MAX_LEN or any(c.isspace() or not c.isprintable() for c in valeur):
                return Response({'error': f'{champ} : clé mal formée.'}, status=status.HTTP_400_BAD_REQUEST)
            if valeur.startswith('sk-ant-oat'):
                # Jeton d'abonnement Claude (`claude setup-token`) : les conditions d'Anthropic
                # interdisent à une application tierce de le stocker ou de s'en servir.
                return Response({'error': "Jeton d'abonnement Claude : utilisez-le dans Claude Code (par le MCP "
                                          "d'App Builder), pas ici. Ce coffre attend une clé d'API (sk-ant-api…).",
                                 'code': 'oauth_token_refused'}, status=status.HTTP_400_BAD_REQUEST)
            valeurs[champ] = valeur
        coffre, _ = AiKeyVault.objects.get_or_create(owner_email=request.user.email)
        for champ, valeur in valeurs.items():
            setattr(coffre, champ, valeur)
        coffre.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AIChatView(APIView):
    """POST /api/chat/ — un tour de conversation avec outils (I4).

    La spec est lue EN BASE (`app_id`, spec de l'appelant, sinon 404) ; `app_spec`
    du corps est ignoré. La clé est celle du coffre de l'appelant (`/api/ai-keys/`) ;
    un `api_key` du corps est ignoré. Les opérations proposées ne sont jamais
    appliquées ici : l'utilisateur les applique (`POST /api/apps/<id>/operations/`)."""

    def post(self, request):
        debut = time.monotonic()
        app, spec = _spec_de_la_demande(request)
        if app is None:
            return Response(_INTROUVABLE, status=status.HTTP_404_NOT_FOUND)
        envoi = _preparer(request.data, spec)
        provider, fiche, messages, contexte = envoi['provider'], envoi['fiche'], envoi['messages'], envoi['context']
        api_key = cle_du_coffre(request.user.email, provider)
        # Journal : des comptes, jamais de contenu (ni spec, ni message, ni clé).
        log.info('Chat : spec=%s provider=%s modèle=%s messages=%d jetons≈%d/%d', app.pk, provider, fiche['id'],
                 len(messages), contexte['estimated_tokens'], contexte['available_tokens'])
        if not api_key:
            return Response(
                {'error': f'Clé API {provider} non configurée. Enregistrez-la dans les paramètres (⚙).',
                 'code': 'key_not_configured'},
                status=status.HTTP_400_BAD_REQUEST)
        if not messages:
            return Response({'error': 'Aucun message à envoyer.', 'context': contexte},
                            status=status.HTTP_400_BAD_REQUEST)
        trop_long = Response(
            {'error': _TROP_LONG.format(modele=contexte['model'], total=contexte['estimated_tokens'],
                                        disponible=max(contexte['available_tokens'], 0)),
             'code': 'context_too_large', 'context': contexte},
            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        # Refus AVANT l'appel : une requête qui ne tient pas est perdue d'avance.
        if not contexte['fits']:
            return trop_long
        try:
            tour = boucle.tour(fiche=fiche, cle=api_key, spec=spec, messages=messages,
                               base_version=patching.version_de(app), debut=debut)
        except fournisseurs.ErreurFournisseur as exc:
            if exc.depassement:
                return trop_long
            log.warning('Chat : fournisseur %s en échec (%d).', provider, exc.statut)
            return Response({'error': exc.message}, status=exc.statut)
        contexte = {**contexte, 'tool_results_tokens': tour['tool_results_tokens']}
        return Response({'content': tour['content'], 'provider': provider, 'model': fiche['id'],
                         'choices': tour['choices'], 'proposal': tour['proposal'],
                         'truncated': tour['truncated'], 'context': contexte, 'usage': tour['usage']})


class AppSpecChatHistoryView(APIView):
    """PATCH /api/apps/<id>/chat/ {"chat_history": [...]} — une liste, sinon 400."""

    def patch(self, request, pk):
        app = _spec_de_l_appelant(request, pk)
        if app is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        donnees = request.data if isinstance(request.data, dict) else {}
        historique = donnees.get('chat_history', [])
        if not isinstance(historique, list):
            return Response({'error': 'chat_history : une liste est attendue.'}, status=status.HTTP_400_BAD_REQUEST)
        app.chat_history = historique
        app.save(update_fields=['chat_history'])
        return Response({'ok': True})


def _operations_du_corps(request):
    donnees = request.data if isinstance(request.data, dict) else {}
    operations = donnees.get('operations')
    if (not isinstance(operations, list) or not operations or len(operations) > 200
            or not all(isinstance(o, dict) for o in operations)):
        return None, donnees
    return operations, donnees


class AppSpecOperationsView(APIView):
    """POST /api/apps/<id>/operations/ {"operations": [...], "base_version": "v:…"} — applique (I4).
    Tout ou rien ; 409 `version_perimee` si la spec a changé depuis `base_version`."""

    def post(self, request, pk):
        app = _spec_de_l_appelant(request, pk)
        if app is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        operations, donnees = _operations_du_corps(request)
        if operations is None:
            return Response({'error': 'Corps attendu : {"operations": [...], "base_version": "v:…"}.',
                             'erreurs': ['operations : une liste non vide d’objets est attendue.']},
                            status=status.HTTP_400_BAD_REQUEST)
        base = donnees.get('base_version')
        base = base if isinstance(base, str) and base else None
        try:
            application = patching.appliquer_operations(app, operations, base)
        except patching.VersionPerimee:
            app.refresh_from_db()
            return Response({'error': 'La spécification a changé depuis cette proposition : relisez-la.',
                             'code': 'version_perimee', 'version': patching.version_de(app)},
                            status=status.HTTP_409_CONFLICT)
        except patching.PatchRefuse as refus:
            return Response({'error': 'Opérations refusées — la spécification n’a pas été modifiée.',
                             'erreurs': list(refus.erreurs)}, status=status.HTTP_400_BAD_REQUEST)
        app.refresh_from_db()
        return Response({'application': _application(application), 'version': patching.version_de(app),
                         'spec': AppSpecSerializer(app).data})


class AppSpecOperationsEssaiView(APIView):
    """POST /api/apps/<id>/operations/essai/ {"operations": [...]} — essai à blanc, rien d'écrit (I4)."""

    def post(self, request, pk):
        app = _spec_de_l_appelant(request, pk)
        if app is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        operations, _ = _operations_du_corps(request)
        if operations is None:
            return Response({'ok': False, 'erreurs': ['operations : une liste non vide d’objets est attendue.'],
                             'resume': None})
        avant = patching.spec_de(app)
        try:
            apres = patching.essayer_operations(avant, operations)
        except patching.PatchRefuse as refus:
            return Response({'ok': False, 'erreurs': list(refus.erreurs), 'resume': None})
        return Response({'ok': True, 'erreurs': [], 'resume': patching.resume_operations(avant, operations, apres)})


class AppSpecPatchView(APIView):
    """POST /api/apps/<id>/patch/ — applique un patch IA à la spec en base.

    Tout ou rien : un patch refusé (illisible, référence vers un élément
    absent, valeur invalide) laisse la spec intacte et dit pourquoi.
    """

    def post(self, request, pk):
        try:
            app = AppSpec.objects.get(pk=pk, owner_email=request.user.email)
        except AppSpec.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        mode = request.data.get('mode', 'merge')
        try:
            application = patching.appliquer(app, request.data.get('patch'), mode)
        except patching.PatchRefuse as refus:
            return Response({'error': 'Patch refusé — la spécification n\'a pas été modifiée.',
                             'details': refus.erreurs}, status=status.HTTP_400_BAD_REQUEST)
        app.refresh_from_db()
        return Response({'spec': AppSpecSerializer(app).data, 'application': _application(application)})


def _application(a: PatchApplication) -> dict:
    return {'id': a.pk, 'mode': a.mode, 'summary': a.summary,
            'created_at': a.created_at, 'undone_at': a.undone_at}


class AppSpecPatchHistoryView(APIView):
    """GET /api/apps/<id>/patches/ — patchs appliqués, du plus récent au plus ancien."""

    def get(self, request, pk):
        try:
            app = AppSpec.objects.get(pk=pk, owner_email=request.user.email)
        except AppSpec.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response([_application(a) for a in app.patch_applications.all()])


class AppSpecPatchUndoView(APIView):
    """POST /api/apps/<id>/patches/<n>/undo/ — rend la spec d'avant le dernier patch."""

    def post(self, request, pk, application_pk):
        try:
            application = PatchApplication.objects.get(
                pk=application_pk, app_id=pk, app__owner_email=request.user.email)
        except PatchApplication.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            patching.annuler(application)
        except patching.AnnulationImpossible as exc:
            return Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)
        except patching.PatchRefuse as refus:
            return Response({'error': 'Annulation impossible.', 'details': refus.erreurs},
                            status=status.HTTP_400_BAD_REQUEST)
        application.refresh_from_db()
        return Response({'spec': AppSpecSerializer(application.app).data,
                         'application': _application(application)})


class AppSpecLabView(APIView):
    """GET /api/apps/<id>/lab/ — la spécification vue du lab : est-elle prête à
    être construite, sinon pourquoi, et ce qu'elle occupera une fois créée."""

    def get(self, request, pk):
        try:
            app = AppSpec.objects.get(pk=pk, owner_email=request.user.email)
        except AppSpec.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        spec = patching.spec_de(app)
        blocages = conformite.blocages(spec)
        return Response({'ready': not blocages, 'blockers': blocages,
                         'footprint': conformite.empreinte(spec)})
