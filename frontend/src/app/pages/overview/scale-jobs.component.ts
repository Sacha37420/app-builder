import { Component, computed, inject } from '@angular/core';
import { BuilderStateService } from '../../core/builder-state.service';
import { AppJob, GraphNode } from '../../models/app-spec.model';
import { OverviewStore } from './overview.store';

const KIND: Record<string, string> = { async: 'à la demande', scheduled: 'planifiée', command: 'commande' };

function trigger(t: string | undefined): string {
  if (!t) return 'déclencheur non décrit';
  if (t === 'manual') return 'à la main';
  const every = /^every:(.+)$/.exec(t);
  if (every) return `toutes les ${every[1]}`;
  return t;
}

/**
 * Vue « Tâches de fond » (notation `timeline`) : une ligne par tâche (I1 `jobs`),
 * en couloir déclencheur → tâche → entrée et suivi ; puis les services du lab et
 * API externes appelés depuis une tâche. Lue sur la spec en cours d'édition.
 */
@Component({
  selector: 'app-ov-jobs',
  standalone: true,
  styleUrl: './scale-jobs.component.scss',
  template: `
    @if (jobs().length === 0) {
      <p class="ov-card ov-empty">Aucune tâche de fond décrite. Décrivez-les dans « Lab &amp; infra » → Tâches.</p>
    } @else {
      <ol class="ov-lanes">
        @for (j of jobs(); track j.name) {
          @let n = node(j);
          <li class="ov-lane">
            <span class="ov-lane-step">
              <span class="ov-insp-sub">Déclencheur</span>
              <span class="ov-mono">{{ trig(j.trigger) }}</span>
            </span>
            <span class="ov-lane-arrow" aria-hidden="true">→</span>
            <button type="button" class="ov-node k-purple" [class.is-focus]="n ? store.isFocus(n.id) : false"
                    [class.is-ghost]="store.isGhost(n)" (click)="store.select(n)" [disabled]="!n">
              <span class="ov-kind">{{ kindLabel(j.kind) }}</span> {{ j.name }}
              @if (j.heavy) { <span class="ov-tag-warn">lourde</span> }
            </button>
            <span class="ov-lane-arrow" aria-hidden="true">→</span>
            <span class="ov-lane-step">
              <span class="ov-insp-sub">Travaille sur</span>
              <span>{{ j.input_model || '—' }}</span>
              @if (j.tracked_by) { <span class="ov-faint">suivi par {{ j.tracked_by }}</span> }
              @if (j.concurrency) { <span class="ov-faint">{{ j.concurrency }}</span> }
            </span>
            @if (j.description) { <p class="ov-detail ov-lane-desc">{{ j.description }}</p> }
          </li>
        }
      </ol>
    }
    @if (fromJobs().length) {
      <h2 class="ov-h2">Appelé depuis une tâche</h2>
      <ul class="ov-notes">
        @for (a of fromJobs(); track a) { <li>{{ a }}</li> }
      </ul>
    }
  `,
})
export class ScaleJobsComponent {
  store = inject(OverviewStore);
  private state = inject(BuilderStateService);

  jobs = computed<AppJob[]>(() => this.state.spec().jobs ?? []);
  fromJobs = computed(() => (this.state.spec().external_apis ?? [])
    .filter(a => a.called_from === 'job').map(a => `${a.name}${a.purpose ? ' — ' + a.purpose : ''}`));

  node(j: AppJob): GraphNode | null { return this.store.byLabel('job', j.name); }
  trig(t: string | undefined): string { return trigger(t); }
  kindLabel(k: string): string { return KIND[k] ?? k; }
}
