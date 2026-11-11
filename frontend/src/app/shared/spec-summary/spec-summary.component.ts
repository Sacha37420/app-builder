import { Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { BuilderStateService } from '../../core/builder-state.service';

interface Entry { label: string; count: number; route: string; query?: Record<string, string>; }

/**
 * Résumé de la spécification sur la page d'accueil (à la place de l'ancien
 * canevas, qui recalculait les liens à sa façon) : ce qu'elle contient, si elle
 * est prête pour le lab, et des entrées vers chaque vue de la vue d'ensemble.
 * Aucun calcul de lien ici : les vues lisent le graphe du serveur.
 */
@Component({
  selector: 'app-spec-summary',
  standalone: true,
  imports: [RouterLink],
  template: `
    <div class="sum">
      <h2 class="sum-title">{{ state.spec().name || 'Sans nom' }}</h2>
      @if (state.spec().description) { <p class="sum-desc">{{ state.spec().description }}</p> }

      @if (state.lab(); as lab) {
        <p class="sum-ready" [class.ok]="lab.ready" role="status">
          @if (lab.ready) { ✓ Prête pour le lab } @else { {{ lab.blockers.length }} point(s) bloquant(s) avant le lab }
        </p>
      } @else if (state.savedId() === null) {
        <p class="sum-ready" role="status">Pas encore enregistrée.</p>
      }

      <ul class="sum-grid">
        @for (e of entries(); track e.label) {
          <li>
            <a class="sum-card" [routerLink]="e.route" [queryParams]="e.query ?? null">
              <span class="sum-n">{{ e.count }}</span>
              <span>{{ e.label }}</span>
            </a>
          </li>
        }
      </ul>

      <h3 class="sum-sub">Voir l'app</h3>
      <div class="sum-views">
        @for (v of views; track v.id) {
          <a class="sum-view" routerLink="/overview" [queryParams]="{ vue: v.id }">{{ v.label }}</a>
        }
      </div>
    </div>
  `,
  styles: `
    :host { display: block; height: 100%; overflow-y: auto; background: var(--bg); color: var(--text); }
    .sum { display: flex; flex-direction: column; gap: var(--space-3); padding: var(--space-5); max-width: 900px; }
    .sum-title { font-size: var(--text-xl); font-weight: 800; overflow-wrap: anywhere; }
    .sum-desc { color: var(--text-mute); font-size: var(--text-sm); }
    .sum-ready { font-size: var(--text-sm); color: var(--warning); font-weight: 600; }
    .sum-ready.ok { color: var(--success); }
    .sum-grid { list-style: none; display: grid; gap: var(--space-2); grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }
    .sum-card {
      display: flex; flex-direction: column; gap: var(--space-1); min-height: 44px; padding: var(--space-3);
      background: var(--card); color: var(--text); text-decoration: none;
      border: 1px solid var(--border); border-radius: var(--radius-md); font-size: var(--text-sm);
      &:hover { background: var(--overlay-hover); }
      &:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    }
    .sum-n { font-size: var(--text-lg); font-weight: 800; color: var(--accent); }
    .sum-sub { font-size: var(--text-sm); font-weight: 700; color: var(--text-mute); text-transform: uppercase; letter-spacing: 0.05em; }
    .sum-views { display: flex; flex-wrap: wrap; gap: var(--space-2); }
    .sum-view {
      display: inline-flex; align-items: center; min-height: 44px; padding: 0 var(--space-3);
      border: 1px solid var(--accent); border-radius: var(--radius-full); color: var(--accent);
      background: var(--accent-tint); font-size: var(--text-sm); font-weight: 600; text-decoration: none;
      &:hover { background: var(--overlay-hover); }
      &:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    }
  `,
})
export class SpecSummaryComponent {
  state = inject(BuilderStateService);

  readonly views = [
    { id: 'overview', label: 'Dans le lab' }, { id: 'architecture', label: 'Architecture' },
    { id: 'data', label: 'Données' }, { id: 'api', label: 'API' }, { id: 'pages', label: 'Pages' },
    { id: 'pipelines', label: 'Flux' }, { id: 'security', label: 'Sécurité' },
    { id: 'lifecycles', label: 'Cycles de vie' }, { id: 'jobs', label: 'Tâches' }, { id: 'roadmap', label: 'Feuille de route' },
  ];

  entries = computed<Entry[]>(() => {
    const s = this.state.spec();
    const endpoints = s.endpoint_groups.reduce((n, g) => n + g.endpoints.length, 0);
    const pipelines = s.pages.reduce((n, p) => n + p.pipelines.length, 0);
    return [
      { label: 'modèles', count: s.data_models.length, route: '/models' },
      { label: "routes d'API", count: endpoints, route: '/endpoints' },
      { label: 'pages', count: s.pages.length, route: '/pages-config' },
      { label: 'pipelines', count: pipelines, route: '/pipelines' },
      { label: 'rôles', count: s.roles?.length ?? 0, route: '/infra', query: { section: 'roles' } },
      { label: 'tâches de fond', count: s.jobs?.length ?? 0, route: '/infra', query: { section: 'jobs' } },
      { label: 'règles métier', count: s.business_rules.length, route: '/infra', query: { section: 'rules' } },
    ];
  });
}
