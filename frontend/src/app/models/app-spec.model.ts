// ── Types de base ──────────────────────────────────────────────────────────────

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
export type InteractionType = 'click' | 'form' | 'navigation' | 'display' | 'other';
export type OperationType = 'list' | 'create' | 'retrieve' | 'update' | 'partial_update' | 'delete' | 'custom';
export type PageLayout = 'list' | 'detail' | 'form' | 'dashboard' | 'mixed';
export type PipelineStepType = 'trigger' | 'service_call' | 'transform' | 'state_update' | 'navigate' | 'error';
export type EndpointStepType = 'auth_check' | 'validate' | 'db_query' | 'db_write' | 'serialize' | 'transform' | 'error' | 'custom';
export type FieldType = 'string' | 'text' | 'int' | 'decimal' | 'bool' | 'datetime' | 'json' | 'file';
export type RelType = 'FK' | 'M2M' | 'O2O';
export type AiProvider = 'claude' | 'mistral';

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
  service_method?: string;   // ex: "ProduitService.create(formData)"
  data_flow?: string;        // ex: "CreateProduitDto → Produit"
  on_error?: string;         // comportement en cas d'erreur
}

export interface Pipeline {
  id?: number;
  name: string;
  description: string;
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

export interface AppSpec {
  id?: number;
  name: string;
  description: string;
  owner_email?: string;
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
  applied?: string;
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
    order?: number;
    steps: PipelineStep[];
  }>;
}

export interface AgentPatch {
  set_meta?: { name?: string; description?: string };
  data_models?: Omit<DataModel, 'id'>[];
  endpoint_groups?: Array<Omit<EndpointGroup, 'id'> & { endpoints: Omit<Endpoint, 'id'>[] }>;
  services?: AgentPatchService[];
  pages?: AgentPatchPage[];
  remove_models?: string[];
  remove_endpoint_groups?: string[];
  remove_services?: string[];
  remove_pages?: string[];
}

export interface ChatMessage extends PersistedChatMessage {}

// ── Helpers de génération de code ─────────────────────────────────────────────

export const DJANGO_FIELD_MAP: Record<FieldType, string> = {
  string:   'models.CharField(max_length={len})',
  text:     'models.TextField()',
  int:      'models.IntegerField()',
  decimal:  'models.DecimalField(max_digits=10, decimal_places=2)',
  bool:     'models.BooleanField(default=False)',
  datetime: 'models.DateTimeField()',
  json:     'models.JSONField(default=dict)',
  file:     'models.FileField(upload_to="uploads/")',
};

export const TS_FIELD_MAP: Record<FieldType, string> = {
  string:   'string',
  text:     'string',
  int:      'number',
  decimal:  'number',
  bool:     'boolean',
  datetime: 'string',
  json:     'unknown',
  file:     'string',
};
