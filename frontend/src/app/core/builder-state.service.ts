import { Injectable, signal, inject } from '@angular/core';
import { Subject, throwError } from 'rxjs';
import { debounceTime, filter, switchMap, tap, catchError } from 'rxjs/operators';
import { Observable } from 'rxjs';
import {
  AppSpec, DataModel, ModelField, ModelRelationship,
  EndpointGroup, Endpoint, FrontendService, Page,
  Interaction, Pipeline, PipelineStep, PageComponent,
  OperationType, PageLayout, AgentPatch,
} from '../models/app-spec.model';
import { BuilderApiService } from './builder-api.service';

export type SaveStatus = 'idle' | 'pending' | 'saving' | 'saved' | 'error';

const EMPTY_SPEC: AppSpec = {
  name: 'Mon Application',
  description: '',
  data_models: [],
  endpoint_groups: [],
  services: [],
  pages: [],
};

@Injectable({ providedIn: 'root' })
export class BuilderStateService {
  private api = inject(BuilderApiService);

  readonly spec = signal<AppSpec>({ ...EMPTY_SPEC });
  readonly savedId = signal<number | null>(null);
  readonly isDirty = signal(false);
  readonly saveStatus = signal<SaveStatus>('idle');

  private debounceTrigger = new Subject<void>();

  constructor() {
    // Autosave : 3 s après la dernière modification, si un ID existe déjà
    this.debounceTrigger.pipe(
      debounceTime(3000),
      filter(() => this.savedId() !== null),
      switchMap(() => {
        this.saveStatus.set('saving');
        return this.api.updateApp(this.savedId()!, this.spec()).pipe(
          tap(saved => {
            this.savedId.set(saved.id!);
            this.isDirty.set(false);
            this.saveStatus.set('saved');
          }),
          catchError(() => {
            this.saveStatus.set('error');
            return throwError(() => new Error('autosave failed'));
          }),
        );
      }),
    ).subscribe();
  }

  private mutate(fn: (s: AppSpec) => AppSpec): void {
    this.spec.update(fn);
    this.isDirty.set(true);
    if (this.savedId() !== null) {
      this.saveStatus.set('pending');
      this.debounceTrigger.next();
    }
  }

  /** Sauvegarde immédiate — crée si pas encore d'ID, met à jour sinon. */
  saveNow(): Observable<AppSpec> {
    const id = this.savedId();
    this.saveStatus.set('saving');
    const obs = id
      ? this.api.updateApp(id, this.spec())
      : this.api.createApp(this.spec());
    return obs.pipe(
      tap(saved => {
        this.savedId.set(saved.id!);
        this.isDirty.set(false);
        this.saveStatus.set('saved');
      }),
      catchError(err => {
        this.saveStatus.set('error');
        return throwError(() => err);
      }),
    );
  }

  loadSpec(spec: AppSpec): void {
    this.spec.set(spec);
    this.savedId.set(spec.id ?? null);
    this.isDirty.set(false);
    this.saveStatus.set('saved');
  }

  resetSpec(): void {
    this.spec.set({ ...EMPTY_SPEC });
    this.savedId.set(null);
    this.isDirty.set(false);
    this.saveStatus.set('idle');
  }

  markSaved(id: number): void {
    this.savedId.set(id);
    this.isDirty.set(false);
    this.saveStatus.set('saved');
  }

  updateMeta(name: string, description: string): void {
    this.mutate(s => ({ ...s, name, description }));
  }

  // ── Phase 1 : DataModels ─────────────────────────────────────────────────────

  addDataModel(): void {
    const dm: DataModel = {
      id: this.tid(), name: 'NouvelleEntite', description: '',
      fields: [], relationships: [], order: this.spec().data_models.length,
    };
    this.mutate(s => ({ ...s, data_models: [...s.data_models, dm] }));
  }

  updateDataModel(id: number, patch: Partial<DataModel>): void {
    this.mutate(s => ({
      ...s,
      data_models: s.data_models.map(m => m.id === id ? { ...m, ...patch } : m),
    }));
  }

  removeDataModel(id: number): void {
    this.mutate(s => ({
      ...s,
      data_models: s.data_models.filter(m => m.id !== id),
      endpoint_groups: s.endpoint_groups.map(g => ({
        ...g,
        endpoints: g.endpoints.map(e =>
          e.linked_model_name === s.data_models.find(m => m.id === id)?.name
            ? { ...e, linked_model_name: '' }
            : e,
        ),
      })),
    }));
  }

  addField(modelId: number): void {
    const field: ModelField = {
      name: 'nouveau_champ', type: 'string', required: true, unique: false,
    };
    this.mutate(s => ({
      ...s,
      data_models: s.data_models.map(m =>
        m.id === modelId ? { ...m, fields: [...m.fields, field] } : m,
      ),
    }));
  }

  updateField(modelId: number, idx: number, patch: Partial<ModelField>): void {
    this.mutate(s => ({
      ...s,
      data_models: s.data_models.map(m => {
        if (m.id !== modelId) return m;
        const fields = m.fields.map((f, i) => i === idx ? { ...f, ...patch } : f);
        return { ...m, fields };
      }),
    }));
  }

  removeField(modelId: number, idx: number): void {
    this.mutate(s => ({
      ...s,
      data_models: s.data_models.map(m => {
        if (m.id !== modelId) return m;
        return { ...m, fields: m.fields.filter((_, i) => i !== idx) };
      }),
    }));
  }

  addRelationship(modelId: number): void {
    const rel: ModelRelationship = {
      name: 'nouvelle_relation', rel_type: 'FK', to_model: '', related_name: '', on_delete: 'CASCADE',
    };
    this.mutate(s => ({
      ...s,
      data_models: s.data_models.map(m =>
        m.id === modelId ? { ...m, relationships: [...m.relationships, rel] } : m,
      ),
    }));
  }

  updateRelationship(modelId: number, idx: number, patch: Partial<ModelRelationship>): void {
    this.mutate(s => ({
      ...s,
      data_models: s.data_models.map(m => {
        if (m.id !== modelId) return m;
        const relationships = m.relationships.map((r, i) => i === idx ? { ...r, ...patch } : r);
        return { ...m, relationships };
      }),
    }));
  }

  removeRelationship(modelId: number, idx: number): void {
    this.mutate(s => ({
      ...s,
      data_models: s.data_models.map(m => {
        if (m.id !== modelId) return m;
        return { ...m, relationships: m.relationships.filter((_, i) => i !== idx) };
      }),
    }));
  }

  // ── Phase 2 : EndpointGroups / Endpoints ─────────────────────────────────────

  addEndpointGroup(): void {
    const group: EndpointGroup = {
      id: this.tid(), name: 'NouveauGroupe', description: '',
      order: this.spec().endpoint_groups.length, endpoints: [],
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
      services: s.services.map(sv => ({
        ...sv,
        endpoint_group_ids: sv.endpoint_group_ids.filter(gid => gid !== id),
      })),
    }));
  }

  addEndpoint(groupId: number): void {
    const ep: Endpoint = {
      id: this.tid(), method: 'GET', path: '/nouveau', description: '',
      order: 0, operation: 'custom', linked_model_name: '',
      auth_required: true, required_roles: [],
      request_schema: null, response_schema: null, query_params: [],
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

  // ── Phase 3 : Services / Pages ───────────────────────────────────────────────

  addService(): void {
    const svc: FrontendService = {
      id: this.tid(), name: 'NouveauService',
      order: this.spec().services.length, endpoint_group_ids: [],
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
        ...p, service_ids: p.service_ids.filter(sid => sid !== id),
      })),
    }));
  }

  addPage(): void {
    const page: Page = {
      id: this.tid(), name: 'NouvellePage', route: '/nouvelle',
      order: this.spec().pages.length, layout: 'mixed', components: [],
      service_ids: [], interactions: [], pipelines: [],
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

  addComponent(pageId: number): void {
    const comp: PageComponent = { type: 'table', label: 'Nouveau composant' };
    this.mutate(s => ({
      ...s,
      pages: s.pages.map(p =>
        p.id === pageId ? { ...p, components: [...p.components, comp] } : p,
      ),
    }));
  }

  updateComponent(pageId: number, idx: number, patch: Partial<PageComponent>): void {
    this.mutate(s => ({
      ...s,
      pages: s.pages.map(p => {
        if (p.id !== pageId) return p;
        return { ...p, components: p.components.map((c, i) => i === idx ? { ...c, ...patch } : c) };
      }),
    }));
  }

  removeComponent(pageId: number, idx: number): void {
    this.mutate(s => ({
      ...s,
      pages: s.pages.map(p =>
        p.id === pageId ? { ...p, components: p.components.filter((_, i) => i !== idx) } : p,
      ),
    }));
  }

  addInteraction(pageId: number): void {
    const inter: Interaction = {
      id: this.tid(), name: 'Nouvelle interaction',
      type: 'click', description: '', order: 0,
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

  // ── Phase 4 : Pipelines ───────────────────────────────────────────────────────

  addPipeline(pageId: number): void {
    const pipe: Pipeline = {
      id: this.tid(), name: 'Nouveau pipeline',
      description: '', steps: [], order: 0,
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

  addPipelineStep(pageId: number, pipeId: number): void {
    const step: PipelineStep = { label: 'Nouvelle étape', type: 'trigger' };
    this.mutate(s => ({
      ...s,
      pages: s.pages.map(p =>
        p.id === pageId
          ? {
              ...p,
              pipelines: p.pipelines.map(pl =>
                pl.id === pipeId ? { ...pl, steps: [...pl.steps, step] } : pl,
              ),
            }
          : p,
      ),
    }));
  }

  updatePipelineStep(pageId: number, pipeId: number, idx: number, patch: Partial<PipelineStep>): void {
    this.mutate(s => ({
      ...s,
      pages: s.pages.map(p =>
        p.id === pageId
          ? {
              ...p,
              pipelines: p.pipelines.map(pl =>
                pl.id === pipeId
                  ? { ...pl, steps: pl.steps.map((st, i) => i === idx ? { ...st, ...patch } : st) }
                  : pl,
              ),
            }
          : p,
      ),
    }));
  }

  removePipelineStep(pageId: number, pipeId: number, idx: number): void {
    this.mutate(s => ({
      ...s,
      pages: s.pages.map(p =>
        p.id === pageId
          ? {
              ...p,
              pipelines: p.pipelines.map(pl =>
                pl.id === pipeId
                  ? { ...pl, steps: pl.steps.filter((_, i) => i !== idx) }
                  : pl,
              ),
            }
          : p,
      ),
    }));
  }

  // ── Agent IA : application de patch ──────────────────────────────────────────

  mergeFromAgent(patch: AgentPatch): void {
    const s = this.spec();

    const newMeta = patch.set_meta
      ? { name: patch.set_meta.name ?? s.name, description: patch.set_meta.description ?? s.description }
      : {};

    const newModels = (patch.data_models ?? []).map((m, i) => ({
      ...m, id: this.tid(), order: s.data_models.length + i,
    }));

    const newGroups = (patch.endpoint_groups ?? []).map((g, i) => ({
      ...g,
      id: this.tid(),
      order: s.endpoint_groups.length + i,
      endpoints: (g.endpoints ?? []).map((e, j) => ({
        ...e, id: this.tid(), order: j,
        operation: e.operation ?? 'custom',
        linked_model_name: e.linked_model_name ?? '',
        auth_required: e.auth_required ?? true,
        required_roles: e.required_roles ?? [],
        request_schema: e.request_schema ?? null,
        response_schema: e.response_schema ?? null,
        query_params: e.query_params ?? [],
      })),
    }));

    const allGroups = [...s.endpoint_groups, ...newGroups];

    const newServices = (patch.services ?? []).map((sv, i) => {
      const groupIds = (sv.endpoint_group_names ?? [])
        .map(n => allGroups.find(g => g.name === n)?.id)
        .filter((id): id is number => id !== undefined);
      return { id: this.tid(), name: sv.name, order: s.services.length + i, endpoint_group_ids: groupIds };
    });

    const allServices = [...s.services, ...newServices];

    const newPages = (patch.pages ?? []).map((p, i) => {
      const serviceIds = (p.service_names ?? [])
        .map(n => allServices.find(sv => sv.name === n)?.id)
        .filter((id): id is number => id !== undefined);
      return {
        id: this.tid(),
        name: p.name,
        route: p.route,
        layout: p.layout ?? 'mixed',
        order: s.pages.length + i,
        service_ids: serviceIds,
        components: p.components ?? [],
        interactions: (p.interactions ?? []).map((inter, j) => ({
          ...inter, id: this.tid(), order: j,
        })),
        pipelines: (p.pipelines ?? []).map((pl, k) => ({
          ...pl, id: this.tid(), order: k,
          steps: pl.steps ?? [],
        })),
      };
    });

    this.mutate(cur => ({
      ...cur,
      ...newMeta,
      data_models: [...cur.data_models, ...newModels],
      endpoint_groups: allGroups,
      services: allServices,
      pages: [...cur.pages, ...newPages],
    }));
  }

  replaceFromAgent(patch: AgentPatch): void {
    this.mutate(() => ({
      name: patch.set_meta?.name ?? 'Mon Application',
      description: patch.set_meta?.description ?? '',
      data_models: [],
      endpoint_groups: [],
      services: [],
      pages: [],
    }));
    this.mergeFromAgent({ ...patch, set_meta: undefined });
  }

  patchSummary(patch: AgentPatch): string {
    const parts: string[] = [];
    if (patch.set_meta?.name) parts.push(`nom → "${patch.set_meta.name}"`);
    if (patch.data_models?.length) parts.push(`${patch.data_models.length} modèle(s)`);
    if (patch.endpoint_groups?.length) {
      const epCount = patch.endpoint_groups.reduce((s, g) => s + g.endpoints.length, 0);
      parts.push(`${patch.endpoint_groups.length} groupe(s) / ${epCount} endpoint(s)`);
    }
    if (patch.services?.length) parts.push(`${patch.services.length} service(s)`);
    if (patch.pages?.length) parts.push(`${patch.pages.length} page(s)`);
    return parts.join(' · ') || 'patch vide';
  }

  // ── Helpers ───────────────────────────────────────────────────────────────────

  private nextId = -1;
  private tid(): number { return this.nextId--; }

  toggleGroupLink(svcId: number, groupId: number): void {
    const svc = this.spec().services.find(s => s.id === svcId);
    if (!svc) return;
    const ids = svc.endpoint_group_ids.includes(groupId)
      ? svc.endpoint_group_ids.filter(id => id !== groupId)
      : [...svc.endpoint_group_ids, groupId];
    this.updateService(svcId, { endpoint_group_ids: ids });
  }

  toggleServiceLink(pageId: number, svcId: number): void {
    const page = this.spec().pages.find(p => p.id === pageId);
    if (!page) return;
    const ids = page.service_ids.includes(svcId)
      ? page.service_ids.filter(id => id !== svcId)
      : [...page.service_ids, svcId];
    this.updatePage(pageId, { service_ids: ids });
  }

  getGroupName(id: number): string {
    return this.spec().endpoint_groups.find(g => g.id === id)?.name ?? `#${id}`;
  }

  getServiceName(id: number): string {
    return this.spec().services.find(s => s.id === id)?.name ?? `#${id}`;
  }

  getModelNames(): string[] {
    return this.spec().data_models.map(m => m.name);
  }
}
