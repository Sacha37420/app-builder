import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  AppSpec, ChatMessage, AiProvider, AgentPatch, PersistedChatMessage, PatchApplication, PatchMode, LabView,
} from '../models/app-spec.model';

interface ChatResponse {
  content: string;
  provider: string;
  spec_patch: AgentPatch | null;
  patch_summary: string | null;
  choices: { multiple: boolean; items: string[] } | null;
}

interface EnvWindow {
  __env?: { apiUrl?: string };
}

@Injectable({ providedIn: 'root' })
export class BuilderApiService {
  private http = inject(HttpClient);

  private get base(): string {
    return (window as unknown as EnvWindow).__env?.apiUrl ?? 'http://localhost:8087';
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

  deleteApp(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/api/apps/${id}/`);
  }

  chat(
    messages: ChatMessage[],
    appSpec: AppSpec | null,
    provider: AiProvider,
    apiKey: string,
    model: string,
  ): Observable<ChatResponse> {
    const cleanMessages = messages.map(m => ({ role: m.role, content: m.content }));
    return this.http.post<ChatResponse>(
      `${this.base}/api/chat/`,
      { messages: cleanMessages, app_spec: appSpec, provider, api_key: apiKey, model },
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
