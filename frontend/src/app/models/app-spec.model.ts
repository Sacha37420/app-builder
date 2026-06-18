export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
export type InteractionType = 'click' | 'form' | 'navigation' | 'display' | 'other';

export interface Endpoint {
  id?: number;
  method: HttpMethod;
  path: string;
  description: string;
  order: number;
}

export interface EndpointGroup {
  id?: number;
  name: string;
  description: string;
  order: number;
  endpoints: Endpoint[];
}

export interface FrontendService {
  id?: number;
  name: string;
  order: number;
  endpoint_group_ids: number[];
}

export interface Interaction {
  id?: number;
  name: string;
  type: InteractionType;
  description: string;
  order: number;
}

export interface Pipeline {
  id?: number;
  name: string;
  description: string;
  steps: string[];
  order: number;
}

export interface Page {
  id?: number;
  name: string;
  route: string;
  order: number;
  service_ids: number[];
  interactions: Interaction[];
  pipelines: Pipeline[];
}

export interface AppSpec {
  id?: number;
  name: string;
  description: string;
  owner_email?: string;
  created_at?: string;
  updated_at?: string;
  endpoint_groups: EndpointGroup[];
  services: FrontendService[];
  pages: Page[];
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export type AiProvider = 'claude' | 'mistral';
