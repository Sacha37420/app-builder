import jwt
from jwt import PyJWKClient, PyJWKClientError, InvalidTokenError
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.conf import settings


class KeycloakUser:
    """Minimal user object constructed from Keycloak JWT claims."""

    is_authenticated = True
    is_active = True

    def __init__(self, claims: dict) -> None:
        self.email: str = claims.get('email', '')
        self.username: str = claims.get('preferred_username', self.email)
        self.claims = claims
        # Required by some DRF internals
        self.pk = self.email

    def __str__(self) -> str:
        return self.username


class AccesRefuse(AuthenticationFailed):
    """Jeton authentique, mais qui n'ouvre pas cette API : autre client, hors
    des groupes requis, sans email. Reste une `AuthenticationFailed` (même
    réponse qu'avant sur toute l'API) ; la remise au lab s'en sert pour répondre
    403 là où un jeton absent ou invalide donne 401 (api/handoff.py)."""


class KeycloakJWTAuthentication(BaseAuthentication):
    """
    Validates Keycloak Bearer JWT tokens using the realm's JWKS endpoint.

    The JWKS client is cached at the class level so keys are fetched once
    per process start-up and reused for all subsequent requests.
    """

    _jwks_client: PyJWKClient | None = None

    def _allowed_client_ids(self) -> set[str]:
        """Clients dont le 'azp' est accepté. Un seul par défaut (le sien) —
        une sous-classe peut l'élargir pour une vue explicitement inter-apps."""
        return {settings.KEYCLOAK_CLIENT_ID}

    @classmethod
    def _get_jwks_client(cls) -> PyJWKClient:
        if cls._jwks_client is None:
            jwks_uri = (
                f'{settings.KEYCLOAK_ISSUER_URI}'
                '/protocol/openid-connect/certs'
            )
            cls._jwks_client = PyJWKClient(jwks_uri, cache_keys=True)
        return cls._jwks_client

    def authenticate(self, request):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return None

        token = auth_header[7:]

        try:
            client = self._get_jwks_client()
            signing_key = client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=['RS256'],
                options={
                    'verify_exp': True,
                    # Audience varies by Keycloak client configuration
                    'verify_aud': False,
                },
            )
        except InvalidTokenError as exc:
            raise AuthenticationFailed(f'Token invalide : {exc}') from exc
        except PyJWKClientError as exc:
            # Clé `kid` absente du JWKS, ou JWKS injoignable : PyJWKClientError
            # n'hérite pas d'InvalidTokenError. Sans cette branche, un jeton
            # forgé avec un `kid` quelconque provoquait une erreur 500.
            raise AuthenticationFailed('Token invalide : clé de signature introuvable.') from exc
        # Le token doit avoir été émis POUR cette application.
        # Sans ce contrôle, n'importe quel token du realm est accepté : le realm
        # expose 'admin-cli' en client public autorisant le password grant, donc
        # tout compte — y compris un compte auto-inscrit — pourrait s'en servir
        # pour appeler cette API. On vérifie 'azp' plutôt que 'aud' car Keycloak
        # ne place pas le clientId dans 'aud' sans mapper d'audience dédié.
        allowed = self._allowed_client_ids()
        if claims.get('azp') not in allowed:
            raise AccesRefuse(
                "Ce token a été émis pour un client non autorisé ici "
                f"(attendu : {', '.join(sorted(allowed))})."
            )

        # Cloisonnement par groupe. KEYCLOAK_REQUIRED_GROUPS vide ⇒ aucun filtre :
        # toute personne authentifiée sur ce client passe.
        required = {
            g.strip()
            for g in settings.KEYCLOAK_REQUIRED_GROUPS.split(',')
            if g.strip()
        }
        if required and not required & set(claims.get('groups') or []):
            raise AccesRefuse(
                'Accès réservé aux membres du/des groupe(s) : '
                f"{', '.join(sorted(required))}."
            )

        if not claims.get('email'):
            raise AccesRefuse(
                "Le token ne contient pas de claim 'email'. "
                "Vérifiez que le mapper 'email' est activé dans Keycloak."
            )

        return KeycloakUser(claims), token


# ── Jetons personnels du serveur MCP (I5 du chantier app-builder-v2) ──────────

class McpUser:
    """L'appelant d'un jeton personnel `abt_…` : son email, sa portée, sa spec liée."""

    is_authenticated = True
    is_active = True

    def __init__(self, jeton) -> None:
        self.email: str = jeton.owner_email
        self.username: str = jeton.owner_email
        self.pk = jeton.owner_email
        self.jeton = jeton
        self.claims: dict = {}

    def __str__(self) -> str:
        return self.username


class McpTokenAuthentication(BaseAuthentication):
    """`Authorization: Bearer abt_…` — n'est branchée QUE sur `/api/mcp/`
    (`api.mcp.McpView.authentication_classes`) : partout ailleurs l'authentification
    par défaut (Keycloak) refuse un `abt_` (ce n'est pas un JWT), et ici un jeton
    Keycloak n'est pas reconnu.

    Le jeton est retrouvé par son empreinte sha256 (index unique) : aucune
    comparaison de secret en clair, donc pas de fuite par le temps de réponse.
    Un message d'erreur unique pour tous les refus (inconnu, expiré, révoqué) :
    rien ne dit à un attaquant lequel."""

    PREFIXE = 'abt_'
    _REFUS = 'Jeton MCP invalide, expiré ou révoqué.'

    def authenticate_header(self, request) -> str:
        return 'Bearer'

    def authenticate(self, request):
        import hashlib

        from django.utils import timezone

        from .models import McpToken

        entete = request.headers.get('Authorization', '')
        if not entete.startswith('Bearer '):
            return None
        valeur = entete[7:].strip()
        if not valeur.startswith(self.PREFIXE) or len(valeur) > 128:
            raise AuthenticationFailed(self._REFUS)
        empreinte = hashlib.sha256(valeur.encode()).hexdigest()
        maintenant = timezone.now()
        jeton = McpToken.objects.filter(token_hash=empreinte).select_related('spec').first()
        if jeton is None or jeton.revoked_at is not None or jeton.expires_at <= maintenant:
            raise AuthenticationFailed(self._REFUS)
        McpToken.objects.filter(pk=jeton.pk).update(last_used_at=maintenant)
        return McpUser(jeton), None
