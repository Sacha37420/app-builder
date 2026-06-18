import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BuilderStateService } from '../../core/builder-state.service';
import { EndpointGroup, FrontendService, Page, HttpMethod, InteractionType } from '../../models/app-spec.model';

type EditTarget =
  | { kind: 'meta' }
  | { kind: 'group'; id: number }
  | { kind: 'service'; id: number }
  | { kind: 'page'; id: number }
  | null;

@Component({
  selector: 'app-schema-canvas',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './schema-canvas.component.html',
  styleUrl: './schema-canvas.component.scss',
})
export class SchemaCanvasComponent {
  state = inject(BuilderStateService);

  editing = signal<EditTarget>(null);
  expandedGroups = signal<Set<number>>(new Set());
  expandedPages = signal<Set<number>>(new Set());

  // ── Edition inline ──────────────────────────────────────────────────────────

  editMeta(): void { this.editing.set({ kind: 'meta' }); }
  editGroup(id: number): void { this.editing.set({ kind: 'group', id }); }
  editService(id: number): void { this.editing.set({ kind: 'service', id }); }
  editPage(id: number): void { this.editing.set({ kind: 'page', id }); }
  closeEdit(): void { this.editing.set(null); }

  isEditing(kind: string, id?: number): boolean {
    const e = this.editing();
    if (!e) return false;
    if (e.kind !== kind) return false;
    if (id !== undefined && (e as { kind: string; id: number }).id !== id) return false;
    return true;
  }

  // ── Accordéon ───────────────────────────────────────────────────────────────

  toggleGroup(id: number): void {
    this.expandedGroups.update(s => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  }

  togglePage(id: number): void {
    this.expandedPages.update(s => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  }

  // ── Méthodes HTTP ────────────────────────────────────────────────────────────

  readonly methods: HttpMethod[] = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];
  readonly interactionTypes: InteractionType[] = ['click', 'form', 'navigation', 'display', 'other'];

  // ── Helpers event → state (évite les object literals dans les templates) ────

  val(e: Event): string { return (e.target as HTMLInputElement).value; }

  setMetaName(e: Event): void       { this.state.updateMeta(this.val(e), this.state.spec().description); }
  setMetaDesc(e: Event): void       { this.state.updateMeta(this.state.spec().name, this.val(e)); }

  setGroupName(id: number, e: Event): void { this.state.updateEndpointGroup(id, { name: this.val(e) }); }
  setGroupDesc(id: number, e: Event): void { this.state.updateEndpointGroup(id, { description: this.val(e) }); }

  setEndpointMethod(gId: number, epId: number, e: Event): void {
    this.state.updateEndpoint(gId, epId, { method: this.val(e) as HttpMethod });
  }
  setEndpointPath(gId: number, epId: number, e: Event): void {
    this.state.updateEndpoint(gId, epId, { path: this.val(e) });
  }

  setServiceName(id: number, e: Event): void { this.state.updateService(id, { name: this.val(e) }); }

  setPageName(id: number, e: Event): void  { this.state.updatePage(id, { name: this.val(e) }); }
  setPageRoute(id: number, e: Event): void { this.state.updatePage(id, { route: this.val(e) }); }

  setPipelineName(pId: number, ppId: number, e: Event): void {
    this.state.updatePipeline(pId, ppId, { name: this.val(e) });
  }
  setPipelineSteps(pId: number, ppId: number, e: Event): void {
    this.state.updatePipeline(pId, ppId, { steps: this.textToSteps(this.val(e)) });
  }

  setInteractionName(pId: number, iId: number, e: Event): void {
    this.state.updateInteraction(pId, iId, { name: this.val(e) });
  }
  setInteractionType(pageId: number, interId: number, event: Event): void {
    const type = this.val(event) as InteractionType;
    this.state.updateInteraction(pageId, interId, { type });
  }

  methodClass(method: HttpMethod): string {
    return `method-${method.toLowerCase()}`;
  }

  // ── Liaison service/groupe ───────────────────────────────────────────────────

  toggleGroupLink(svcId: number, groupId: number): void {
    const svc = this.state.spec().services.find(s => s.id === svcId);
    if (!svc) return;
    const ids = svc.endpoint_group_ids.includes(groupId)
      ? svc.endpoint_group_ids.filter(id => id !== groupId)
      : [...svc.endpoint_group_ids, groupId];
    this.state.updateService(svcId, { endpoint_group_ids: ids });
  }

  toggleServiceLink(pageId: number, svcId: number): void {
    const page = this.state.spec().pages.find(p => p.id === pageId);
    if (!page) return;
    const ids = page.service_ids.includes(svcId)
      ? page.service_ids.filter(id => id !== svcId)
      : [...page.service_ids, svcId];
    this.state.updatePage(pageId, { service_ids: ids });
  }

  // ── Steps pipeline ──────────────────────────────────────────────────────────

  stepsToText(steps: string[]): string { return steps.join('\n'); }

  textToSteps(text: string): string[] {
    return text.split('\n').map(s => s.trim()).filter(s => s.length > 0);
  }
}
