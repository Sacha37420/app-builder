import { Injectable, signal, inject } from '@angular/core';
import { Subject, throwError } from 'rxjs';
import { debounceTime, filter, switchMap, tap, catchError } from 'rxjs/operators';
import { Observable } from 'rxjs';
import {
  AppSpec, AppType, DataModel, ModelField, ModelRelationship,
  EndpointGroup, Endpoint, FrontendService, Page,
  Interaction, Pipeline, PipelineStep, PageComponent,
  OperationType, PageLayout, AgentPatch, PersistedChatMessage,
  FieldType, RelType, HttpMethod, InteractionType,
} from '../models/app-spec.model';
import { BuilderApiService } from './builder-api.service';

export type SaveStatus = 'idle' | 'pending' | 'saving' | 'saved' | 'error';

const EMPTY_SPEC: AppSpec = {
  name: 'Mon Application',
  description: '',
  app_type: 'django-angular',
  required_groups: [],
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
  readonly chatHistory = signal<PersistedChatMessage[]>([]);
  /** Incrémenté à chaque loadSpec/resetSpec pour signaler un changement de contexte. */
  readonly specSessionId = signal(0);

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
    this.spec.set({ ...spec, required_groups: spec.required_groups ?? [] });
    this.savedId.set(spec.id ?? null);
    this.isDirty.set(false);
    this.saveStatus.set('saved');
    this.chatHistory.set(spec.chat_history ?? []);
    this.specSessionId.update(v => v + 1);
  }

  resetSpec(): void {
    this.spec.set({ ...EMPTY_SPEC });
    this.savedId.set(null);
    this.isDirty.set(false);
    this.saveStatus.set('idle');
    this.chatHistory.set([]);
    this.specSessionId.update(v => v + 1);
  }

  setChatHistory(msgs: PersistedChatMessage[]): void {
    this.chatHistory.set(msgs);
  }

  markSaved(id: number): void {
    this.savedId.set(id);
    this.isDirty.set(false);
    this.saveStatus.set('saved');
  }

  updateMeta(name: string, description: string): void {
    this.mutate(s => ({ ...s, name, description }));
  }

  updateAppType(app_type: AppType): void {
    this.mutate(s => ({ ...s, app_type }));
  }

  updateRequiredGroups(required_groups: string[]): void {
    this.mutate(s => ({ ...s, required_groups }));
  }

  addRequiredGroup(name: string): void {
    const g = name.trim();
    if (!g || this.spec().required_groups.includes(g)) return;
    this.updateRequiredGroups([...this.spec().required_groups, g]);
  }

  removeRequiredGroup(name: string): void {
    this.updateRequiredGroups(this.spec().required_groups.filter(g => g !== name));
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
    const n = this._normalizePatch(patch);
    const s = this.spec();

    const removedModels = new Set(n.remove_models ?? []);
    const removedGroups = new Set(n.remove_endpoint_groups ?? []);
    const removedSvcs   = new Set(n.remove_services ?? []);
    const removedPages  = new Set(n.remove_pages ?? []);

    const patchGroups = n.set_meta?.required_groups;
    const newMeta = n.set_meta
      ? {
          name: n.set_meta.name ?? s.name,
          description: n.set_meta.description ?? s.description,
          // Fusion (union), pas remplacement : un patch qui ajoute un groupe ne doit
          // jamais faire disparaître ceux déjà validés dans une conversation précédente.
          ...(patchGroups?.length && {
            required_groups: Array.from(new Set([...s.required_groups, ...patchGroups])),
          }),
        }
      : {};

    // ── Phase 1 : DataModels — upsert par nom ─────────────────────────────────
    const patchModelMap = new Map((n.data_models ?? []).map(m => [m.name, m]));
    const allModels: DataModel[] = [
      ...s.data_models
        .filter(m => !removedModels.has(m.name))
        .map(m => patchModelMap.has(m.name)
          ? { ...patchModelMap.get(m.name)!, id: m.id, order: m.order }
          : m),
      ...(n.data_models ?? [])
        .filter(m => !s.data_models.some(em => em.name === m.name))
        .map((m, i) => ({ ...m, id: this.tid(), order: s.data_models.length + i })),
    ];

    // ── Phase 2 : EndpointGroups — upsert par nom ────────────────────────────
    const buildEndpoints = (eps: Omit<Endpoint, 'id'>[]): Endpoint[] =>
      eps.map((e, j) => ({
        ...e, id: this.tid(), order: j,
        operation: e.operation ?? 'custom',
        linked_model_name: e.linked_model_name ?? '',
        auth_required: e.auth_required ?? true,
        required_roles: e.required_roles ?? [],
        request_schema: e.request_schema ?? null,
        response_schema: e.response_schema ?? null,
        query_params: e.query_params ?? [],
      }));

    const patchGroupMap = new Map((n.endpoint_groups ?? []).map(g => [g.name, g]));
    const allGroups: EndpointGroup[] = [
      ...s.endpoint_groups
        .filter(g => !removedGroups.has(g.name))
        .map(g => patchGroupMap.has(g.name)
          ? { ...patchGroupMap.get(g.name)!, id: g.id, order: g.order,
              endpoints: buildEndpoints(patchGroupMap.get(g.name)!.endpoints ?? []) }
          : g),
      ...(n.endpoint_groups ?? [])
        .filter(g => !s.endpoint_groups.some(eg => eg.name === g.name))
        .map((g, i) => ({
          ...g, id: this.tid(), order: s.endpoint_groups.length + i,
          endpoints: buildEndpoints(g.endpoints ?? []),
        })),
    ];

    // ── Phase 3 : Services — upsert par nom ──────────────────────────────────
    const resolveGroupIds = (names: string[]) =>
      names.map(n => allGroups.find(g => g.name === n)?.id)
           .filter((id): id is number => id !== undefined);

    const patchSvcMap = new Map((n.services ?? []).map(sv => [sv.name, sv]));
    const allServices: FrontendService[] = [
      ...s.services
        .filter(sv => !removedSvcs.has(sv.name))
        .map(sv => patchSvcMap.has(sv.name)
          ? { ...sv, endpoint_group_ids: resolveGroupIds(patchSvcMap.get(sv.name)!.endpoint_group_names ?? []) }
          : sv),
      ...(n.services ?? [])
        .filter(sv => !s.services.some(esv => esv.name === sv.name))
        .map((sv, i) => ({
          id: this.tid(), name: sv.name, order: s.services.length + i,
          endpoint_group_ids: resolveGroupIds(sv.endpoint_group_names ?? []),
        })),
    ];

    // ── Phase 3/4 : Pages — upsert par nom ───────────────────────────────────
    const resolveSvcIds = (names: string[]) =>
      names.map(n => allServices.find(sv => sv.name === n)?.id)
           .filter((id): id is number => id !== undefined);

    const buildInteractions = (items: Omit<Interaction, 'id'>[]): Interaction[] =>
      items.map((inter, j) => ({ ...inter, id: this.tid(), order: j }));

    const buildPipelines = (items: Array<Omit<Pipeline, 'id' | 'order'> & { order?: number }>): Pipeline[] =>
      items.map((pl, k) => ({
        ...pl, id: this.tid(), order: pl.order ?? k, steps: pl.steps ?? [],
        trigger_interaction: pl.trigger_interaction,
      }));

    const patchPageMap = new Map((n.pages ?? []).map(p => [p.name, p]));
    const allPages: Page[] = [
      ...s.pages
        .filter(p => !removedPages.has(p.name))
        .map(p => {
          if (!patchPageMap.has(p.name)) return p;
          const pp = patchPageMap.get(p.name)!;
          return {
            ...p,
            route: pp.route ?? p.route,
            layout: pp.layout ?? p.layout,
            service_ids: resolveSvcIds(pp.service_names ?? []),
            components: pp.components ?? p.components,
            interactions: buildInteractions(pp.interactions ?? p.interactions ?? []),
            pipelines: buildPipelines(pp.pipelines ?? p.pipelines ?? []),
          };
        }),
      ...(n.pages ?? [])
        .filter(p => !s.pages.some(ep => ep.name === p.name))
        .map((p, i) => ({
          id: this.tid(),
          name: p.name,
          route: p.route || '/' + p.name.toLowerCase().replace(/\s+/g, '-'),
          layout: p.layout ?? 'mixed',
          order: s.pages.length + i,
          service_ids: resolveSvcIds(p.service_names ?? []),
          components: p.components ?? [],
          interactions: buildInteractions(p.interactions ?? []),
          pipelines: buildPipelines(p.pipelines ?? []),
        })),
    ];

    this.mutate(cur => ({ ...cur, ...newMeta, data_models: allModels, endpoint_groups: allGroups, services: allServices, pages: allPages }));
  }

  replaceFromAgent(patch: AgentPatch): void {
    this.mutate(cur => ({
      name: patch.set_meta?.name ?? 'Mon Application',
      description: patch.set_meta?.description ?? '',
      required_groups: patch.set_meta?.required_groups ?? [],
      app_type: cur.app_type,
      data_models: [], endpoint_groups: [], services: [], pages: [],
    }));
    this.mergeFromAgent({ ...patch, set_meta: undefined });
  }

  patchSummary(patch: AgentPatch): string {
    const n = this._normalizePatch(patch);
    const parts: string[] = [];
    if (n.set_meta?.name) parts.push(`nom → "${n.set_meta.name}"`);
    if (n.set_meta?.required_groups?.length) parts.push(`groupes requis → ${n.set_meta.required_groups.join(', ')}`);
    if (n.data_models?.length) parts.push(`${n.data_models.length} modèle(s)`);
    if (n.remove_models?.length) parts.push(`−${n.remove_models.length} modèle(s)`);
    if (n.endpoint_groups?.length) {
      const epCount = n.endpoint_groups.reduce((acc, g) => acc + (g.endpoints?.length ?? 0), 0);
      parts.push(`${n.endpoint_groups.length} groupe(s) / ${epCount} endpoint(s)`);
    }
    if (n.remove_endpoint_groups?.length) parts.push(`−${n.remove_endpoint_groups.length} groupe(s)`);
    if (n.services?.length) parts.push(`${n.services.length} service(s)`);
    if (n.remove_services?.length) parts.push(`−${n.remove_services.length} service(s)`);
    if (n.pages?.length) parts.push(`${n.pages.length} page(s)`);
    if (n.remove_pages?.length) parts.push(`−${n.remove_pages.length} page(s)`);
    return parts.join(' · ') || 'patch vide';
  }

  // ── Helpers ───────────────────────────────────────────────────────────────────

  private nextId = -1;
  private tid(): number { return this.nextId--; }

  /**
   * Normalise un patch brut issu de l'IA :
   * - gère les clés alternatives (models/data_models, groups/endpoint_groups…)
   * - normalise les types de champs, opérations, méthodes HTTP, types de relation
   * - filtre les items invalides (sans nom, sans champ requis)
   * - applique les valeurs par défaut manquantes
   */
  private _normalizePatch(raw: AgentPatch): AgentPatch {
    const FIELD_TYPES: Record<string, FieldType> = {
      string: 'string', str: 'string', char: 'string', varchar: 'string',
      url: 'string', email: 'string', slug: 'string',
      text: 'text', longtext: 'text', long_text: 'text',
      int: 'int', integer: 'int',
      decimal: 'decimal', float: 'decimal', double: 'decimal', number: 'decimal',
      bool: 'bool', boolean: 'bool',
      datetime: 'datetime', date: 'datetime', timestamp: 'datetime',
      json: 'json', jsonb: 'json', dict: 'json', object: 'json', array: 'json',
      file: 'file', image: 'file', upload: 'file',
    };
    const OPERATIONS: Record<string, OperationType> = {
      list: 'list', index: 'list', getall: 'list', get_all: 'list',
      create: 'create', post: 'create', add: 'create',
      retrieve: 'retrieve', get: 'retrieve', detail: 'retrieve', read: 'retrieve',
      update: 'update', put: 'update', replace: 'update',
      partial_update: 'partial_update', patch: 'partial_update',
      delete: 'delete', destroy: 'delete', remove: 'delete',
      custom: 'custom',
    };
    const REL_TYPES: Record<string, RelType> = {
      FK: 'FK', fk: 'FK', foreignkey: 'FK', foreign_key: 'FK', manytoone: 'FK',
      M2M: 'M2M', m2m: 'M2M', manytomany: 'M2M', many_to_many: 'M2M',
      O2O: 'O2O', o2o: 'O2O', onetoone: 'O2O', one_to_one: 'O2O',
    };
    const HTTP_METHODS: Record<string, HttpMethod> = {
      GET: 'GET', POST: 'POST', PUT: 'PUT', PATCH: 'PATCH', DELETE: 'DELETE',
    };
    const ON_DELETE_VALS = new Set(['CASCADE', 'SET_NULL', 'PROTECT', 'DO_NOTHING']);

    const arr = <T>(v: unknown): T[] => (Array.isArray(v) ? v as T[] : []);
    const str = (v: unknown, fb = ''): string => (typeof v === 'string' ? v.trim() : fb);

    const r = raw as Record<string, unknown>;
    // Clés alternatives acceptées
    const rawModels  = arr(r['data_models']      ?? r['models']     ?? r['data-models']);
    const rawGroups  = arr(r['endpoint_groups']   ?? r['groups']     ?? r['endpoints']);
    const rawSvcs    = arr(r['services']);
    const rawPages   = arr(r['pages']);
    const rmModels   = arr<string>(r['remove_models']          ?? r['delete_models']);
    const rmGroups   = arr<string>(r['remove_endpoint_groups'] ?? r['delete_groups']);
    const rmSvcs     = arr<string>(r['remove_services']        ?? r['delete_services']);
    const rmPages    = arr<string>(r['remove_pages']           ?? r['delete_pages']);

    // set_meta.required_groups reste en pass-through pour name/description (undefined
    // doit rester undefined pour laisser le ?? de mergeFromAgent/replaceFromAgent
    // retomber sur l'existant) — seul required_groups est assaini si présent.
    const rawGroupNames = raw.set_meta?.required_groups;
    const setMeta = raw.set_meta ? {
      ...raw.set_meta,
      ...(Array.isArray(rawGroupNames) && {
        required_groups: arr<string>(rawGroupNames).map(g => str(g)).filter(Boolean),
      }),
    } : undefined;

    return {
      set_meta: setMeta,
      remove_models: rmModels,
      remove_endpoint_groups: rmGroups,
      remove_services: rmSvcs,
      remove_pages: rmPages,

      data_models: (rawModels as any[])
        .filter(m => m && str(m.name))
        .map(m => ({
          name: str(m.name),
          description: str(m.description),
          order: typeof m.order === 'number' ? m.order : 0,
          fields: arr<ModelField>(m.fields)
            .filter((f: any) => f && str(f.name))
            .map((f: any) => ({
              name: str(f.name),
              type: (FIELD_TYPES[str(f.type).toLowerCase()] ?? 'string') as FieldType,
              required: f.required !== false,
              unique: !!f.unique,
              ...(typeof f.max_length === 'number' && { max_length: f.max_length }),
              ...(f.default !== undefined && { default: String(f.default) }),
              ...(f.help_text && { help_text: str(f.help_text) }),
            })),
          relationships: arr<ModelRelationship>(m.relationships)
            .filter((r: any) => r && str(r.name) && str(r.to_model))
            .map((rel: any) => {
              const rt = str(rel.rel_type).replace(/[\s_-]/g, '').toLowerCase();
              const od = str(rel.on_delete ?? rel.on_delete_action).toUpperCase();
              return {
                name: str(rel.name),
                rel_type: (REL_TYPES[rt] ?? 'FK') as RelType,
                to_model: str(rel.to_model ?? rel.target ?? rel.model),
                related_name: str(rel.related_name),
                on_delete: (ON_DELETE_VALS.has(od) ? od : 'CASCADE') as 'CASCADE' | 'SET_NULL' | 'PROTECT' | 'DO_NOTHING',
              };
            }),
        })),

      endpoint_groups: (rawGroups as any[])
        .filter(g => g && str(g.name))
        .map(g => ({
          name: str(g.name),
          description: str(g.description),
          order: typeof g.order === 'number' ? g.order : 0,
          endpoints: arr<Omit<Endpoint, 'id'>>(g.endpoints)
            .filter((e: any) => e && str(e.method) && str(e.path))
            .map((e: any) => {
              const mth = str(e.method).toUpperCase();
              const op  = str(e.operation ?? '').toLowerCase().replace(/[\s-]/g, '_');
              return {
                method: (HTTP_METHODS[mth] ?? 'GET') as HttpMethod,
                path: str(e.path),
                description: str(e.description),
                order: typeof e.order === 'number' ? e.order : 0,
                operation: (OPERATIONS[op] ?? 'custom') as OperationType,
                linked_model_name: str(e.linked_model_name ?? e.model ?? e.linked_model),
                auth_required: e.auth_required !== false,
                required_roles: arr<string>(e.required_roles),
                request_schema: e.request_schema ?? null,
                response_schema: e.response_schema ?? null,
                query_params: arr(e.query_params),
              };
            }),
        })),

      services: (rawSvcs as any[])
        .filter(sv => sv && str(sv.name))
        .map(sv => ({
          name: str(sv.name),
          order: typeof sv.order === 'number' ? sv.order : 0,
          endpoint_group_names: arr<string>(sv.endpoint_group_names ?? sv.groups ?? sv.endpoint_groups),
        })),

      pages: (rawPages as any[])
        .filter(p => p && str(p.name))
        .map(p => ({
          name: str(p.name),
          route: str(p.route),
          layout: (str(p.layout || 'mixed')) as PageLayout,
          order: typeof p.order === 'number' ? p.order : 0,
          service_names: arr<string>(p.service_names ?? p.services),
          components: arr(p.components),
          interactions: arr<Omit<Interaction, 'id'>>(p.interactions)
            .filter((i: any) => i && str(i.name))
            .map((i: any) => ({
              name: str(i.name),
              type: str(i.type || 'other') as InteractionType,
              description: str(i.description),
              order: typeof i.order === 'number' ? i.order : 0,
            })),
          pipelines: arr<Omit<Pipeline, 'id'>>(p.pipelines)
            .filter((pl: any) => pl && str(pl.name))
            .map((pl: any) => ({
              name: str(pl.name),
              description: str(pl.description),
              trigger_interaction: pl.trigger_interaction ? str(pl.trigger_interaction) : undefined,
              order: typeof pl.order === 'number' ? pl.order : 0,
              steps: arr<PipelineStep>(pl.steps).map((st: any) => ({
                label: str(st.label),
                type: st.type ?? 'trigger',
                ...(st.description && { description: str(st.description) }),
                ...(st.service_name && { service_name: str(st.service_name) }),
                ...(st.service_method && { service_method: str(st.service_method) }),
                ...(st.data_flow && { data_flow: str(st.data_flow) }),
                ...(st.on_error && { on_error: str(st.on_error) }),
              })),
            })),
        })),
    };
  }

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
