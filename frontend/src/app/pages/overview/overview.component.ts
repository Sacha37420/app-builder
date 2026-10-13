import {
  afterNextRender, Component, computed, effect, inject, Injector, OnDestroy, signal, untracked, ViewEncapsulation,
} from '@angular/core';
import { DatePipe } from '@angular/common';
import { Subscription } from 'rxjs';
import { BuilderApiService } from '../../core/builder-api.service';
import { BuilderStateService } from '../../core/builder-state.service';
import { OverviewStore } from './overview.store';
import { ScaleLabComponent } from './scale-lab.component';
import { ScaleArchitectureComponent } from './scale-architecture.component';
import { ScaleDataComponent } from './scale-data.component';
import { ScalePipelinesComponent } from './scale-pipelines.component';
import { ScaleRoadmapComponent } from './scale-roadmap.component';

/**
 * Page « Vue d'ensemble » (route `/overview`) : la spec enregistrée vue à cinq
 * échelles, du lab à l'étape de pipeline. Rien n'est calculé ici : la page
 * affiche la réponse de `GET /api/apps/<id>/graph/`. L'échelle et le nœud en
 * focus vivent dans l'URL (voir `OverviewStore`).
 *
 * Styles : cette feuille porte le vocabulaire commun des échelles (cartes,
 * étiquettes, liens), d'où `ViewEncapsulation.None` — tout y est rangé sous le
 * sélecteur `app-overview-page` et préfixé `ov-`.
 */
@Component({
  selector: 'app-overview-page',
  standalone: true,
  imports: [
    DatePipe, ScaleLabComponent, ScaleArchitectureComponent, ScaleDataComponent,
    ScalePipelinesComponent, ScaleRoadmapComponent,
  ],
  providers: [OverviewStore],
  templateUrl: './overview.component.html',
  styleUrl: './overview.component.scss',
  encapsulation: ViewEncapsulation.None,
})
export class OverviewPageComponent implements OnDestroy {
  state = inject(BuilderStateService);
  store = inject(OverviewStore);
  private api = inject(BuilderApiService);
  private injector = inject(Injector);

  loading = signal(false);
  failed = signal(false);

  /** Le graphe est celui de la dernière version enregistrée : le dire quand la spec a bougé depuis. */
  unsaved = computed(() => {
    const status = this.state.saveStatus();
    return this.state.isDirty() || status === 'pending' || status === 'saving';
  });

  /** « échelle|nœud » : une chaîne, pour ne réagir qu'à un vrai changement de position. */
  private focusKey = computed(() => {
    const f = this.store.focus();
    return f ? `${this.store.scale()}|${f.id}` : null;
  });

  private request?: Subscription;

  constructor() {
    // Au montage, puis à chaque fois que la spec enregistrée change : `lab` est
    // relu par le service après chaque enregistrement réussi.
    effect(() => {
      const id = this.state.savedId();
      this.state.lab();
      untracked(() => this.load(id));
    });

    // Le nœud en focus est amené à l'écran une fois l'échelle rendue — seulement
    // quand la position change, pas à chaque rechargement du graphe.
    effect(() => {
      const key = this.focusKey();
      if (!key) return;
      afterNextRender(() => {
        const el = document.getElementById(this.store.domId(key.slice(key.indexOf('|') + 1)));
        if (!el) return;
        const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        el.scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' });
        el.focus({ preventScroll: true });
      }, { injector: this.injector });
    });
  }

  ngOnDestroy(): void { this.request?.unsubscribe(); }

  reload(): void { this.load(this.state.savedId()); }

  private load(id: number | null): void {
    // Une requête en cours ne vaut plus rien : sa réponse décrirait un état dépassé.
    this.request?.unsubscribe();
    if (id === null) {
      this.store.graph.set(null);
      this.loading.set(false);
      this.failed.set(false);
      return;
    }
    // Autre spec que celle affichée : ne pas laisser le graphe de la précédente à l'écran.
    if (this.store.graph()?.spec.id !== id) this.store.graph.set(null);
    this.loading.set(true);
    this.failed.set(false);
    this.request = this.api.getGraph(id).subscribe({
      next: res => {
        if (this.state.savedId() !== id) return;   // réponse arrivée après un changement de spec
        this.store.graph.set(res);
        this.loading.set(false);
      },
      error: () => {
        if (this.state.savedId() !== id) return;
        this.store.graph.set(null);
        this.failed.set(true);
        this.loading.set(false);
      },
    });
  }
}
