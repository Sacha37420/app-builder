import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { AppSpec, ChatMessage, AiProvider, AgentPatch } from '../models/app-spec.model';

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

  deleteApp(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/api/apps/${id}/`);
  }

  chat(
    messages: ChatMessage[],
    appSpec: AppSpec | null,
    provider: AiProvider,
    apiKey: string,
    model: string,
  ): Observable<{ content: string; provider: string; spec_patch: AgentPatch | null; choices: { multiple: boolean; items: string[] } | null }> {
    const cleanMessages = messages.map(m => ({ role: m.role, content: m.content }));
    return this.http.post<{ content: string; provider: string; spec_patch: AgentPatch | null; choices: { multiple: boolean; items: string[] } | null }>(
      `${this.base}/api/chat/`,
      { messages: cleanMessages, app_spec: appSpec, provider, api_key: apiKey, model },
    );
  }
}
