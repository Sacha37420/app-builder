import { Component, computed, inject } from '@angular/core';
import { OverviewStore } from './overview.store';

/**
 * Échelle « Feuille de route » : les lots dans l'ordre, chacun relié aux
 * éléments de la spec qu'il construit (liens `builds`) — chaque élément mène à
 * son nœud, dans son échelle.
 */
@Component({
  selector: 'app-ov-roadmap',
  standalone: true,
  templateUrl: './scale-roadmap.component.html',
  styleUrl: './scale-roadmap.component.scss',
})
export class ScaleRoadmapComponent {
  store = inject(OverviewStore);

  lots = computed(() =>
    [...this.store.ofKind('lot')].sort((a, b) => (a.order ?? 0) - (b.order ?? 0)));
}
