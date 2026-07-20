import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { JsonPipe } from '@angular/common';
import { BuilderStateService } from '../../core/builder-state.service';
import {
  EndpointGroup, FrontendService, Page,
  HttpMethod, InteractionType, PipelineStepType, EndpointStepType
} from '../../models/app-spec.model';

type EditTarget =
  | { kind: 'meta' }
  | { kind: 'group'; id: number }
  | { kind: 'service'; id: number }
  | { kind: 'page'; id: number }
  | null;

type HoveredEl = { type: string; id: number } | null;

@Component({
  selector: 'app-schema-canvas',
  standalone: true,
  imports: [FormsModule, JsonPipe],
  templateUrl: './schema-canvas.component.html',
  styleUrl: './schema-canvas.component.scss',
})
export class SchemaCanvasComponent {
  state = inject(BuilderStateService);

  // ── Edit ─────────────────────────────────────────────────────────────────────
  editing = signal<EditTarget>(null);

  // ── Expanded sets ─────────────────────────────────────────────────────────────
  expandedModels    = signal<Set<number>>(new Set());
  expandedGroups    = signal<Set<number>>(new Set());
  expandedEndpoints = signal<Set<string>>(new Set());
  expandedEpSteps   = signal<Set<string>>(new Set()); // endpoint steps
  expandedPages     = signal<Set<number>>(new Set());
  expandedPipelines = signal<Set<string>>(new Set());
  expandedSteps     = signal<Set<string>>(new Set());

  // ── Hover ─────────────────────────────────────────────────────────────────────
  hoveredEl = signal<HoveredEl>(null);

  get anyHovered(): boolean { return this.hoveredEl() !== null; }

  // ── Toggle helpers ────────────────────────────────────────────────────────────
  private tog<T>(sig: ReturnType<typeof signal<Set<T>>>, key: T): void {
    sig.update(s => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n; });
  }
  toggleModel(id: number): void    { this.tog(this.expandedModels, id); }
  toggleGroup(id: number): void    { this.tog(this.expandedGroups, id); }
  togglePage(id: number): void     { this.tog(this.expandedPages, id); }
  toggleEndpoint(gId: number, epId: number): void { this.tog(this.expandedEndpoints, `${gId}-${epId}`); }
  isExpandedEp(gId: number, epId: number): boolean { return this.expandedEndpoints().has(`${gId}-${epId}`); }
  toggleEpStep(gId: number, epId: number, i: number): void { this.tog(this.expandedEpSteps, `${gId}-${epId}-${i}`); }
  isExpandedEpStep(gId: number, epId: number, i: number): boolean { return this.expandedEpSteps().has(`${gId}-${epId}-${i}`); }
  togglePipeline(pageId: number, pipeId: number): void { this.tog(this.expandedPipelines, `${pageId}-${pipeId}`); }
  isExpandedPipe(pageId: number, pipeId: number): boolean { return this.expandedPipelines().has(`${pageId}-${pipeId}`); }
  toggleStep(pageId: number, pipeId: number, i: number): void { this.tog(this.expandedSteps, `${pageId}-${pipeId}-${i}`); }
  isExpandedStep(pageId: number, pipeId: number, i: number): boolean { return this.expandedSteps().has(`${pageId}-${pipeId}-${i}`); }

  // ── Edit helpers ──────────────────────────────────────────────────────────────
  editMeta(): void    { this.editing.set({ kind: 'meta' }); }
  editGroup(id: number): void   { this.editing.set({ kind: 'group', id }); }
  editService(id: number): void { this.editing.set({ kind: 'service', id }); }
  editPage(id: number): void    { this.editing.set({ kind: 'page', id }); }
  closeEdit(): void   { this.editing.set(null); }
  isEditing(kind: string, id?: number): boolean {
    const e = this.editing();
    return !!e && e.kind === kind && (id === undefined || (e as any).id === id);
  }

  // ── Hover / connection ────────────────────────────────────────────────────────
  setHovered(type: string, id: number): void { this.hoveredEl.set({ type, id }); }
  clearHovered(): void { this.hoveredEl.set(null); }

  isConnected(type: string, id: number): boolean {
    const h = this.hoveredEl();
    if (!h) return false;
    const spec = this.state.spec();
    if (h.type === 'model' && type === 'group')
      return spec.endpoint_groups.find(g => g.id === id)?.endpoints.some(e => e.linked_model_name === spec.data_models.find(m => m.id === h.id)?.name) ?? false;
    if (h.type === 'group' && type === 'model') {
      const g = spec.endpoint_groups.find(g => g.id === h.id);
      return g?.endpoints.some(e => e.linked_model_name === spec.data_models.find(m => m.id === id)?.name) ?? false;
    }
    if (h.type === 'group' && type === 'service')
      return spec.services.find(s => s.id === id)?.endpoint_group_ids.includes(h.id) ?? false;
    if (h.type === 'service' && type === 'group')
      return spec.services.find(s => s.id === h.id)?.endpoint_group_ids.includes(id) ?? false;
    if (h.type === 'service' && type === 'page')
      return spec.pages.find(p => p.id === id)?.service_ids.includes(h.id) ?? false;
    if (h.type === 'page' && type === 'service')
      return spec.pages.find(p => p.id === h.id)?.service_ids.includes(id) ?? false;
    return false;
  }

  elClass(type: string, id: number): string {
    const h = this.hoveredEl();
    if (!h) return '';
    if (h.type === type && h.id === id) return 'el-active';
    if (this.isConnected(type, id)) return 'el-connected';
    return 'el-dimmed';
  }

  // ── Data helpers ──────────────────────────────────────────────────────────────
  linkedServicesForGroup(gId: number): FrontendService[] {
    return this.state.spec().services.filter(s => s.endpoint_group_ids.includes(gId));
  }
  linkedPagesForService(sId: number): Page[] {
    return this.state.spec().pages.filter(p => p.service_ids.includes(sId));
  }
  groupsForService(sId: number): EndpointGroup[] {
    const svc = this.state.spec().services.find(s => s.id === sId);
    return svc ? this.state.spec().endpoint_groups.filter(g => svc.endpoint_group_ids.includes(g.id!)) : [];
  }
  groupsUsingModel(name: string): EndpointGroup[] {
    return this.state.spec().endpoint_groups.filter(g => g.endpoints.some(e => e.linked_model_name === name));
  }

  // ── Browser column ────────────────────────────────────────────────────────────
  get interactionTypes(): InteractionType[] {
    const types = new Set<InteractionType>();
    for (const p of this.state.spec().pages) for (const i of p.interactions) types.add(i.type as InteractionType);
    return Array.from(types);
  }
  interactionsOfType(type: InteractionType): { name: string; pageName: string }[] {
    const result: { name: string; pageName: string }[] = [];
    for (const p of this.state.spec().pages)
      for (const i of p.interactions) if (i.type === type) result.push({ name: i.name, pageName: p.name });
    return result;
  }

  // ── App name as DB schema ─────────────────────────────────────────────────────
  get dbSchema(): string {
    return this.state.spec().name.toLowerCase()
      .replace(/[éèêëàâäùûüôöîï]/g, c => ({'é':'e','è':'e','ê':'e','ë':'e','à':'a','â':'a','ä':'a','ù':'u','û':'u','ü':'u','ô':'o','ö':'o','î':'i','ï':'i'})[c] ?? c)
      .replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  }

  // ── Noms de tables (mêmes noms que la page /infra) ────────────────────────────
  get tableNames(): string[] {
    return this.state.spec().data_models.map(m => this.toSnake(m.name));
  }

  private toSnake(s: string): string {
    return s.replace(/([A-Z])/g, m => `_${m.toLowerCase()}`).replace(/^_/, '');
  }

  // ── Constants ─────────────────────────────────────────────────────────────────
  readonly methods: HttpMethod[] = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];
  readonly layoutTypes = ['list', 'detail', 'form', 'dashboard', 'mixed'] as const;
  readonly interTypesList: InteractionType[] = ['click', 'form', 'navigation', 'display', 'other'];
  readonly epStepTypes: EndpointStepType[] = ['auth_check', 'validate', 'db_query', 'db_write', 'serialize', 'transform', 'error', 'custom'];
  readonly pipeStepTypes: PipelineStepType[] = ['trigger', 'service_call', 'transform', 'state_update', 'navigate', 'error'];

  // ── Event helpers ─────────────────────────────────────────────────────────────
  val(e: Event): string { return (e.target as HTMLInputElement).value; }
  setMetaName(e: Event): void { this.state.updateMeta(this.val(e), this.state.spec().description); }
  setMetaDesc(e: Event): void { this.state.updateMeta(this.state.spec().name, this.val(e)); }

  removeRequiredGroup(g: string): void { this.state.removeRequiredGroup(g); }
  onRequiredGroupKeydown(e: KeyboardEvent): void {
    if (e.key !== 'Enter' && e.key !== ',') return;
    e.preventDefault();
    const input = e.target as HTMLInputElement;
    this.state.addRequiredGroup(input.value);
    input.value = '';
  }
  setGroupName(id: number, e: Event): void { this.state.updateEndpointGroup(id, { name: this.val(e) }); }
  setGroupDesc(id: number, e: Event): void { this.state.updateEndpointGroup(id, { description: this.val(e) }); }
  setEndpointMethod(gId: number, epId: number, e: Event): void { this.state.updateEndpoint(gId, epId, { method: this.val(e) as HttpMethod }); }
  setEndpointPath(gId: number, epId: number, e: Event): void { this.state.updateEndpoint(gId, epId, { path: this.val(e) }); }
  setEndpointAuth(gId: number, epId: number, e: Event): void { this.state.updateEndpoint(gId, epId, { auth_required: (e.target as HTMLInputElement).checked }); }
  setServiceName(id: number, e: Event): void { this.state.updateService(id, { name: this.val(e) }); }
  setPageName(id: number, e: Event): void  { this.state.updatePage(id, { name: this.val(e) }); }
  setPageRoute(id: number, e: Event): void { this.state.updatePage(id, { route: this.val(e) }); }
  setPageLayout(id: number, e: Event): void { this.state.updatePage(id, { layout: this.val(e) as any }); }
}
