import { afterNextRender, Component, computed, effect, inject, Injector, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BuilderStateService } from '../../core/builder-state.service';
import { urlSelection } from '../../core/url-selection';
import { checked, val } from '../../core/form-utils';
import { BackLinkComponent } from '../../shared/back-link/back-link.component';
import {
  Page, FrontendService, PageComponent, PageComponentType,
  PageLayout, InteractionType,
} from '../../models/app-spec.model';

@Component({
  selector: 'app-pages-page',
  standalone: true,
  imports: [FormsModule, BackLinkComponent],
  templateUrl: './pages-config.component.html',
  styleUrl: './pages-config.component.scss',
})
export class PagesPageComponent {
  state = inject(BuilderStateService);
  private injector = inject(Injector);

  /** La page ouverte, portée par l'adresse (`?page=<id>`, contrat I6). */
  readonly selection = urlSelection('page', 'pages');
  /** Service mis en évidence, porté par l'adresse (`?service=<id>`, contrat I6 v2). */
  readonly serviceSelection = urlSelection('service', 'services');

  readonly layouts: PageLayout[] = ['list', 'detail', 'form', 'dashboard', 'mixed', 'canvas', 'wizard', 'settings'];
  readonly interactionTypes: InteractionType[] = [
    'click', 'form', 'navigation', 'display', 'drag', 'keyboard', 'timer', 'upload', 'realtime_event', 'other',
  ];
  readonly interactionLabels: Record<InteractionType, string> = {
    click: 'clic', form: 'formulaire', navigation: 'navigation', display: 'affichage', other: 'autre',
    drag: 'glisser', keyboard: 'clavier', timer: 'minuterie', upload: 'envoi de fichier',
    realtime_event: 'événement temps réel',
  };

  readonly layoutLabels: Record<PageLayout, string> = {
    list: 'Liste / tableau', detail: 'Vue détail',
    form: 'Formulaire', dashboard: 'Dashboard', mixed: 'Mixte',
    canvas: 'Plein écran (canevas)', wizard: 'Assistant en étapes', settings: 'Réglages',
  };

  /** Types de composants (I1 `components[].type`), libellés courts. */
  readonly compTypeLabels: Record<PageComponentType, string> = {
    table: 'Tableau', form: 'Formulaire', chart: 'Graphique', card: 'Carte (fiche)', custom: 'Autre',
    map: 'Carte géographique', viewer_3d: 'Visionneuse 3D', game_canvas: 'Canevas de jeu',
    timeseries_chart: 'Série temporelle', calendar: 'Calendrier', video_player: 'Lecteur vidéo',
    pdf_viewer: 'Lecteur PDF', markdown: 'Texte Markdown', qr_code: 'Code QR', graph: 'Graphe',
    wizard: 'Assistant', chat: 'Conversation', job_progress: 'Suivi de tâche', share_manager: 'Partages',
    secret_form: 'Saisie de secret', file_browser: 'Fichiers', kanban: 'Tableau kanban',
  };
  readonly compTypes = Object.keys(this.compTypeLabels) as PageComponentType[];

  private readonly page = computed<Page | undefined>(() => {
    const id = this.selection.id();
    return id !== null ? this.state.spec().pages.find(p => p.id === id) : undefined;
  });
  get selectedPage(): Page | undefined { return this.page(); }

  /** Rôles proposés à la saisie : rôles de la spec (I1 `roles`) et groupes requis. */
  readonly roleSuggestions = computed(() => {
    const out = (this.state.spec().roles ?? []).map(r => r.name);
    for (const g of this.state.spec().required_groups) if (!out.includes(g)) out.push(g);
    return out;
  });

  /** Erreurs de saisie JSON de `config`, par « pageId:index » de composant. */
  readonly configErrors = signal<Record<string, string>>({});

  constructor() {
    effect(() => {
      const id = this.serviceSelection.id();
      if (id === null) return;
      afterNextRender(() => {
        const el = document.getElementById(`service-${id}`);
        if (!el) return;
        const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        el.scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' });
        el.querySelector<HTMLInputElement>('input')?.focus({ preventScroll: true });
      }, { injector: this.injector });
    });
    effect(() => {
      const id = this.selection.id();
      if (id === null) return;
      afterNextRender(() => {
        const el = document.getElementById('page-detail');
        if (!el) return;
        const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        el.scrollIntoView({ block: 'start', behavior: reduced ? 'auto' : 'smooth' });
        document.getElementById(`page-item-${id}`)?.scrollIntoView({ block: 'nearest' });
      }, { injector: this.injector });
    });
  }

  isServiceSelected(id: number | undefined): boolean {
    return id !== undefined && this.serviceSelection.id() === id;
  }

  /** L'adresse désigne un service que la spec ne contient pas. */
  serviceMissing(): boolean {
    const id = this.serviceSelection.id();
    return id !== null && !this.state.spec().services.some(s => s.id === id);
  }

  /** L'adresse désigne une page que la spec ne contient pas. */
  missing(): boolean {
    return this.selection.id() !== null && !this.page();
  }

  selectPage(id: number): void { this.selection.set(id); }

  val = val;
  checked = checked;

  // ── Service ───────────────────────────────────────────────────────────────────

  setServiceName(id: number, e: Event): void { this.state.updateService(id, { name: val(e) }); }

  getGroupName(id: number): string { return this.state.getGroupName(id); }

  getLinkedGroupIds(svc: FrontendService): number[] {
    return svc.endpoint_group_ids;
  }

  // ── Page ──────────────────────────────────────────────────────────────────────

  setPageName(id: number, e: Event): void { this.state.updatePage(id, { name: val(e) }); }
  setPageRoute(id: number, e: Event): void { this.state.updatePage(id, { route: val(e) }); }
  setPageLayout(id: number, e: Event): void { this.state.updatePage(id, { layout: val(e) as PageLayout }); }

  // ── Accès à la page (I1 `public`, `public_reason`, `required_roles`) ─────────

  setPagePublic(id: number, e: Event): void {
    const pub = checked(e);
    this.state.updatePage(id, pub ? { public: true } : { public: false, public_reason: '' });
  }
  setPagePublicReason(id: number, e: Event): void { this.state.updatePage(id, { public_reason: val(e) }); }

  addPageRole(page: Page, raw: string): void {
    const r = raw.trim();
    const roles = page.required_roles ?? [];
    if (!r || roles.includes(r)) return;
    this.state.updatePage(page.id!, { required_roles: [...roles, r] });
  }
  removePageRole(page: Page, role: string): void {
    this.state.updatePage(page.id!, { required_roles: (page.required_roles ?? []).filter(r => r !== role) });
  }
  onPageRoleKeydown(page: Page, e: KeyboardEvent): void {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      const input = e.target as HTMLInputElement;
      this.addPageRole(page, input.value);
      input.value = '';
    }
  }
  onPageRoleChange(page: Page, e: Event): void {
    // Choix dans la liste proposée (datalist) : ajouté sans attendre « Entrée ».
    const input = e.target as HTMLInputElement;
    if (this.roleSuggestions().includes(input.value.trim())) {
      this.addPageRole(page, input.value);
      input.value = '';
    }
  }

  // ── Composants ────────────────────────────────────────────────────────────────

  setCompType(pageId: number, idx: number, e: Event): void {
    this.state.updateComponent(pageId, idx, { type: val(e) as PageComponent['type'] });
  }
  setCompLabel(pageId: number, idx: number, e: Event): void {
    this.state.updateComponent(pageId, idx, { label: val(e) });
  }
  setCompModel(pageId: number, idx: number, e: Event): void {
    this.state.updateComponent(pageId, idx, { linked_model: val(e) });
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

  /** Réglages libres du composant (`config`), en JSON lisible. */
  configJson(comp: PageComponent): string {
    return comp.config && Object.keys(comp.config).length ? JSON.stringify(comp.config, null, 2) : '';
  }

  configError(pageId: number, idx: number): string {
    return this.configErrors()[`${pageId}:${idx}`] ?? '';
  }

  /** N'écrit que si le JSON est un objet valide ; sinon un message, et rien n'est envoyé. */
  setCompConfig(pageId: number, idx: number, e: Event): void {
    const key = `${pageId}:${idx}`;
    const raw = val(e).trim();
    let config: Record<string, unknown> | undefined;
    if (raw === '') {
      config = undefined;
    } else {
      let parsed: unknown;
      try { parsed = JSON.parse(raw); } catch {
        this.configErrors.update(m => ({ ...m, [key]: 'JSON illisible : rien n\'a été enregistré.' }));
        return;
      }
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        this.configErrors.update(m => ({ ...m, [key]: 'Il faut un objet JSON ({ … }) : rien n\'a été enregistré.' }));
        return;
      }
      config = parsed as Record<string, unknown>;
    }
    this.configErrors.update(m => { const { [key]: _, ...rest } = m; return rest; });
    this.state.updateComponent(pageId, idx, { config });
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
    this.state.updateInteraction(pageId, interId, { name: val(e) });
  }
  setInteractionType(pageId: number, interId: number, e: Event): void {
    this.state.updateInteraction(pageId, interId, { type: val(e) as InteractionType });
  }
  setInteractionDesc(pageId: number, interId: number, e: Event): void {
    this.state.updateInteraction(pageId, interId, { description: val(e) });
  }

  // ── Helpers ───────────────────────────────────────────────────────────────────

  getLinkedServices(page: Page): FrontendService[] {
    return this.state.spec().services.filter(s => page.service_ids.includes(s.id!));
  }
}
