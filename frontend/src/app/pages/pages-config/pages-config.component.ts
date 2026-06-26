import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BuilderStateService } from '../../core/builder-state.service';
import {
  Page, FrontendService, PageComponent, Interaction,
  PageLayout, InteractionType,
} from '../../models/app-spec.model';
import { NavbarComponent } from '../../shared/navbar/navbar.component';

@Component({
  selector: 'app-pages-page',
  standalone: true,
  imports: [FormsModule, NavbarComponent],
  templateUrl: './pages-config.component.html',
  styleUrl: './pages-config.component.scss',
})
export class PagesPageComponent {
  state = inject(BuilderStateService);

  selectedPageId = signal<number | null>(null);

  readonly layouts: PageLayout[] = ['list', 'detail', 'form', 'dashboard', 'mixed'];
  readonly compTypes = ['table', 'form', 'chart', 'card', 'custom'] as const;
  readonly interactionTypes: InteractionType[] = ['click', 'form', 'navigation', 'display', 'other'];

  readonly layoutLabels: Record<PageLayout, string> = {
    list: 'Liste / tableau', detail: 'Vue détail',
    form: 'Formulaire', dashboard: 'Dashboard', mixed: 'Mixte',
  };

  get selectedPage(): Page | undefined {
    const id = this.selectedPageId();
    return id !== null ? this.state.spec().pages.find(p => p.id === id) : undefined;
  }

  selectPage(id: number): void { this.selectedPageId.set(id); }

  val(e: Event): string { return (e.target as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value; }
  checked(e: Event): boolean { return (e.target as HTMLInputElement).checked; }

  // ── Service ───────────────────────────────────────────────────────────────────

  setServiceName(id: number, e: Event): void { this.state.updateService(id, { name: this.val(e) }); }

  getGroupName(id: number): string { return this.state.getGroupName(id); }

  getLinkedGroupIds(svc: FrontendService): number[] {
    return svc.endpoint_group_ids;
  }

  // ── Page ──────────────────────────────────────────────────────────────────────

  setPageName(id: number, e: Event): void { this.state.updatePage(id, { name: this.val(e) }); }
  setPageRoute(id: number, e: Event): void { this.state.updatePage(id, { route: this.val(e) }); }
  setPageLayout(id: number, e: Event): void { this.state.updatePage(id, { layout: this.val(e) as PageLayout }); }

  // ── Composants ────────────────────────────────────────────────────────────────

  setCompType(pageId: number, idx: number, e: Event): void {
    this.state.updateComponent(pageId, idx, { type: this.val(e) as PageComponent['type'] });
  }
  setCompLabel(pageId: number, idx: number, e: Event): void {
    this.state.updateComponent(pageId, idx, { label: this.val(e) });
  }
  setCompModel(pageId: number, idx: number, e: Event): void {
    this.state.updateComponent(pageId, idx, { linked_model: this.val(e) });
  }
  setCompFields(pageId: number, comp: PageComponent, idx: number, raw: string): void {
    const fields = raw.split(',').map(f => f.trim()).filter(Boolean);
    this.state.updateComponent(pageId, idx, { fields });
  }

  addCompField(pageId: number, comp: PageComponent, idx: number, field: string): void {
    const f = field.trim();
    if (!f || (comp.fields ?? []).includes(f)) return;
    this.state.updateComponent(pageId, idx, { fields: [...(comp.fields ?? []), f] });
  }

  removeCompField(pageId: number, comp: PageComponent, compIdx: number, fieldIdx: number): void {
    const fields = (comp.fields ?? []).filter((_, i) => i !== fieldIdx);
    this.state.updateComponent(pageId, compIdx, { fields });
  }

  getModelFields(modelName: string): string[] {
    const m = this.state.spec().data_models.find(dm => dm.name === modelName);
    if (!m) return [];
    return [
      ...m.fields.map(f => f.name),
      ...m.relationships.map(r => r.name),
    ];
  }

  // ── Interactions ──────────────────────────────────────────────────────────────

  setInteractionName(pageId: number, interId: number, e: Event): void {
    this.state.updateInteraction(pageId, interId, { name: this.val(e) });
  }
  setInteractionType(pageId: number, interId: number, e: Event): void {
    this.state.updateInteraction(pageId, interId, { type: this.val(e) as InteractionType });
  }
  setInteractionDesc(pageId: number, interId: number, e: Event): void {
    this.state.updateInteraction(pageId, interId, { description: this.val(e) });
  }

  // ── Helpers ───────────────────────────────────────────────────────────────────

  getLinkedServices(page: Page): FrontendService[] {
    return this.state.spec().services.filter(s => page.service_ids.includes(s.id!));
  }
}
