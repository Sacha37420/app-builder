// ── Types de base ──────────────────────────────────────────────────────────────

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
export type InteractionType = 'click' | 'form' | 'navigation' | 'display' | 'other';
export type OperationType = 'list' | 'create' | 'retrieve' | 'update' | 'partial_update' | 'delete' | 'custom';
export type PageLayout = 'list' | 'detail' | 'form' | 'dashboard' | 'mixed';
export type PipelineStepType = 'trigger' | 'service_call' | 'transform' | 'state_update' | 'navigate' | 'error';
export type EndpointStepType = 'auth_check' | 'validate' | 'db_query' | 'db_write' | 'serialize' | 'transform' | 'error' | 'custom';
// `storage_file` : fichier d'utilisateur déposé dans le service `storage` du lab — le
// modèle n'en garde que le chemin. `file` est l'ancien type : encore lisible sur une
// spec ancienne, refusé à l'écriture par le serveur pour tout nouveau champ.
export type FieldType = 'string' | 'text' | 'int' | 'decimal' | 'bool' | 'datetime' | 'json' | 'storage_file' | 'file';
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
}

export interface ModelRelationship {
  name: string;
  rel_type: RelType;
  to_model: string;     // nom d'un autre DataModel
  related_name: string;
  on_delete?: 'CASCADE' | 'SET_NULL' | 'PROTECT' | 'DO_NOTHING';
}

export interface DataModel {
  id?: number;
  name: string;         // PascalCase, ex: "Produit"
  description: string;
  fields: ModelField[];
  relationships: ModelRelationship[];
  order: number;
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

export interface PageComponent {
  type: 'table' | 'form' | 'chart' | 'card' | 'custom';
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
}

// ── Spec complète ─────────────────────────────────────────────────────────────

export interface BusinessRule {
  title: string;        // obligatoire, non vide (400 sinon)
  description: string;
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
  chat_history?: PersistedChatMessage[];
  created_at?: string;
  updated_at?: string;
  data_models: DataModel[];
  endpoint_groups: EndpointGroup[];
  services: FrontendService[];
  pages: Page[];
}

// ── Chat ──────────────────────────────────────────────────────────────────────

export interface PersistedChatMessage {
  role: 'user' | 'assistant';
  content: string;
  spec_patch?: AgentPatch | null;
  patch_summary?: string | null;
  applied?: string;
  // Identifiant de l'application côté serveur : c'est lui qui permet d'annuler.
  application_id?: number | null;
  choices?: { multiple: boolean; items: string[] } | null;
}

export interface AgentPatchService {
  name: string;
  order?: number;
  endpoint_group_names: string[];
}

export interface AgentPatchPage {
  name: string;
  route: string;
  layout: PageLayout;
  order?: number;
  service_names: string[];
  components: PageComponent[];
  interactions: Omit<Interaction, 'id'>[];
  pipelines: Array<{
    name: string;
    description: string;
    trigger_interaction?: string;
    order?: number;
    steps: PipelineStep[];
  }>;
}

export interface AgentPatch {
  set_meta?: {
    name?: string; project_name?: string; description?: string;
    required_groups?: string[]; uses_email?: boolean;
  };
  business_rules?: BusinessRule[];
  remove_business_rules?: string[];
  data_models?: Omit<DataModel, 'id'>[];
  endpoint_groups?: Array<Omit<EndpointGroup, 'id'> & { endpoints: Omit<Endpoint, 'id'>[] }>;
  services?: AgentPatchService[];
  pages?: AgentPatchPage[];
  remove_models?: string[];
  remove_endpoint_groups?: string[];
  remove_services?: string[];
  remove_pages?: string[];
}

export type PatchMode = 'merge' | 'replace';

export interface PatchApplication {
  id: number;
  mode: PatchMode;
  summary: string;
  created_at: string;
  undone_at: string | null;
}

export interface ChatMessage extends PersistedChatMessage {}

/** Un modèle proposé par `GET /api/models/` et ce qu'il peut tenir. */
export interface ModelInfo {
  id: string;
  label: string;
  context_window: number;
  max_output: number;
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

export type LotFamily = 'modeles' | 'api' | 'regles' | 'services' | 'pages' | 'pipelines' | 'recette';
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
