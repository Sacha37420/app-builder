// ── Types de base ──────────────────────────────────────────────────────────────

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
export type InteractionType = 'click' | 'form' | 'navigation' | 'display' | 'other'
  | 'drag' | 'keyboard' | 'timer' | 'upload' | 'realtime_event';
export type OperationType = 'list' | 'create' | 'retrieve' | 'update' | 'partial_update' | 'delete' | 'custom';
export type PageLayout = 'list' | 'detail' | 'form' | 'dashboard' | 'mixed' | 'canvas' | 'wizard' | 'settings';
export type PipelineStepType = 'trigger' | 'service_call' | 'transform' | 'state_update' | 'navigate' | 'error'
  | 'poll_job' | 'enqueue_job' | 'client_compute';
export type EndpointStepType = 'auth_check' | 'validate' | 'db_query' | 'db_write' | 'serialize' | 'transform' | 'error' | 'custom'
  | 'enqueue_job' | 'external_call' | 'notify';
// `storage_file` : fichier d'utilisateur déposé dans le service `storage` du lab — le
// modèle n'en garde que le chemin. `file` est l'ancien type : encore lisible sur une
// spec ancienne, refusé à l'écriture par le serveur pour tout nouveau champ.
export type FieldType = 'string' | 'text' | 'int' | 'decimal' | 'bool' | 'datetime' | 'json' | 'storage_file' | 'file'
  // Métamodèle v2 (contrat app-builder-v2, I1)
  | 'date' | 'email' | 'url' | 'enum' | 'secret' | 'geo_point' | 'geometry';
export type RelType = 'FK' | 'M2M' | 'O2O';
export type AiProvider = 'claude' | 'mistral';
export type AppType = 'django-angular' | 'django' | 'spring-angular' | 'spring' | 'angular';
/** Types que le moteur du lab sait créer (les autres ne restent que lisibles). */
export const CONSTRUCTIBLE_APP_TYPES: readonly AppType[] = ['django-angular', 'django', 'angular'];

// ── Phase 1 : Modèles de données ──────────────────────────────────────────────

export interface ModelField {
  name: string;
  type: FieldType;
  required: boolean;
  unique: boolean;
  max_length?: number;
  default?: string;
  help_text?: string;
  // ── Attributs facultatifs du métamodèle v2 (I1) ──
  values?: string[];            // enum (obligatoire pour enum)
  min?: number;
  max?: number;
  pattern?: string;
  unique_ci?: boolean;
  max_bytes?: number;           // storage_file
  accept?: string;              // storage_file
  srid?: number;                // geometry
  geometry_kind?: string;       // geometry
  secret_scope?: 'user' | 'app';   // secret : chiffré au coffre, jamais rendu par l'API
}

export interface ModelRelationship {
  name: string;
  rel_type: RelType;
  to_model: string;     // nom d'un autre DataModel
  related_name: string;
  on_delete?: 'CASCADE' | 'SET_NULL' | 'PROTECT' | 'DO_NOTHING';
}

export type ModelKind = 'entity' | 'singleton' | 'reference' | 'log' | 'join';
export type AccessScope = 'owner' | 'shared' | 'group' | 'parent' | 'public_read' | 'global';
export type AccessAction = 'read' | 'create' | 'update' | 'delete' | 'manage_shares';

export interface AccessRule { action: AccessAction; who: string[]; }

/** Qui voit quoi (I1) — `{}` = non décrit (avertissement ; défaut « propriétaire seul »). */
export interface ModelAccess {
  scope?: AccessScope;
  owner_field?: string;
  parent?: string;
  share_model?: string;
  public_flag?: string;
  rules?: AccessRule[];
  hidden_fields?: { field: string; unless: string }[];
  reason?: string;
}

export interface StateTransition {
  from: string[];
  to: string;
  by?: string[];
  action?: string;
  side_effects?: string[];
}

/** Machine à états (I1) — `{}` = aucune. */
export interface ModelStates {
  field?: string;
  initial?: string;
  values?: string[];
  transitions?: StateTransition[];
  frozen_in?: string[];
}

export interface ModelConstraint {
  kind: 'unique' | 'check';
  fields?: string[];
  condition?: string;
  name?: string;
}

export interface DataModel {
  id?: number;
  name: string;         // PascalCase, ex: "Produit"
  description: string;
  fields: ModelField[];
  relationships: ModelRelationship[];
  order: number;
  // ── Métamodèle v2 (I1) — absents d'une spec ancienne ──
  kind?: ModelKind;
  access?: ModelAccess;
  states?: ModelStates;
  constraints?: ModelConstraint[];
}

// ── Phase 2 : API Backend ─────────────────────────────────────────────────────

export interface QueryParam {
  name: string;
  type: FieldType;
  required: boolean;
  description: string;
}

export interface EndpointStep {
  label: string;
  type: EndpointStepType;
  description?: string;
}

export interface Endpoint {
  id?: number;
  method: HttpMethod;
  path: string;
  description: string;
  order: number;
  // Sémantique pour génération
  operation: OperationType;
  linked_model_name: string;   // nom d'un DataModel
  auth_required: boolean;
  /** Justification d'une route sans authentification (`auth_required: false`), sinon ''. */
  public_reason: string;
  required_roles: string[];
  request_schema: Record<string, string> | null;   // {field: type}
  response_schema: Record<string, string> | null;
  query_params: QueryParam[];
  steps?: EndpointStep[];
  /** Mode d'authentification (I1) ; `{}` = jwt. */
  auth?: EndpointAuth;
}

export type EndpointAuthMode = 'jwt' | 'public' | 'api_key' | 'hmac_signature' | 'internal_key' | 'ticket';

export interface EndpointAuth {
  mode?: EndpointAuthMode;
  caller?: string;
  key_source?: string;
  reason?: string;
}

export interface EndpointGroup {
  id?: number;
  name: string;
  description: string;
  order: number;
  endpoints: Endpoint[];
}

// ── Phase 3 : Frontend ────────────────────────────────────────────────────────

export interface FrontendService {
  id?: number;
  name: string;
  order: number;
  endpoint_group_ids: number[];
}

export type PageComponentType = 'table' | 'form' | 'chart' | 'card' | 'custom'
  // Métamodèle v2 (I1)
  | 'map' | 'viewer_3d' | 'game_canvas' | 'timeseries_chart' | 'calendar' | 'video_player' | 'pdf_viewer'
  | 'markdown' | 'qr_code' | 'graph' | 'wizard' | 'chat' | 'job_progress' | 'share_manager' | 'secret_form'
  | 'file_browser' | 'kanban';

export interface PageComponent {
  type: PageComponentType;
  label: string;
  linked_model?: string;
  fields?: string[];
  config?: Record<string, unknown>;
}

export interface Interaction {
  id?: number;
  name: string;
  type: InteractionType;
  description: string;
  order: number;
}

// ── Phase 4 : Pipelines ───────────────────────────────────────────────────────

export interface PipelineStep {
  id?: number;
  label: string;
  description?: string;
  type: PipelineStepType;
  service_name?: string;     // ex: "ProduitService" (classe Angular)
  service_method?: string;   // ex: "ProduitService.create(formData)"
  data_flow?: string;        // ex: "CreateProduitDto → Produit"
  on_error?: string;         // comportement en cas d'erreur
}

export interface Pipeline {
  id?: number;
  name: string;
  description: string;
  trigger_interaction?: string;  // name d'une Interaction de la même page
  steps: PipelineStep[];
  order: number;
}

export interface Page {
  id?: number;
  name: string;
  route: string;
  order: number;
  layout: PageLayout;
  components: PageComponent[];
  service_ids: number[];
  interactions: Interaction[];
  pipelines: Pipeline[];
  // ── Métamodèle v2 (I1) ──
  public?: boolean;
  public_reason?: string;
  required_roles?: string[];
}

// ── Spec complète ─────────────────────────────────────────────────────────────

export interface BusinessRule {
  title: string;        // obligatoire, non vide (400 sinon)
  description: string;
  // ── Métamodèle v2 (I1), facultatifs ──
  applies_to?: string;                 // "Modèle" | "METHODE /chemin/"
  kind?: 'invariant' | 'validation' | 'side_effect' | 'access';
  enforced_by?: string[];              // ["POST /api/x/"]
}

// ── Structures du métamodèle v2 au niveau de la spec (I1) ─────────────────────

export interface AppRole {
  name: string;
  kind: 'keycloak_group' | 'object_role';
  description?: string;
  implies?: string[];
  on_model?: string;                   // object_role seulement
}

export interface AppJob {
  name: string;
  kind: 'async' | 'scheduled' | 'command';
  trigger?: string;                    // "POST /api/…" | "every:30min" | "manual"
  input_model?: string;
  tracked_by?: string;
  concurrency?: string;                // "" | "one_per:<Modèle>"
  heavy?: boolean;
  description?: string;
}

export type IntegrationType = 'storage' | 'email' | 'keycloak_admin' | 'lab_media' | 'postgis' | 'oauth_hub';

export interface AppIntegration {
  type: IntegrationType;
  mode?: string;
  description?: string;
}

export interface ExternalApi {
  name: string;
  purpose?: string;
  auth?: 'none' | 'app_key' | 'user_key' | 'oauth_hub';
  called_from?: 'backend' | 'job';
  description?: string;
}

export interface DataIoExtension {
  direction: 'import' | 'export'; format: string; model: string;
  mode?: 'append' | 'upsert' | 'replace'; async?: boolean;
  name?: string;
}
export interface RealtimeExtension { name: string; transport: 'poll' | 'ws_relay' | 'webrtc' | 'hls'; description?: string; }
export interface ComputationExtension {
  name: string; inputs?: string[]; output?: string; run?: 'sync' | 'job'; verification?: string;
}
export interface NotificationExtension { event: string; channel: string; to: string; name?: string; }

export interface AppExtensions {
  data_io?: DataIoExtension[];
  realtime?: RealtimeExtension[];
  computations?: ComputationExtension[];
  notifications?: NotificationExtension[];
}

export interface AppSpec {
  id?: number;
  name: string;
  /** Nom du projet dans le lab (dossier, adresse `/<nom>`, client Keycloak) ; '' tant qu'il n'est pas choisi. */
  project_name: string;
  description: string;
  app_type: AppType;
  owner_email?: string;
  // Groupes Keycloak autorisés à utiliser l'app (cloisonnement) — champ structuré,
  // survit à un effacement de l'historique de chat (contrairement à ce qui n'est
  // dit qu'en conversation).
  required_groups: string[];
  business_rules: BusinessRule[];
  uses_email: boolean;
  // ── Métamodèle v2 (I1) — absents d'une spec ancienne, normalisés à la lecture ──
  roles?: AppRole[];
  jobs?: AppJob[];
  integrations?: AppIntegration[];
  external_apis?: ExternalApi[];
  extensions?: AppExtensions;
  /** `GET /api/apps/<id>/` seulement (I4, lecture seule) : empreinte de la version. */
  version?: string;
  chat_history?: PersistedChatMessage[];
  created_at?: string;
  updated_at?: string;
  data_models: DataModel[];
  endpoint_groups: EndpointGroup[];
  services: FrontendService[];
  pages: Page[];
}

// ── Chat (I4) ─────────────────────────────────────────────────────────────────

/** Une opération atomique sur la spec (I2) — affichée telle quelle, jamais fusionnée ici. */
export interface SpecOperation {
  op: 'upsert' | 'remove' | 'rename';
  cible: { type: string; nom?: string; modele?: string; groupe?: string; page?: string };
  nouveau_nom?: string;
  data?: Record<string, unknown>;
}

/** Résumé d'un lot d'opérations calculé par le serveur (I3 `resume_operations`). */
export interface OperationsSummary {
  texte: string;
  destructive: boolean;
  details: { index: number; texte: string; destructive: boolean }[];
}

/** Proposition de l'agent (I4) : rien n'est écrit tant que l'utilisateur n'a pas cliqué « Appliquer ». */
export interface ChatProposal {
  operations: SpecOperation[];
  resume: OperationsSummary;
  base_version: string;
  erreurs: string[];
}

export interface ChatChoices { question?: string; multiple: boolean; items: string[]; }

export interface ChatUsage { calls: number; input_tokens: number; output_tokens: number; cache_read_tokens: number; }

/** Réponse 200 de `POST /api/chat/` (I4). */
export interface ChatResponse {
  content: string;
  provider: string;
  model: string;
  choices: ChatChoices | null;
  proposal: ChatProposal | null;
  truncated: boolean;
  context?: ChatContext;
  usage?: ChatUsage;
}

/** État d'une proposition dans la conversation (enregistré avec elle). */
export type ProposalState = 'proposed' | 'applied' | 'undone' | 'stale' | 'refused';

export interface PersistedChatMessage {
  role: 'user' | 'assistant';
  content: string;
  proposal?: ChatProposal | null;
  proposal_state?: ProposalState;
  /** Erreurs rendues par le serveur au moment d'appliquer (400). */
  proposal_errors?: string[];
  // Identifiant de l'application côté serveur : c'est lui qui permet d'annuler.
  application_id?: number | null;
  choices?: ChatChoices | null;
  truncated?: boolean;
  // ── Ancien protocole (avant le chantier app-builder-v2) : lu seulement ──
  spec_patch?: unknown;
  patch_summary?: string | null;
  applied?: string;
}

export interface PatchApplication {
  id: number;
  mode: string;          // merge | replace | ops
  summary: string;
  created_at: string;
  undone_at: string | null;
}

/** Réponse 200 de `POST /api/apps/<id>/operations/` (I4). */
export interface OperationsApplied {
  application: PatchApplication;
  version: string;
  spec: AppSpec;
}

/** Réponse de `POST /api/apps/<id>/operations/essai/` (I4). */
export interface OperationsTrial { ok: boolean; erreurs: string[]; resume: OperationsSummary; }

export interface ChatMessage extends PersistedChatMessage {}

// ── Jetons MCP et connexion de Claude Code / Vibe (I5) ────────────────────────

export type McpScope = 'lire' | 'ecrire';

export interface McpToken {
  id: number;
  name: string;
  prefix: string;
  scope: McpScope;
  spec_id: number | null;
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  revoked: boolean;
  /** Présent une seule fois, dans la réponse de création. */
  token?: string;
}

/** `GET /api/mcp/info/` : les commandes portent `<JETON>` littéral. */
export interface McpInfo { url: string; claude: string; vibe: string; }

/** Un modèle proposé par `GET /api/models/` et ce qu'il peut tenir. */
export interface ModelInfo {
  id: string;
  label: string;
  context_window: number;
  max_output: number;
  /** Le modèle sait appeler des outils (I4) ; sinon le serveur passe par une sortie structurée. */
  tools?: boolean;
}

/** Réponse de `GET /api/models/` : les modèles par fournisseur. */
export interface ModelCatalogue {
  providers: Record<AiProvider, { default: string; models: ModelInfo[] }>;
  lot_budget_tokens: number;
}

/** Ce que pèse un envoi face à ce que le modèle peut tenir (`/api/chat/` et `/api/chat/estimate/`). */
export interface ChatContext {
  model: string;
  provider: AiProvider;
  context_window: number;
  reserved_output_tokens: number;
  available_tokens: number;
  /** Consignes + spécification ; `spec_tokens` y est compris. */
  system_tokens: number;
  spec_tokens: number;
  history_tokens: number;
  estimated_tokens: number;
  /** `estimated_tokens / available_tokens` — peut dépasser 1. */
  ratio: number;
  fits: boolean;
  messages_sent: number;
  messages_dropped: number;
  /** I4 : poids des définitions d'outils et de l'index compact de la spec. */
  tools_tokens?: number;
  index_tokens?: number;
  /** Ajouts de B (compatibles) : réserve pour les appels d'outils, et poids des résultats d'outils. */
  reserved_tool_tokens?: number;
  tool_results_tokens?: number;
}

// ── La spécification vue du lab : GET /api/apps/<id>/lab/ ─────────────────────

export type BlockerCode =
  | 'project_name' | 'app_type' | 'required_groups' | 'empty'
  | 'file_field' | 'orphan_reference' | 'context_budget';

export interface Blocker {
  code: BlockerCode;
  message: string;      // s'affiche tel quel
}

export interface LabFootprint {
  project_name: string;
  project_name_valid: boolean;
  app_type: string;
  constructible: boolean;
  containers: { name: string; role: string }[];
  paths: { frontend: string | null; api: string | null };
  keycloak: { client_id: string; required_groups: string[]; locks: string[] };
  database: { instance: string; database: string; schema: string; tables: number } | null;
  storage: { used: boolean; fields: string[]; legacy_file_fields: string[]; rule: string };
  email: { used: boolean; rule: string };
  public_routes: { method: string; path: string; group: string; reason: string }[];
  deployment: string;
}

export interface LabView {
  ready: boolean;
  blockers: Blocker[];
  footprint: LabFootprint;
}

/** Forme d'un nom de projet du lab (règle 1 de `check-app-name.sh`) ; `null` si elle est respectée. */
export function projectNameError(name: string): string | null {
  if (!/^[a-z][a-z0-9-]{1,38}[a-z0-9]$/.test(name)) {
    return 'Le nom de projet fait 3 à 40 caractères : minuscules, chiffres et tirets, '
      + 'commence par une lettre et ne finit pas par un tiret.';
  }
  if (name.includes('--')) return 'Le nom de projet ne contient pas deux tirets de suite.';
  return null;
}

// ── Les livrables : GET /api/apps/<id>/livrables/ ─────────────────────────────
// Ce qui serait remis au lab pour construire l'app : cahier des charges et lots
// de la feuille de route, générés par le serveur (jamais par le navigateur).

export type LotFamily = 'modeles' | 'api' | 'regles' | 'services' | 'pages' | 'pipelines' | 'jobs' | 'recette';
export type LotElementKind = 'data_model' | 'endpoint_group' | 'business_rule' | 'service' | 'page' | 'pipeline';

export interface LotElement {
  kind: LotElementKind;
  name: string;
  page?: string;        // seulement pour un `pipeline` : la page qui le porte
}

export interface GeneratedLot {
  number: number;
  family: LotFamily;
  title: string;
  objective: string;
  tasks: string[];
  tests: string[];
  tokens: number;       // poids estimé du lot, en jetons
  elements: LotElement[];
}

export interface LivrablesContext {
  cahier_tokens: number;
  largest_lot_tokens: number;
  lot_budget_tokens: number;
}

export interface Livrables {
  spec: { id: number; name: string; updated_at: string };
  ready: boolean;
  blockers: Blocker[];
  create: { name: string; type: string; required_groups: string[] };
  counts: { data_models: number; endpoints: number; pages: number; lots: number };
  context: LivrablesContext;
  lots: GeneratedLot[];
  lots_md: string;                  // '' quand la spec est vide
  cahier_des_charges_md: string;
}

// ── Graphe de la spec, à toutes les échelles (`GET /api/apps/<id>/graph/`) ───
// Formes définies par `backend/api/graphe.py` (v1, puis v2 : contrat app-builder-v2, I6) :
// rien n'est recalculé côté interface. Les clés v2 sont facultatives ici pour qu'une
// réponse d'un serveur v1 reste lisible.

export type GraphScaleId =
  | 'overview' | 'architecture' | 'data' | 'pipelines' | 'roadmap'
  // v2
  | 'api' | 'pages' | 'security' | 'lifecycles' | 'jobs'
  | (string & {});

export type GraphNotation = 'c4' | 'tree' | 'er' | 'sitemap' | 'sequence' | 'matrix' | 'statechart' | 'timeline' | 'kanban';

export interface GraphScale {
  id: GraphScaleId;
  label: string;
  notation?: GraphNotation;
  available?: boolean;
  reason?: string;
}

export type GraphNodeKind =
  | 'groups' | 'keycloak' | 'frontend' | 'api' | 'database' | 'storage' | 'email' | 'business_rule'
  | 'endpoint_group' | 'endpoint' | 'service' | 'page'
  | 'data_model'
  | 'interaction' | 'pipeline' | 'step'
  | 'lot'
  // v2
  | 'role' | 'job' | 'integration' | 'external_api' | 'state' | 'transition'
  | (string & {});

export interface GraphIssue { code: string; message: string; node?: string; }

export interface GraphNode {
  id: string;
  kind: GraphNodeKind;
  scale: GraphScaleId;
  label: string;
  parent: string | null;            // id du nœud plus large dont celui-ci descend
  detail: string;
  count?: number;
  opens?: GraphScaleId;             // échelle où l'on entre en cliquant
  fields?: { name: string; type: string }[];   // `data_model`
  public?: boolean;                 // `endpoint` : appelable sans connexion
  roles?: string[];                 // `endpoint`
  order?: number;                   // `step` (rang à partir de 0), `lot` (numéro)
  family?: LotFamily;               // `lot`
  tokens?: number;                  // `lot`
  // ── v2 ──
  ref?: { collection: string; id: number | null; name?: string };
  edit?: { route: string; query: Record<string, string | number> };
  attrs?: Record<string, unknown>;
  lots?: number[];
  appears_in?: GraphScaleId[];
  issues?: GraphIssue[];
}

export type GraphLinkKind =
  | 'flow' | 'contains' | 'uses' | 'calls' | 'reads' | 'relation' | 'triggers' | 'next' | 'invokes' | 'builds'
  | (string & {});

export interface GraphLink {
  source: string;
  target: string;
  kind: GraphLinkKind;
  label: string;
  // ── v2 ──
  id?: string;
  cardinality?: { source: string; target: string } | null;
}

export interface SecurityMatrix {
  rows: string[];
  cols: string[];
  cells: string[][];
  notes: Record<string, string>;
}

export interface CrudMatrix {
  rows: string[];
  cols: string[];
  cells: string[][][];
}

export interface GraphSequence {
  pipeline: string;
  lifelines: string[];
  messages: { from: number | string; to: number | string; label: string; step?: string }[];
}

export interface SpecGraph {
  spec: { id: number; name: string; updated_at: string };
  scales: GraphScale[];
  nodes: GraphNode[];
  links: GraphLink[];
  // ── v2 ──
  version?: number;
  kinds?: Record<string, { label: string; cat: string }>;
  issues?: GraphIssue[];
  matrices?: { security?: SecurityMatrix; crud?: CrudMatrix };
  sequences?: GraphSequence[];
}
