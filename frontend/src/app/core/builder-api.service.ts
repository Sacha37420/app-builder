import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { apiUrl } from './env';
import {
  AppSpec, ChatMessage, AiProvider, AgentPatch, PersistedChatMessage, PatchApplication, PatchMode, LabView, Livrables,
  ModelCatalogue, ChatContext, SpecGraph,
} from '../models/app-spec.model';

interface ChatResponse {
  content: string;
  provider: string;
  spec_patch: AgentPatch | null;
  patch_summary: string | null;
  choices: { multiple: boolean; items: string[] } | null;
  context?: ChatContext;
}

export interface AiKeysState { claude_key_configured: boolean; mistral_key_configured: boolean; }

/** Clés de la spec qui ne partent jamais vers l'IA : la conversation voyage dans `messages`. */
const HORS_ENVOI_IA = ['chat_history', 'created_at', 'updated_at', 'owner_email'];

function specPourIa(spec: AppSpec | null): Record<string, unknown> | null {
  if (!spec) return null;
  return Object.fromEntries(Object.entries(spec).filter(([cle]) => !HORS_ENVOI_IA.includes(cle)));
}

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
    return this.http.post<AppSpec>(`${this.base}/api/apps/`, spec);
  }

  getApp(id: number): Observable<AppSpec> {
    return this.http.get<AppSpec>(`${this.base}/api/apps/${id}/`);
  }

  updateApp(id: number, spec: AppSpec): Observable<AppSpec> {
    return this.http.put<AppSpec>(`${this.base}/api/apps/${id}/`, spec);
  }

  /** La spec enregistrée vue du lab : prête ou non, blocages, empreinte. */
  getLab(id: number): Observable<LabView> {
    return this.http.get<LabView>(`${this.base}/api/apps/${id}/lab/`);
  }

  /** Ce qui serait remis au lab pour la spec enregistrée : cahier des charges et lots. */
  getLivrables(id: number): Observable<Livrables> {
    return this.http.get<Livrables>(`${this.base}/api/apps/${id}/livrables/`);
  }

  /** La spec enregistrée en graphe, à toutes les échelles (du lab à l'étape de pipeline). */
  getGraph(id: number): Observable<SpecGraph> {
    return this.http.get<SpecGraph>(`${this.base}/api/apps/${id}/graph/`);
  }

  deleteApp(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/api/apps/${id}/`);
  }

  chat(
    messages: ChatMessage[],
    appSpec: AppSpec | null,
    provider: AiProvider,
    model: string,
  ): Observable<ChatResponse> {
    // Aucune clé dans l'envoi : le serveur prend celle du coffre de l'utilisateur.
    return this.http.post<ChatResponse>(
      `${this.base}/api/chat/`,
      { messages: messagesPourIa(messages), app_spec: specPourIa(appSpec), provider, model },
    );
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

  /** La place qu'occuperait un envoi : aucun appel à une IA, aucune clé, aucun coût. */
  estimateChat(
    messages: ChatMessage[],
    appSpec: AppSpec | null,
    provider: AiProvider,
    model: string,
  ): Observable<{ context: ChatContext }> {
    return this.http.post<{ context: ChatContext }>(
      `${this.base}/api/chat/estimate/`,
      { messages: messagesPourIa(messages), app_spec: specPourIa(appSpec), provider, model },
    );
  }

  saveChatHistory(id: number, history: PersistedChatMessage[]): Observable<{ ok: boolean }> {
    return this.http.patch<{ ok: boolean }>(`${this.base}/api/apps/${id}/chat/`, { chat_history: history });
  }

  applyPatch(id: number, patch: AgentPatch, mode: PatchMode): Observable<{ spec: AppSpec; application: PatchApplication }> {
    return this.http.post<{ spec: AppSpec; application: PatchApplication }>(
      `${this.base}/api/apps/${id}/patch/`, { patch, mode },
    );
  }

  undoPatch(id: number, applicationId: number): Observable<{ spec: AppSpec; application: PatchApplication }> {
    return this.http.post<{ spec: AppSpec; application: PatchApplication }>(
      `${this.base}/api/apps/${id}/patches/${applicationId}/undo/`, {},
    );
  }
}
