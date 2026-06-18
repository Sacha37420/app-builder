import { Injectable, signal, computed } from '@angular/core';
import {
  AppSpec, EndpointGroup, Endpoint, FrontendService,
  Page, Interaction, Pipeline,
} from '../models/app-spec.model';

const EMPTY_SPEC: AppSpec = {
  name: 'Mon Application',
  description: '',
  endpoint_groups: [],
  services: [],
  pages: [],
};

@Injectable({ providedIn: 'root' })
export class BuilderStateService {
  readonly spec = signal<AppSpec>({ ...EMPTY_SPEC });
  readonly savedId = signal<number | null>(null);
  readonly isDirty = signal(false);

  private nextTempId = -1;
  private getTempId(): number { return this.nextTempId--; }

  private mutate(fn: (s: AppSpec) => AppSpec): void {
    this.spec.update(fn);
    this.isDirty.set(true);
  }

  loadSpec(spec: AppSpec): void {
    this.spec.set(spec);
    this.savedId.set(spec.id ?? null);
    this.isDirty.set(false);
  }

  resetSpec(): void {
    this.spec.set({ ...EMPTY_SPEC });
    this.savedId.set(null);
    this.isDirty.set(false);
  }

  markSaved(id: number): void {
    this.savedId.set(id);
    this.isDirty.set(false);
  }

  updateMeta(name: string, description: string): void {
    this.mutate(s => ({ ...s, name, description }));
  }

  // ── Endpoint Groups ──────────────────────────────────────────────────────────

  addEndpointGroup(): void {
    const group: EndpointGroup = {
      id: this.getTempId(),
      name: 'Nouveau groupe',
      description: '',
      order: this.spec().endpoint_groups.length,
      endpoints: [],
    };
    this.mutate(s => ({ ...s, endpoint_groups: [...s.endpoint_groups, group] }));
  }

  updateEndpointGroup(id: number, patch: Partial<EndpointGroup>): void {
    this.mutate(s => ({
      ...s,
      endpoint_groups: s.endpoint_groups.map(g => g.id === id ? { ...g, ...patch } : g),
    }));
  }

  removeEndpointGroup(id: number): void {
    this.mutate(s => ({
      ...s,
      endpoint_groups: s.endpoint_groups.filter(g => g.id !== id),
      services: s.services.map(svc => ({
        ...svc,
        endpoint_group_ids: svc.endpoint_group_ids.filter(gid => gid !== id),
      })),
    }));
  }

  addEndpoint(groupId: number): void {
    const ep: Endpoint = {
      id: this.getTempId(),
      method: 'GET',
      path: '/nouveau',
      description: '',
      order: 0,
    };
    this.mutate(s => ({
      ...s,
      endpoint_groups: s.endpoint_groups.map(g =>
        g.id === groupId
          ? { ...g, endpoints: [...g.endpoints, { ...ep, order: g.endpoints.length }] }
          : g,
      ),
    }));
  }

  updateEndpoint(groupId: number, epId: number, patch: Partial<Endpoint>): void {
    this.mutate(s => ({
      ...s,
      endpoint_groups: s.endpoint_groups.map(g =>
        g.id === groupId
          ? { ...g, endpoints: g.endpoints.map(e => e.id === epId ? { ...e, ...patch } : e) }
          : g,
      ),
    }));
  }

  removeEndpoint(groupId: number, epId: number): void {
    this.mutate(s => ({
      ...s,
      endpoint_groups: s.endpoint_groups.map(g =>
        g.id === groupId
          ? { ...g, endpoints: g.endpoints.filter(e => e.id !== epId) }
          : g,
      ),
    }));
  }

  // ── Services ─────────────────────────────────────────────────────────────────

  addService(): void {
    const svc: FrontendService = {
      id: this.getTempId(),
      name: 'NouveauService',
      order: this.spec().services.length,
      endpoint_group_ids: [],
    };
    this.mutate(s => ({ ...s, services: [...s.services, svc] }));
  }

  updateService(id: number, patch: Partial<FrontendService>): void {
    this.mutate(s => ({
      ...s,
      services: s.services.map(sv => sv.id === id ? { ...sv, ...patch } : sv),
    }));
  }

  removeService(id: number): void {
    this.mutate(s => ({
      ...s,
      services: s.services.filter(sv => sv.id !== id),
      pages: s.pages.map(p => ({
        ...p,
        service_ids: p.service_ids.filter(sid => sid !== id),
      })),
    }));
  }

  // ── Pages ────────────────────────────────────────────────────────────────────

  addPage(): void {
    const page: Page = {
      id: this.getTempId(),
      name: 'NouvellePage',
      route: '/nouvelle',
      order: this.spec().pages.length,
      service_ids: [],
      interactions: [],
      pipelines: [],
    };
    this.mutate(s => ({ ...s, pages: [...s.pages, page] }));
  }

  updatePage(id: number, patch: Partial<Page>): void {
    this.mutate(s => ({
      ...s,
      pages: s.pages.map(p => p.id === id ? { ...p, ...patch } : p),
    }));
  }

  removePage(id: number): void {
    this.mutate(s => ({ ...s, pages: s.pages.filter(p => p.id !== id) }));
  }

  addInteraction(pageId: number): void {
    const inter: Interaction = {
      id: this.getTempId(),
      name: 'Nouvelle interaction',
      type: 'click',
      description: '',
      order: 0,
    };
    this.mutate(s => ({
      ...s,
      pages: s.pages.map(p =>
        p.id === pageId
          ? { ...p, interactions: [...p.interactions, { ...inter, order: p.interactions.length }] }
          : p,
      ),
    }));
  }

  updateInteraction(pageId: number, interId: number, patch: Partial<Interaction>): void {
    this.mutate(s => ({
      ...s,
      pages: s.pages.map(p =>
        p.id === pageId
          ? { ...p, interactions: p.interactions.map(i => i.id === interId ? { ...i, ...patch } : i) }
          : p,
      ),
    }));
  }

  removeInteraction(pageId: number, interId: number): void {
    this.mutate(s => ({
      ...s,
      pages: s.pages.map(p =>
        p.id === pageId
          ? { ...p, interactions: p.interactions.filter(i => i.id !== interId) }
          : p,
      ),
    }));
  }

  addPipeline(pageId: number): void {
    const pipe: Pipeline = {
      id: this.getTempId(),
      name: 'Nouveau pipeline',
      description: '',
      steps: [],
      order: 0,
    };
    this.mutate(s => ({
      ...s,
      pages: s.pages.map(p =>
        p.id === pageId
          ? { ...p, pipelines: [...p.pipelines, { ...pipe, order: p.pipelines.length }] }
          : p,
      ),
    }));
  }

  updatePipeline(pageId: number, pipeId: number, patch: Partial<Pipeline>): void {
    this.mutate(s => ({
      ...s,
      pages: s.pages.map(p =>
        p.id === pageId
          ? { ...p, pipelines: p.pipelines.map(pl => pl.id === pipeId ? { ...pl, ...patch } : pl) }
          : p,
      ),
    }));
  }

  removePipeline(pageId: number, pipeId: number): void {
    this.mutate(s => ({
      ...s,
      pages: s.pages.map(p =>
        p.id === pageId
          ? { ...p, pipelines: p.pipelines.filter(pl => pl.id !== pipeId) }
          : p,
      ),
    }));
  }

  // ── Helpers ──────────────────────────────────────────────────────────────────

  getGroupName(id: number): string {
    return this.spec().endpoint_groups.find(g => g.id === id)?.name ?? `#${id}`;
  }

  getServiceName(id: number): string {
    return this.spec().services.find(s => s.id === id)?.name ?? `#${id}`;
  }
}
