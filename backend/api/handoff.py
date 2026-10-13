"""API de remise au lab — `/api/handoff/…` (contrat « app-builder-lab », interface I1).

Trois routes en lecture seule, appelées par le navigateur d'un utilisateur de
lab-admin avec SON jeton, pour lancer la construction d'une spécification prête.

Ce sont les seules routes d'App Builder qui acceptent un jeton émis pour un
autre client que le sien (`KEYCLOAK_HANDOFF_CLIENTS`). Tout le reste des
contrôles est celui du reste de l'API : signature, email, groupes requis. Un
appelant ne voit que ses propres spécifications ; jamais la conversation, jamais
une clé d'API ; rien ici n'appelle une IA.
"""
from datetime import timezone as tz

from django.conf import settings
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import graphe, patching, remise
from .authentication import AccesRefuse, KeycloakJWTAuthentication
from .models import AppSpec

try:
    from zoneinfo import ZoneInfo
    _FUSEAU = ZoneInfo('Europe/Paris')
except Exception:  # pas de base de fuseaux dans l'image : on rend l'heure en UTC
    _FUSEAU = tz.utc

# Clients intégrés du realm : jamais acceptés, même listés par erreur dans la
# configuration. `admin-cli` est public avec le password grant — l'accepter
# ouvrirait ces routes à tout compte du lab, sans passer par aucun flow.
CLIENTS_INTEGRES = frozenset({'admin-cli', 'account', 'account-console', 'broker',
                              'realm-management', 'security-admin-console'})


def clients_de_remise() -> set[str]:
    autres = {c.strip() for c in settings.KEYCLOAK_HANDOFF_CLIENTS.split(',') if c.strip()}
    return {settings.KEYCLOAK_CLIENT_ID} | (autres - CLIENTS_INTEGRES)


class HandoffAuthentication(KeycloakJWTAuthentication):
    """La même serrure, ouverte à un client de plus, et qui distingue
    « pas de jeton valable » (401) de « jeton valable mais refusé ici » (403)."""

    def _allowed_client_ids(self) -> set[str]:
        return clients_de_remise()

    def authenticate_header(self, request):
        return 'Bearer'

    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except AccesRefuse as refus:
            raise exceptions.PermissionDenied(refus.detail) from refus


def horodatage(instant) -> str:
    """Date de modification telle qu'elle est rendue partout dans la remise
    (et citée dans le cahier des charges) : ISO 8601, à la seconde, avec décalage."""
    return instant.astimezone(_FUSEAU).replace(microsecond=0).isoformat()


def _resume(app: AppSpec) -> tuple[dict, dict]:
    spec = patching.spec_de(app)
    etat_du = horodatage(app.updated_at)
    livrables = remise.livrables(spec, app.pk, etat_du)
    resume = {
        'id': app.pk,
        'name': app.name,
        'project_name': app.project_name,
        'app_type': app.app_type,
        'required_groups': livrables['create']['required_groups'],
        'updated_at': etat_du,
        'ready': livrables['ready'],
        'blockers': livrables['blockers'],
        'counts': livrables['counts'],
    }
    return resume, livrables


class _Remise(APIView):
    authentication_classes = [HandoffAuthentication]
    # Lecture seule : toute autre méthode (HEAD et OPTIONS compris) rend 405.
    http_method_names = ['get']

    def specs(self, request):
        return AppSpec.objects.filter(owner_email=request.user.email)

    def spec(self, request, pk) -> AppSpec:
        try:
            return self.specs(request).get(pk=pk)
        except AppSpec.DoesNotExist:
            # Introuvable ou à quelqu'un d'autre : même réponse.
            raise Http404 from None


class HandoffSpecListView(_Remise):
    """GET /api/handoff/specs/ — les spécifications de l'appelant, la plus récente d'abord."""

    def get(self, request):
        return Response([_resume(app)[0] for app in self.specs(request).order_by('-updated_at', '-pk')])


class HandoffSpecDetailView(_Remise):
    """GET /api/handoff/specs/<id>/ — le résumé, la description et la mesure du contexte."""

    def get(self, request, pk):
        app = self.spec(request, pk)
        resume, livrables = _resume(app)
        return Response({**resume, 'description': app.description, 'context': livrables['context']})


class HandoffKitView(_Remise):
    """GET /api/handoff/specs/<id>/kit/ — de quoi créer le projet : paramètres et graine."""

    def get(self, request, pk):
        app = self.spec(request, pk)
        resume, livrables = _resume(app)
        if not livrables['ready']:
            return Response({'error': 'not_ready', 'blockers': livrables['blockers']},
                            status=status.HTTP_409_CONFLICT)
        return Response({
            'spec': {'id': app.pk, 'name': app.name, 'updated_at': resume['updated_at']},
            'create': livrables['create'],
            'seed': {'lots_md': livrables['lots_md'],
                     'cahier_des_charges_md': livrables['cahier_des_charges_md']},
            'context': livrables['context'],
        })


class LivrablesView(APIView):
    """GET /api/apps/<id>/livrables/ — pour l'éditeur d'App Builder lui-même :
    le cahier des charges et la feuille de route tels qu'ils seraient remis au
    lab, lot par lot, même quand la spécification n'est pas encore prête.
    Authentification ordinaire de l'app (son seul client)."""

    def get(self, request, pk):
        try:
            app = AppSpec.objects.get(pk=pk, owner_email=request.user.email)
        except AppSpec.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        resume, livrables = _resume(app)
        return Response({
            'spec': {'id': app.pk, 'name': app.name, 'updated_at': resume['updated_at']},
            'ready': livrables['ready'], 'blockers': livrables['blockers'],
            'create': livrables['create'], 'counts': livrables['counts'], 'context': livrables['context'],
            'lots': livrables['lots'], 'lots_md': livrables['lots_md'],
            'cahier_des_charges_md': livrables['cahier_des_charges_md'],
        })


class GraphView(APIView):
    """GET /api/apps/<id>/graph/ — la spécification en graphe, à toutes les échelles
    (place dans le lab, architecture, données, pipelines, feuille de route)."""

    def get(self, request, pk):
        try:
            app = AppSpec.objects.get(pk=pk, owner_email=request.user.email)
        except AppSpec.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        spec = patching.spec_de(app)
        return Response({'spec': {'id': app.pk, 'name': app.name, 'updated_at': horodatage(app.updated_at)},
                         **graphe.graphe(spec)})
