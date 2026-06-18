import re
import json
import requests as http_requests
from decouple import config as env_config
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework import generics, status
from rest_framework.response import Response
from .models import AppSpec
from .serializers import AppSpecSerializer

# ── Extraction du patch JSON depuis la réponse IA ─────────────────────────────

_PATCH_RE = re.compile(r'SPEC_PATCH_START\s*(.*?)\s*SPEC_PATCH_END', re.DOTALL)


def _extract_patch(content: str) -> tuple[str, dict | None]:
    """Sépare le texte lisible du bloc SPEC_PATCH_START...SPEC_PATCH_END."""
    match = _PATCH_RE.search(content)
    if not match:
        return content, None
    clean = content[:match.start()].rstrip()
    try:
        patch = json.loads(match.group(1))
        return clean, patch
    except json.JSONDecodeError:
        return content, None


# ── Prompt système structuré ───────────────────────────────────────────────────

_AGENT_SYSTEM = """Tu es un assistant expert en architecture logicielle fullstack (Django REST + Angular).
Tu aides l'utilisateur à concevoir son application pour qu'elle soit entièrement génératable en code.
Tu t'adresses à des utilisateurs de tous niveaux : un utilisateur non-technique doit pouvoir te décrire
son besoin en français courant et obtenir une architecture complète sans connaître Django ou Angular.

## Ton objectif

Guider l'utilisateur à travers 4 phases de définition, dans l'ordre. Ne passe pas à la phase suivante
tant que la phase courante n'est pas complète. Identifie toujours la phase en cours au début de ta réponse.

Adapte ton vocabulaire au niveau de l'utilisateur :
- S'il parle en termes métier ("des produits", "un panier") → traduis toi-même en termes techniques
  sans lui imposer la syntaxe Django
- S'il est développeur → tu peux utiliser le vocabulaire technique directement

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

---

### Phase 3 — Frontend : pages et services Angular
Pour chaque page :
- Nom du composant (PascalCase) et route (`/chemin/:param`)
- Type de layout : list / detail / form / dashboard / mixed
- Composants UI présents : quels tableaux (colonnes ?), quels formulaires (champs ?), quels graphiques ?
- Quel(s) service(s) Angular appelle-t-elle ? Quelle(s) méthode(s) ?

Pour chaque service Angular :
- Méthodes concrètes avec types de retour

---

### Phase 4 — Pipelines et flux de données
Pour chaque pipeline par page :
- Événement déclencheur (clic bouton, chargement page, soumission formulaire…)
- Séquence d'étapes typées : trigger → service_call → transform → state_update → navigate → error

---

## Règles de dialogue

1. Pose **une question à la fois**, précise et ciblée.
2. Si une réponse est vague (ex : "il y a des utilisateurs"), reformule en demandant les champs exacts.
3. Résume ce qui est validé avant de passer à la question suivante.
4. Si tu détectes une incohérence, signale-la avant de continuer.
5. Quand une phase est complète, récapitule-la et demande confirmation.

---

## Format de réponse avec patch

Quand tu proposes des éléments **concrets et validés** (après confirmation de l'utilisateur, ou en
réponse à une description complète), inclus un bloc JSON **à la fin de ta réponse** entre ces balises :

SPEC_PATCH_START
{
  "set_meta": { "name": "NomApp", "description": "..." },
  "data_models": [ ... ],
  "endpoint_groups": [ ... ],
  "services": [ ... ],
  "pages": [ ... ]
}
SPEC_PATCH_END

**Règles importantes :**
- Omets entièrement le bloc pour les questions, demandes de clarification ou récapitulatifs sans nouveautés.
- N'inclus **que les éléments nouveaux** — pas ce qui existe déjà dans le contexte fourni.
- Chaque tableau peut être vide `[]` si rien de nouveau dans cette catégorie.
- Pour **services** : utilise `endpoint_group_names` (noms, pas IDs).
- Pour **pages** : utilise `service_names` (noms, pas IDs).

### Structure exacte des éléments

**data_models** (types de champs : string/text/int/decimal/bool/datetime/json/file) :
```json
{
  "name": "Produit", "description": "...", "order": 0,
  "fields": [
    { "name": "nom", "type": "string", "required": true, "unique": false, "max_length": 200 },
    { "name": "prix", "type": "decimal", "required": true, "unique": false }
  ],
  "relationships": [
    { "name": "categorie", "rel_type": "FK", "to_model": "Categorie",
      "related_name": "produits", "on_delete": "CASCADE" }
  ]
}
```

**endpoint_groups** :
```json
{
  "name": "Produits", "description": "...", "order": 0,
  "endpoints": [
    {
      "method": "GET", "path": "/api/produits/", "description": "Liste tous les produits",
      "operation": "list", "linked_model_name": "Produit", "order": 0,
      "auth_required": true, "required_roles": [],
      "request_schema": null, "response_schema": null, "query_params": []
    }
  ]
}
```

**services** :
```json
{ "name": "ProduitService", "order": 0, "endpoint_group_names": ["Produits"] }
```

**pages** :
```json
{
  "name": "ListeProduits", "route": "/produits", "layout": "list", "order": 0,
  "service_names": ["ProduitService"],
  "components": [{ "type": "table", "label": "Tableau des produits" }],
  "interactions": [
    { "name": "Voir détail", "type": "navigation",
      "description": "Clic sur une ligne → page détail", "order": 0 }
  ],
  "pipelines": [
    {
      "name": "Chargement produits", "description": "Au chargement", "order": 0,
      "steps": [
        { "label": "Page initialisée", "type": "trigger" },
        { "label": "ProduitService.getAll()", "type": "service_call",
          "service_method": "ProduitService.getAll()", "data_flow": "void → Produit[]" },
        { "label": "produits$ mis à jour", "type": "state_update" }
      ]
    }
  ]
}
```

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
        raw = resp.json()['choices'][0]['message']['content']
        content, patch = _extract_patch(raw)
        return Response({'content': content, 'provider': 'mistral', 'spec_patch': patch})

    def _call_claude(self, api_key, system_prompt, messages):
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        )
        raw = msg.content[0].text
        content, patch = _extract_patch(raw)
        return Response({'content': content, 'provider': 'claude', 'spec_patch': patch})
