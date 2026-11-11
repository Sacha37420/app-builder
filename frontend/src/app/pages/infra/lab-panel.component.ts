import { Component, computed, effect, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { BuilderStateService } from '../../core/builder-state.service';
import { AppType, CONSTRUCTIBLE_APP_TYPES, projectNameError } from '../../models/app-spec.model';

const APP_TYPE_LABELS: Record<AppType, string> = {
  'django-angular': 'Django + Angular',
  'django':         'Django seul (API)',
  'angular':        'Angular seul',
  'spring-angular': 'Spring + Angular',
  'spring':         'Spring seul',
};

/**
 * Le projet vu du lab : sa fiche (ce que le moteur a besoin de savoir pour le
 * créer), son état « prêt ou non » et son empreinte une fois créé. Les deux
 * derniers blocs viennent du serveur (`state.lab()`), jamais d'un calcul local.
 */
@Component({
  selector: 'app-lab-panel',
  standalone: true,
  imports: [],
  templateUrl: './lab-panel.component.html',
  styleUrl: './lab-panel.component.scss',
})
export class LabPanelComponent {
  state = inject(BuilderStateService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);

  readonly constructibleTypes = CONSTRUCTIBLE_APP_TYPES;

  /** Saisie en cours du nom de projet quand elle est mal formée (rien n'est alors envoyé). */
  projectNameDraft = signal<string | null>(null);
  projectNameProblem = computed(() => {
    const draft = this.projectNameDraft();
    return draft === null ? null : projectNameError(draft);
  });

  /** Ancien type (Spring…) porté par la spec : affiché, mais plus sélectionnable. */
  legacyType = computed<AppType | null>(() => {
    const t = this.state.spec().app_type;
    return this.constructibleTypes.includes(t) ? null : t;
  });

  constructor() {
    // Changement de spec (chargement, nouvelle spec) : les saisies locales n'ont plus de sens.
    effect(() => {
      this.state.specSessionId();
      this.projectNameDraft.set(null);
    });
  }

  typeLabel(t: string): string { return APP_TYPE_LABELS[t as AppType] ?? t; }

  private val(e: Event): string {
    return (e.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value;
  }

  setTitle(e: Event): void { this.state.updateMeta(this.val(e), this.state.spec().description); }
  setDescription(e: Event): void { this.state.updateMeta(this.state.spec().name, this.val(e)); }

  /** N'enregistre qu'un nom vide ou bien formé ; sinon garde la saisie et dit pourquoi. */
  setProjectName(e: Event): void {
    const name = this.val(e).trim();
    if (name === '' || projectNameError(name) === null) {
      this.projectNameDraft.set(null);
      if (name !== this.state.spec().project_name) this.state.updateProjectName(name);
    } else {
      this.projectNameDraft.set(name);
    }
  }

  setAppType(e: Event): void { this.state.updateAppType(this.val(e) as AppType); }

  setUsesEmail(e: Event): void { this.state.setUsesEmail((e.target as HTMLInputElement).checked); }

  // ── Groupes requis ──────────────────────────────────────────────────────────

  addGroup(input: HTMLInputElement): void {
    this.state.addRequiredGroup(input.value);
    input.value = '';
  }

  onGroupKeydown(e: KeyboardEvent, input: HTMLInputElement): void {
    if (e.key !== 'Enter' && e.key !== ',') return;
    e.preventDefault();
    this.addGroup(input);
  }

  // ── Règles métier : éditées dans la section « rules » de la page ─────────────

  openSection(section: string): void {
    this.router.navigate([], {
      relativeTo: this.route, queryParams: { section }, queryParamsHandling: 'merge', replaceUrl: true,
    });
  }
}
