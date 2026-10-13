import { Injectable, effect, signal, inject } from '@angular/core';
import { EMPTY, Subject, of, throwError } from 'rxjs';
import { debounceTime, filter, finalize, map, switchMap, tap, catchError } from 'rxjs/operators';
import { Observable } from 'rxjs';
import {
  AppSpec, AppType, DataModel, ModelField, ModelRelationship,
  EndpointGroup, Endpoint, FrontendService, Page,
  Interaction, Pipeline, PipelineStep, PageComponent,
  AgentPatch, PersistedChatMessage, PatchApplication, PatchMode,
  BusinessRule, LabView,
} from '../models/app-spec.model';
import { BuilderApiService } from './builder-api.service';

export type SaveStatus = 'idle' | 'pending' | 'saving' | 'saved' | 'error';

const EMPTY_SPEC: AppSpec = {
  name: 'Mon Application',
  project_name: '',
  description: '',
  app_type: 'django-angular',
  required_groups: [],
  business_rules: [],
  uses_email: false,
  data_models: [],
  endpoint_groups: [],
  services: [],
  pages: [],
};

/** Une spec ancienne (ou rendue par un vieux serveur) peut ne pas porter les clés du lot 4. */
function normalize(spec: AppSpec): AppSpec {
  return {
    ...spec,
    project_name: spec.project_name ?? '',
    required_groups: spec.required_groups ?? [],
    business_rules: spec.business_rules ?? [],
    uses_email: spec.uses_email ?? false,
  };
}

/** Première phrase trouvée dans le corps d'une erreur DRF (`{"champ": ["message"]}`, `{"detail": "…"}`). */
function firstMessage(body: unknown): string {
  if (typeof body === 'string') return body.trim();
  if (Array.isArray(body)) {
    for (const item of body) {
      const found = firstMessage(item);
      if (found) return found;
    }
    return '';
  }
  if (body && typeof body === 'object') {
    for (const value of Object.values(body)) {
      const found = firstMessage(value);
      if (found) return found;
    }
  }
  return '';
}

const OPEN_SPEC_KEY = 'app-builder.spec';

/** Spec à ouvrir au démarrage : `?spec=<id>` de l'adresse, sinon celle de l'onglet avant rechargement. */
function openSpecId(): number | null {
  let raw: string | null = null;
  try {
    raw = new URLSearchParams(window.location.search).get('spec') ?? sessionStorage.getItem(OPEN_SPEC_KEY);
  } catch { /* stockage indisponible */ }
  return raw && /^[0-9]{1,9}$/.test(raw) ? Number(raw) : null;
}

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
  /** La spec enregistrée vue du lab (GET …/lab/) ; `null` tant que rien n'est enregistré. */
  readonly lab = signal<LabView | null>(null);
  /** Message du serveur quand un enregistrement est refusé (400), sinon ''. */
  readonly saveErrorDetail = signal('');

  private debounceTrigger = new Subject<void>();
  private patching = false;

  constructor() {
    // La spec ouverte survit à un rechargement et s'ouvre par lien direct (`?spec=<id>`,
    // posé par lab-admin) : avant, toute arrivée par l'adresse retombait sur une app vide.
    effect(() => {
      const id = this.savedId();
      try {
        if (id === null) sessionStorage.removeItem(OPEN_SPEC_KEY);
        else sessionStorage.setItem(OPEN_SPEC_KEY, String(id));
      } catch { /* stockage indisponible : on perd seulement le confort */ }
    });
    const wanted = openSpecId();
    if (wanted !== null) {
      // 404 (spec supprimée ou d'autrui) : on reste sur une app vide, sans message.
      this.api.getApp(wanted).pipe(catchError(() => EMPTY)).subscribe(spec => {
        if (this.savedId() === null && !this.isDirty()) this.loadSpec(spec);
      });
    }

    // Autosave : 3 s après la dernière modification, si un ID existe déjà
    this.debounceTrigger.pipe(
      debounceTime(3000),
      filter(() => this.savedId() !== null && !this.patching),
      switchMap(() => {
        this.saveStatus.set('saving');
        return this.api.updateApp(this.savedId()!, this.spec()).pipe(
          tap(saved => {
            this.savedId.set(saved.id!);
            this.isDirty.set(false);
            this.saveStatus.set('saved');
            this.saveErrorDetail.set('');
            this.refreshLab();
          }),
          catchError(err => {
            this.saveStatus.set('error');
            this.noteSaveError(err);
            // EMPTY et non une erreur : une erreur remontée ici terminait le flux,
            // et plus aucun autosave ne partait après un premier refus du serveur.
            return EMPTY;
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
        this.saveErrorDetail.set('');
        this.refreshLab();
      }),
      catchError(err => {
        this.saveStatus.set('error');
        this.noteSaveError(err);
        return throwError(() => err);
      }),
    );
  }

  private noteSaveError(err: unknown): void {
    const e = err as { status?: number; error?: unknown } | null;
    this.saveErrorDetail.set(e?.status === 400 ? firstMessage(e.error) : '');
  }

  /** Relit l'état « lab » de la spec enregistrée. Sans identifiant : rien à lire. */
  refreshLab(): void {
    const id = this.savedId();
    if (id === null) { this.lab.set(null); return; }
    this.api.getLab(id).subscribe({
      // Une réponse arrivée après un changement de spec ne doit pas s'afficher.
      next: view => { if (this.savedId() === id) this.lab.set(view); },
      error: () => { if (this.savedId() === id) this.lab.set(null); },
    });
  }

  loadSpec(spec: AppSpec): void {
    this.spec.set(normalize(spec));
    this.savedId.set(spec.id ?? null);
    this.isDirty.set(false);
    this.saveStatus.set('saved');
    this.saveErrorDetail.set('');
    this.chatHistory.set(spec.chat_history ?? []);
    this.specSessionId.update(v => v + 1);
    this.lab.set(null);
    this.refreshLab();
  }

  resetSpec(): void {
    this.spec.set({ ...EMPTY_SPEC });
    this.savedId.set(null);
    this.isDirty.set(false);
    this.saveStatus.set('idle');
    this.saveErrorDetail.set('');
    this.lab.set(null);
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

  /** L'appelant contrôle la forme (`projectNameError`) : le serveur refuse un nom mal formé. */
  updateProjectName(project_name: string): void {
    this.mutate(s => ({ ...s, project_name }));
  }

  setUsesEmail(uses_email: boolean): void {
    this.mutate(s => ({ ...s, uses_email }));
  }

  addBusinessRule(): void {
    const rule: BusinessRule = { title: 'Nouvelle règle', description: '' };
    this.mutate(s => ({ ...s, business_rules: [...s.business_rules, rule] }));
  }

  updateBusinessRule(idx: number, patch: Partial<BusinessRule>): void {
    this.mutate(s => ({
      ...s,
      business_rules: s.business_rules.map((r, i) => i === idx ? { ...r, ...patch } : r),
    }));
  }

  removeBusinessRule(idx: number): void {
    this.mutate(s => ({ ...s, business_rules: s.business_rules.filter((_, i) => i !== idx) }));
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

  /** Passe un ancien champ `file` en référence au service storage (`storage_file`). */
  convertFileField(modelId: number, idx: number): void {
    const field = this.spec().data_models.find(m => m.id === modelId)?.fields[idx];
    if (field?.type !== 'file') return;
    this.updateField(modelId, idx, { type: 'storage_file' });
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
      auth_required: true, public_reason: '', required_roles: [],
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
    // Une route qui redevient authentifiée perd sa justification de route publique,
    // d'où qu'on la recoche (page API ou canvas).
    if (patch.auth_required === true) patch = { ...patch, public_reason: '' };
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
  // Le patch est fusionné par le serveur (POST /api/apps/<id>/patch/) : une seule
  // implémentation, et un instantané qui permet d'annuler. Ici on se contente
  // d'envoyer une spec à jour, puis d'adopter celle que le serveur rend.

  applyAgentPatch(patch: AgentPatch, mode: PatchMode): Observable<PatchApplication> {
    return this.withServerSpec(id => this.api.applyPatch(id, patch, mode));
  }

  undoAgentPatch(applicationId: number): Observable<PatchApplication> {
    return this.withServerSpec(id => this.api.undoPatch(id, applicationId));
  }

  private withServerSpec(
    call: (id: number) => Observable<{ spec: AppSpec; application: PatchApplication }>,
  ): Observable<PatchApplication> {
    // Tant que l'opération dure, l'autosave est suspendu : un PUT de l'ancienne
    // spec arrivant après le patch l'effacerait.
    this.patching = true;
    const flushed: Observable<unknown> =
      this.savedId() === null || this.isDirty() ? this.saveNow() : of(null);
    return flushed.pipe(
      switchMap(() => call(this.savedId()!)),
      tap(res => {
        this.spec.set(normalize(res.spec));
        this.isDirty.set(false);
        this.saveStatus.set('saved');
        this.saveErrorDetail.set('');
        this.refreshLab();
      }),
      map(res => res.application),
      finalize(() => { this.patching = false; }),
    );
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
