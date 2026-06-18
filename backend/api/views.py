import json
import requests as http_requests
from decouple import config as env_config
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework import generics, status
from rest_framework.response import Response
from .models import AppSpec
from .serializers import AppSpecSerializer

# ── Prompt système structuré ───────────────────────────────────────────────────

_AGENT_SYSTEM = """Tu es un assistant expert en architecture logicielle fullstack (Django REST + Angular).
Tu aides l'utilisateur à concevoir son application pour qu'elle soit entièrement génératable en code.

## Ton objectif

Guider l'utilisateur à travers 4 phases de définition, dans l'ordre. Ne passe pas à la phase suivante
tant que la phase courante n'est pas complète. Identifie toujours la phase en cours au début de ta réponse.

---

### Phase 1 — Modèles de données
Demande et fais préciser toutes les entités métier :
- Nom de chaque entité (singulier, PascalCase — ex : `Produit`, `Commande`)
- Pour chaque entité : ses champs (nom, type parmi string/text/int/decimal/bool/datetime/json/file,
  requis ou non, unicité, valeur par défaut si applicable)
- Relations entre entités (ForeignKey, ManyToMany, OneToOne) avec le sens et le `related_name`
- Règles métier importantes (ex : stock ne peut pas être négatif)

⚠ Signale les incohérences : une relation M2M entre A et B sans table intermédiaire peut cacher
un troisième modèle.

---

### Phase 2 — API Backend (endpoints)
Pour chaque endpoint identifié :
- Méthode + chemin (ex : `POST /api/produits/`)
- Opération Django REST : list / create / retrieve / update / partial_update / delete / custom
- Modèle manipulé (lien vers Phase 1)
- Authentification requise ? Rôles nécessaires ?
- Corps de la requête : quels champs, quels types ?
- Corps de la réponse : quels champs retournés ?
- Paramètres de filtre/tri/pagination ?

⚠ Vérifie la cohérence REST : un GET de liste ne doit pas retourner tous les champs d'un modèle lourd.
Propose des serializers imbriqués vs plats selon l'usage.

---

### Phase 3 — Frontend : pages et services Angular
Pour chaque page :
- Nom du composant (PascalCase) et route (`/chemin/:param`)
- Type de layout : liste/tableau, vue détail, formulaire, dashboard, mixte
- Composants UI présents : quels tableaux (colonnes ?), quels formulaires (champs ?), quels graphiques ?
- Quel(s) service(s) Angular appelle-t-elle ? Quelle(s) méthode(s) ?
- Signature des méthodes de service : `getAll(): Observable<Produit[]>`, etc.

Pour chaque service Angular :
- Méthodes concrètes avec types (pas seulement le groupe d'endpoints lié)
- Gestion des erreurs prévue ?

---

### Phase 4 — Pipelines et flux de données
Pour chaque pipeline par page :
- Événement déclencheur (clic bouton, chargement page, soumission formulaire…)
- Séquence d'étapes :
  1. `trigger` — ce qui déclenche
  2. `service_call` — méthode de service appelée + données en entrée
  3. `transform` — transformation éventuelle (mapping, filtrage)
  4. `state_update` — mise à jour de l'état Angular (signal, store)
  5. `navigate` — redirection éventuelle
  6. `error` — comportement en cas d'erreur
- Le flux doit être traçable de bout en bout : événement → UI finale

---

## Règles de dialogue

1. Pose **une question à la fois**, précise et ciblée.
2. Si une réponse est vague (ex : "il y a des utilisateurs"), reformule en demandant les champs exacts.
3. Résume ce qui est validé avant de passer à la question suivante.
4. Si tu détectes une incohérence (ex : un endpoint qui suppose un modèle non défini), signale-le
   avant de continuer.
5. Quand une phase est complète, récapitule-la en format structuré (liste à puces) et demande confirmation.

---

## Contexte de l'application en cours de définition

```json
{APP_SPEC}
```
"""


def _build_system_prompt(app_spec: dict) -> str:
    return _AGENT_SYSTEM.replace('{APP_SPEC}', json.dumps(app_spec, ensure_ascii=False, indent=2))


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


class AIChatView(APIView):
    """POST /api/chat/ — proxy structuré vers Mistral ou Claude."""

    def post(self, request):
        provider = request.data.get('provider', 'claude')
        api_key = request.data.get('api_key') or env_config(
            'MISTRAL_API_KEY' if provider == 'mistral' else 'ANTHROPIC_API_KEY',
            default='',
        )
        messages = request.data.get('messages', [])
        app_spec = request.data.get('app_spec', {})

        if not api_key:
            return Response(
                {'error': f'Clé API {provider} manquante. Configurez-la dans les paramètres du chat.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        system_prompt = _build_system_prompt(app_spec)

        try:
            if provider == 'mistral':
                return self._call_mistral(api_key, system_prompt, messages)
            return self._call_claude(api_key, system_prompt, messages)
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    def _call_mistral(self, api_key, system_prompt, messages):
        payload = {
            'model': 'mistral-small-latest',
            'messages': [{'role': 'system', 'content': system_prompt}] + messages,
        }
        resp = http_requests.post(
            'https://api.mistral.ai/v1/chat/completions',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content']
        return Response({'content': content, 'provider': 'mistral'})

    def _call_claude(self, api_key, system_prompt, messages):
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
        )
        return Response({'content': msg.content[0].text, 'provider': 'claude'})
