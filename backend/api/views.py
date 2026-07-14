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

def _extract_choices(content: str) -> tuple[str, dict | None]:
    """Extrait et supprime le bloc CHOICES_START...CHOICES_END du contenu."""
    si = content.find('CHOICES_START')
    if si == -1:
        return content, None
    ei = content.find('CHOICES_END', si)
    if ei == -1:
        return content, None
    between = content[si + len('CHOICES_START'):ei]
    bo = between.find('{')
    bc = between.rfind('}')
    if bo == -1 or bc == -1:
        return content, None
    json_str = between[bo:bc + 1]
    clean = (content[:si] + content[ei + len('CHOICES_END'):]).strip()
    try:
        choices = json.loads(json_str)
        print(f"[CHOICES] multiple={choices.get('multiple')} items={len(choices.get('items', []))}")
        return clean, choices
    except json.JSONDecodeError:
        return content, None


def _extract_patch(content: str) -> tuple[str, dict | None]:
    """Sépare le texte lisible du bloc SPEC_PATCH_START...SPEC_PATCH_END.

    Robuste face aux variations du modèle :
    - JSON direct après le marqueur
    - JSON dans un bloc ```json ... ```
    - Marqueur utilisé comme titre Markdown (### SPEC_PATCH_START)
    """
    start_marker = 'SPEC_PATCH_START'
    end_marker   = 'SPEC_PATCH_END'

    start_idx = content.find(start_marker)
    if start_idx == -1:
        print('[PATCH] Aucun bloc SPEC_PATCH_START trouvé')
        return content, None

    end_idx = content.find(end_marker, start_idx)
    if end_idx == -1:
        print('[PATCH] SPEC_PATCH_END non trouvé')
        return content, None

    # Zone entre les deux marqueurs
    between = content[start_idx + len(start_marker):end_idx]

    # Premier '{' et dernier '}' dans cette zone → isole le JSON quelle que soit
    # la mise en forme (backticks, texte d'intro, titre Markdown, etc.)
    brace_open  = between.find('{')
    brace_close = between.rfind('}')
    if brace_open == -1 or brace_close == -1:
        print('[PATCH] Pas de JSON trouvé entre les marqueurs')
        return content, None

    json_str = between[brace_open:brace_close + 1]
    clean    = content[:start_idx].rstrip()

    try:
        patch = json.loads(json_str)
        print(f"[PATCH] OK — models={len(patch.get('data_models') or [])} "
              f"groups={len(patch.get('endpoint_groups') or [])} "
              f"services={len(patch.get('services') or [])} "
              f"pages={len(patch.get('pages') or [])}")
        return clean, patch
    except json.JSONDecodeError as e:
        print(f'[PATCH] JSON invalide : {e}')
        print(f'[PATCH] Extrait brut : {json_str[:300]}')
        return content, None


# ── Prompt système structuré ───────────────────────────────────────────────────

_AGENT_SYSTEM = """Tu es un assistant expert en architecture logicielle fullstack (Django REST + Angular).
Tu aides l'utilisateur à concevoir son application pour qu'elle soit entièrement génératable en code.
Tu t'adresses à des utilisateurs de tous niveaux : un utilisateur non-technique doit pouvoir te décrire
son besoin en français courant et obtenir une architecture complète sans connaître Django ou Angular.

## Contexte technique du système

L'application sera déployée dans un lab utilisant **Keycloak** comme fournisseur d'identité (SSO).
Règles impératives à respecter dans toute spécification :

- **Ne jamais modéliser `User`, `Role` ou `Permission`** — ces entités existent déjà dans Keycloak.
- Les **groupes/rôles** sont des claims JWT : `request.user.claims.get('groups', [])`. Ne pas créer
  de table Django pour ça.
- Les **`required_roles`** d'un endpoint sont des noms de groupes Keycloak (ex : `["admin", "editor"]`).
- L'authentification est toujours via JWT Keycloak, jamais via session Django ni `django.contrib.auth`.

## Cloisonnement — règles de sécurité non négociables

Le lab est **exposé sur Internet**, et être authentifié dans le realm ne doit donner accès à RIEN.
Toute application est réservée à un ou plusieurs **groupes** Keycloak.

- Demande **systématiquement**, dès la phase 1 : « Quel(s) groupe(s) ont le droit d'utiliser cette
  application ? ». Le résultat alimente `app_spec.required_groups` (liste de noms de groupes).
  Une app sans `required_groups` accepterait n'importe quel compte du realm — y compris un inconnu
  auto-inscrit. **Ne jamais laisser cette liste vide sans que l'utilisateur l'ait explicitement voulu.**
- Le cloisonnement repose sur **deux verrous**, et la spec doit toujours prévoir les deux :
  1. **Barrière navigateur** — un flow Keycloak `require-<client>` refuse la connexion à qui n'a pas
     le rôle `<client>-access`. Il est posé automatiquement par `create-app-client.sh` à partir de
     `--require-group`, il n'y a rien à générer côté code.
  2. **Serrure API** — le backend Django DOIT vérifier lui-même, dans `api/authentication.py` :
     - **`azp`** (client émetteur du token) == `settings.KEYCLOAK_CLIENT_ID` ;
     - le claim **`groups`** croise `settings.KEYCLOAK_REQUIRED_GROUPS`.
- ⚠️ **Le flow ne voit jamais un appel direct à l'API.** Le realm expose `admin-cli` en client public
  avec le password grant : sans le contrôle de `azp`, tout compte du realm obtient un token et appelle
  n'importe quelle API en contournant complètement le flow. **Ne jamais proposer une app qui s'en
  remet au seul flow Keycloak**, ni retirer le contrôle `azp` / `groups` du backend.
- Les `required_roles` d'un endpoint viennent **en plus** de ce cloisonnement global, pour restreindre
  certaines routes à un sous-ensemble des groupes autorisés.

---

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
⚠ Ne jamais proposer de modèle `User`, `Profil utilisateur` ou `Permission` — Keycloak les gère.

---

### Phase 2 — API Backend (endpoints)
Pour chaque endpoint identifié :
- Méthode + chemin (ex : `POST /api/produits/`)
- Opération Django REST : list / create / retrieve / update / partial_update / delete / custom
- Modèle manipulé (lien vers Phase 1)
- Authentification requise ? (par défaut oui)
- **Rôles requis** : demander systématiquement "Cet endpoint est-il accessible à tous les utilisateurs
  connectés, ou réservé à certains rôles ?" — si des rôles sont nécessaires, les lister dans `required_roles`
- Corps de la requête : quels champs, quels types ?
- Corps de la réponse : quels champs retournés ?
- **Paramètres de filtre/tri/pagination** : demander systématiquement "Y a-t-il des filtres, une
  recherche par texte ou une pagination ?" — si oui, définir chaque `query_param` (nom, type, requis)

⚠ Vérifie la cohérence REST : un GET de liste ne doit pas retourner tous les champs d'un modèle lourd.

---

### Phase 3 — Frontend : pages et services Angular
Pour chaque page :
- Nom du composant (PascalCase) et route (`/chemin/:param`)
- Type de layout : list / detail / form / dashboard / mixed
- **Composants UI** : pour chaque composant, préciser impérativement :
  - Tableau (`table`) → quelles colonnes afficher ? (noms des champs du modèle)
  - Formulaire (`form`) → quels champs inclure ? validation ? action de soumission ?
  - Graphique (`chart`) → quel type ? quelles données en X et Y ?
  - Carte (`card`) → quels champs afficher ?
  → Toujours renseigner `linked_model` (modèle source) et `fields` (liste des champs visibles)
- Quel(s) service(s) Angular appelle-t-elle ?
- Interactions utilisateur : clics, soumissions, navigations

Pour chaque service Angular :
- Méthodes concrètes liées aux endpoints de la Phase 2

---

### Phase 4 — Pipelines et flux de données
Pour chaque pipeline par page :
- **Interaction déclencheure** : quel événement de la page déclenche ce pipeline ?
  (utiliser le `name` d'une interaction définie en Phase 3, champ `trigger_interaction`)
- Séquence d'étapes typées : trigger → service_call → transform → state_update → navigate → error
- Pour les étapes `service_call` : préciser `service_name` (nom de la classe Angular, ex : `ProduitService`)
  ET `service_method` (appel complet, ex : `ProduitService.create(formData)`)

---

## Règles de dialogue

1. Pose **une question à la fois**, précise et ciblée.
2. Si une réponse est vague (ex : "il y a des utilisateurs"), reformule en demandant les champs exacts.
3. Résume ce qui est validé avant de passer à la question suivante.
4. Si tu détectes une incohérence, signale-la avant de continuer.
5. Quand une phase est complète, récapitule-la et demande confirmation.

---

## Format de réponse avec choix proposés

Quand tu poses une question à laquelle l'utilisateur peut choisir parmi des options,
inclus un bloc **immédiatement après ta question** entre ces balises :

CHOICES_START
{
  "multiple": false,
  "items": ["Option A", "Option B", "Option C"]
}
CHOICES_END

- `multiple: false` → une seule réponse attendue (ex : type de relation, layout de page, opération REST)
- `multiple: true` → plusieurs réponses possibles (ex : liste de champs, liste de pages, rôles autorisés)
- Propose 2 à 6 options concrètes et pertinentes pour le contexte
- L'interface ajoute automatiquement un bouton "Autre..." — ne l'inclus pas dans tes options
- N'inclus **pas** ce bloc pour les récapitulatifs, confirmations ou questions ouvertes sans choix naturels

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

**data_models** (types de champs : string/text/int/decimal/bool/datetime/json — **n'utilise jamais `file`**, voir règles de stockage) :
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

**endpoint_groups** — chaque endpoint peut inclure des `steps` décrivant le traitement serveur :
```json
{
  "name": "Produits", "description": "...", "order": 0,
  "endpoints": [
    {
      "method": "GET", "path": "/api/produits/", "description": "Liste tous les produits",
      "operation": "list", "linked_model_name": "Produit", "order": 0,
      "auth_required": true, "required_roles": [],
      "request_schema": null, "response_schema": null, "query_params": [],
      "steps": [
        { "label": "Vérifier JWT", "type": "auth_check", "description": "Vérifie que le token Keycloak est valide et extrait email + groups" },
        { "label": "Requête DB", "type": "db_query", "description": "Filtre les produits par owner_email=request.user.email avec order_by('-updated_at')" },
        { "label": "Sérialiser", "type": "serialize", "description": "Convertit le queryset en liste JSON via ProduitSerializer(many=True)" }
      ]
    }
  ]
}
```
Types de steps backend : `auth_check | validate | db_query | db_write | serialize | transform | error | custom`

**services** :
```json
{ "name": "ProduitService", "order": 0, "endpoint_group_names": ["Produits"] }
```

**pages** :
```json
{
  "name": "ListeProduits", "route": "/produits", "layout": "list", "order": 0,
  "service_names": ["ProduitService"],
  "components": [{
    "type": "table", "label": "Tableau des produits",
    "linked_model": "Produit",
    "fields": ["nom", "prix", "categorie", "updated_at"]
  }],
  "interactions": [
    { "name": "Page chargée", "type": "display",
      "description": "Déclenchée au chargement (ngOnInit)", "order": 0 },
    { "name": "Voir détail", "type": "navigation",
      "description": "Clic sur une ligne → page détail du produit", "order": 1 }
  ],
  "pipelines": [
    {
      "name": "Chargement produits", "description": "Au chargement de la page", "order": 0,
      "trigger_interaction": "Page chargée",
      "steps": [
        { "label": "Page initialisée", "type": "trigger",
          "description": "Événement ngOnInit" },
        { "label": "ProduitService.getAll()", "type": "service_call",
          "service_name": "ProduitService",
          "service_method": "ProduitService.getAll()", "data_flow": "void → Produit[]",
          "description": "Appelle GET /api/produits/ et stocke le résultat dans le signal produits$" },
        { "label": "produits$ mis à jour", "type": "state_update",
          "description": "Signal produits$ = résultat de l'appel API" }
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


class AppSpecPublicView(generics.ListAPIView):
    """GET /api/apps/public/ — toutes les specs, tous utilisateurs confondus."""
    serializer_class = AppSpecSerializer
    queryset = AppSpec.objects.all().order_by('-updated_at')


class InfrastructureView(APIView):
    """GET /api/infrastructure/ — apps hébergées parsées depuis ports.env."""

    _PORTS_FILE = '/ports.env'

    def get(self, request):
        domain = env_config('DOMAIN', default='')
        try:
            with open(self._PORTS_FILE, 'r') as f:
                content = f.read()
        except FileNotFoundError:
            return Response({'apps': [], 'error': 'ports.env introuvable'})

        apps = []
        for line in content.strip().splitlines():
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('__'):
                continue
            parts = line.split(':')
            name = parts[0]
            backend_port = int(parts[1]) if len(parts) > 1 and parts[1] else None
            frontend_port = int(parts[2]) if len(parts) > 2 and parts[2] else None

            if domain:
                base = f'https://{domain}'
                frontend_url = f'{base}/{name}/' if frontend_port else None
                backend_url  = f'{base}/{name}-api/' if backend_port else None
            else:
                base = 'http://localhost'
                frontend_url = f'{base}:{frontend_port}/' if frontend_port else None
                backend_url  = f'{base}:{backend_port}/' if backend_port else None

            apps.append({
                'name': name,
                'backend_port': backend_port,
                'frontend_port': frontend_port,
                'frontend_url': frontend_url,
                'backend_url': backend_url,
            })

        return Response({'apps': apps})


class AIChatView(APIView):
    """POST /api/chat/ — proxy structuré vers Mistral ou Claude."""

    def post(self, request):
        provider = request.data.get('provider', 'claude')
        api_key  = request.data.get('api_key', '').strip()
        model    = request.data.get('model', '').strip() or None
        messages = request.data.get('messages', [])
        app_spec = request.data.get('app_spec', {})

        print(f"[CHAT] provider={provider} model={model} messages={len(messages)}")
        for i, m in enumerate(messages):
            print(f"  [{i}] {m.get('role')}: {str(m.get('content',''))[:80]!r}")

        if not api_key:
            return Response(
                {'error': f'Clé API {provider} manquante. Configurez-la dans les paramètres (⚙).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        system_prompt = _build_system_prompt(app_spec)

        try:
            if provider == 'mistral':
                return self._call_mistral(api_key, system_prompt, messages, model)
            return self._call_claude(api_key, system_prompt, messages, model)
        except http_requests.exceptions.Timeout:
            return Response(
                {'error': 'Impossible de joindre l\'API Mistral (timeout de connexion). Vérifiez votre clé ou réessayez dans quelques instants.'},
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    def _call_mistral(self, api_key, system_prompt, messages, model=None):
        payload = {
            'model': model or 'mistral-small-latest',
            'messages': [{'role': 'system', 'content': system_prompt}] + messages,
            'stream': True,
        }
        # Streaming : timeout connect=10s, pas de read timeout (le flux arrive en continu)
        with http_requests.post(
            'https://api.mistral.ai/v1/chat/completions',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json=payload,
            stream=True,
            timeout=(10, None),
        ) as resp:
            resp.raise_for_status()
            full_text = ''
            for line in resp.iter_lines():
                if not line:
                    continue
                decoded = line.decode('utf-8')
                if not decoded.startswith('data: '):
                    continue
                data = decoded[6:]
                if data == '[DONE]':
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk['choices'][0]['delta'].get('content', '')
                    if delta:
                        full_text += delta
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass

        content, patch   = _extract_patch(full_text)
        content, choices = _extract_choices(content)
        return Response({'content': content, 'provider': 'mistral', 'spec_patch': patch, 'choices': choices})

    def _call_claude(self, api_key, system_prompt, messages, model=None):
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        full_text = ''
        with client.messages.stream(
            model=model or 'claude-sonnet-4-6',
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                full_text += text
        content, patch   = _extract_patch(full_text)
        content, choices = _extract_choices(content)
        return Response({'content': content, 'provider': 'claude', 'spec_patch': patch, 'choices': choices})


class AppSpecChatHistoryView(APIView):
    def patch(self, request, pk):
        try:
            app = AppSpec.objects.get(pk=pk, owner_email=request.user.email)
        except AppSpec.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        app.chat_history = request.data.get('chat_history', [])
        app.save(update_fields=['chat_history'])
        return Response({'ok': True})
