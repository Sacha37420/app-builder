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

  setInteractionType(pageId: number, interId: number, event: Event): void {
    const type = (event.target as HTMLSelectElement).value as InteractionType;
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
