import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { apiUrl } from './env';
import {
  AppSpec, ChatMessage, AiProvider, PersistedChatMessage, PatchApplication, LabView, Livrables,
  ModelCatalogue, ChatContext, SpecGraph, ChatResponse, SpecOperation, OperationsApplied, OperationsTrial,
  McpToken, McpInfo, McpScope,
} from '../models/app-spec.model';

export interface AiKeysState { claude_key_configured: boolean; mistral_key_configured: boolean; }

/** Clés de la spec qui ne partent jamais vers l'IA : la conversation voyage dans `messages`. */
const HORS_ENVOI_IA = ['chat_history', 'created_at', 'updated_at', 'owner_email', 'version'];

function specPourIa(spec: AppSpec | null): Record<string, unknown> | null {
  if (!spec) return null;
  return Object.fromEntries(Object.entries(spec).filter(([cle]) => !HORS_ENVOI_IA.includes(cle)));
}

/** L'historique repart en texte seulement (I4) : jamais une proposition, des choix ni un appel d'outil. */
function messagesPourIa(messages: ChatMessage[]): { role: string; content: string }[] {
  return messages.map(m => ({ role: m.role, content: m.content }));
}

@Injectable({ providedIn: 'root' })
export class BuilderApiService {
  private http = inject(HttpClient);

  private get base(): string {
    return apiUrl();
  }

  listApps(): Observable<AppSpec[]> {
    return this.http.get<AppSpec[]>(`${this.base}/api/apps/`);
  }

  createApp(spec: Partial<AppSpec>): Observable<AppSpec> {
    return this.http.post<AppSpec>(`${this.base}/api/apps/`, specPourEcriture(spec));
  }

  /** La spec enregistrée ; porte `version` (I4) quand le serveur la fournit. */
  getApp(id: number): Observable<AppSpec> {
    return this.http.get<AppSpec>(`${this.base}/api/apps/${id}/`);
  }

  updateApp(id: number, spec: AppSpec): Observable<AppSpec> {
    return this.http.put<AppSpec>(`${this.base}/api/apps/${id}/`, specPourEcriture(spec));
  }

  /** La spec enregistrée vue du lab : prête ou non, blocages, empreinte. */
  getLab(id: number): Observable<LabView> {
    return this.http.get<LabView>(`${this.base}/api/apps/${id}/lab/`);
  }

  /** Ce qui serait remis au lab pour la spec enregistrée : cahier des charges et lots. */
  getLivrables(id: number): Observable<Livrables> {
    return this.http.get<Livrables>(`${this.base}/api/apps/${id}/livrables/`);
  }

  /** La spec enregistrée en graphe, à toutes les échelles (I6). */
  getGraph(id: number): Observable<SpecGraph> {
    return this.http.get<SpecGraph>(`${this.base}/api/apps/${id}/graph/`);
  }

  deleteApp(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/api/apps/${id}/`);
  }

  /**
   * Un tour de conversation (I4). La spec est lue en base par le serveur (`app_id`) :
   * elle ne part jamais du navigateur.
   */
  chat(appId: number, messages: ChatMessage[], provider: AiProvider, model: string): Observable<ChatResponse> {
    // Aucune clé dans l'envoi : le serveur prend celle du coffre de l'utilisateur.
    return this.http.post<ChatResponse>(
      `${this.base}/api/chat/`,
      { app_id: appId, messages: messagesPourIa(messages), provider, model },
    );
  }

  /** Applique une proposition (I4) ; 409 `version_perimee` si la spec a changé depuis. */
  applyOperations(id: number, operations: SpecOperation[], baseVersion: string): Observable<OperationsApplied> {
    return this.http.post<OperationsApplied>(
      `${this.base}/api/apps/${id}/operations/`, { operations, base_version: baseVersion },
    );
  }

  /** Essai à blanc d'une liste d'opérations : rien n'est écrit. */
  tryOperations(id: number, operations: SpecOperation[]): Observable<OperationsTrial> {
    return this.http.post<OperationsTrial>(`${this.base}/api/apps/${id}/operations/essai/`, { operations });
  }

  /** Coffre des clés d'API : seulement « configurée ou non », jamais la clé. */
  getAiKeys(): Observable<AiKeysState> {
    return this.http.get<AiKeysState>(`${this.base}/api/ai-keys/`);
  }

  /** Dépose (ou, chaîne vide, supprime) une clé dans le coffre. Réponse 204. */
  putAiKeys(keys: { claude_key?: string; mistral_key?: string }): Observable<void> {
    return this.http.put<void>(`${this.base}/api/ai-keys/`, keys);
  }

  /** Les modèles proposés, par fournisseur, et la fenêtre de chacun. */
  getModels(): Observable<ModelCatalogue> {
    return this.http.get<ModelCatalogue>(`${this.base}/api/models/`);
  }

  /**
   * La place qu'occuperait un envoi : aucun appel à une IA, aucune clé, aucun coût.
   * Route inchangée par le contrat : elle reçoit encore `app_spec` ; `app_id` est
   * joint pour un serveur qui mesure désormais la spec enregistrée.
   */
  estimateChat(
    appId: number | null,
    messages: ChatMessage[],
    appSpec: AppSpec | null,
    provider: AiProvider,
    model: string,
  ): Observable<{ context: ChatContext }> {
    return this.http.post<{ context: ChatContext }>(
      `${this.base}/api/chat/estimate/`,
      { app_id: appId, messages: messagesPourIa(messages), app_spec: specPourIa(appSpec), provider, model },
    );
  }

  saveChatHistory(id: number, history: PersistedChatMessage[]): Observable<{ ok: boolean }> {
    return this.http.patch<{ ok: boolean }>(`${this.base}/api/apps/${id}/chat/`, { chat_history: history });
  }

  undoPatch(id: number, applicationId: number): Observable<{ spec: AppSpec; application: PatchApplication }> {
    return this.http.post<{ spec: AppSpec; application: PatchApplication }>(
      `${this.base}/api/apps/${id}/patches/${applicationId}/undo/`, {},
    );
  }

  // ── Jetons MCP (I5) ─────────────────────────────────────────────────────────

  listMcpTokens(): Observable<McpToken[]> {
    return this.http.get<McpToken[]>(`${this.base}/api/mcp-tokens/`);
  }

  /** Le jeton complet (`token`) n'est rendu que par cette réponse. */
  createMcpToken(body: { name: string; scope: McpScope; spec_id?: number; days?: number }): Observable<McpToken> {
    return this.http.post<McpToken>(`${this.base}/api/mcp-tokens/`, body);
  }

  revokeMcpToken(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/api/mcp-tokens/${id}/`);
  }

  getMcpInfo(): Observable<McpInfo> {
    return this.http.get<McpInfo>(`${this.base}/api/mcp/info/`);
  }
}

/** `version` est en lecture seule (I4) : il ne repart pas dans un enregistrement. */
function specPourEcriture<T extends Partial<AppSpec>>(spec: T): T {
  if (!('version' in spec)) return spec;
  const { version: _v, ...rest } = spec;
  return rest as T;
}
