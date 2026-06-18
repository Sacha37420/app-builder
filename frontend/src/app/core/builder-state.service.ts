import { Injectable, signal } from '@angular/core';
import {
  AppSpec, DataModel, ModelField, ModelRelationship,
  EndpointGroup, Endpoint, FrontendService, Page,
  Interaction, Pipeline, PipelineStep, PageComponent,
  OperationType, PageLayout,
} from '../models/app-spec.model';

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
  readonly spec = signal<AppSpec>({ ...EMPTY_SPEC, data_models: [], endpoint_groups: [], services: [], pages: [] });
  readonly savedId = signal<number | null>(null);
  readonly isDirty = signal(false);

  private nextId = -1;
  private tid(): number { return this.nextId--; }

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
    this.spec.set({ ...EMPTY_SPEC, data_models: [], endpoint_groups: [], services: [], pages: [] });
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

  // ── Helpers ───────────────────────────────────────────────────────────────────

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
