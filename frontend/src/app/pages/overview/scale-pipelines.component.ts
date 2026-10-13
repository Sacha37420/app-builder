import { Component, computed, inject } from '@angular/core';
import { GraphNode } from '../../models/app-spec.model';
import { OverviewStore } from './overview.store';
import { LotTagsComponent } from './lot-tags.component';

/** Types d'étape et d'interaction en clair. */
const STEP_TYPES: Record<string, string> = {
  trigger: 'déclencheur', service_call: 'appel de service', transform: 'transformation',
  state_update: "mise à jour de l'affichage", navigate: 'changement de page', error: "gestion d'erreur",
};
const INTERACTION_TYPES: Record<string, string> = {
  click: 'clic', form: 'formulaire', navigation: 'navigation', display: 'affichage', other: 'autre',
};

/**
 * Échelle « Pipelines » : par page, chaque pipeline avec l'interaction qui le
 * déclenche et ses étapes en frise numérotée. Le sélecteur de page pose le
 * filtre dans l'URL (`noeud=page:<nom>`), comme une entrée depuis l'architecture.
 */
@Component({
  selector: 'app-ov-pipelines',
  standalone: true,
  imports: [LotTagsComponent],
  templateUrl: './scale-pipelines.component.html',
  styleUrl: './scale-pipelines.component.scss',
})
export class ScalePipelinesComponent {
  store = inject(OverviewStore);

  /** Toutes les pages de la spec (le sélecteur), et celles que le filtre laisse à l'écran. */
  allPages = computed(() => (this.store.graph()?.nodes ?? []).filter(n => n.kind === 'page'));
  pages = computed(() => this.store.ofKind('page'));

  /** Page choisie dans le sélecteur : '' = toutes. */
  selected = computed(() => {
    const f = this.store.filter();
    return f?.kind === 'page' ? f.id : '';
  });

  pick(id: string): void { this.store.open('pipelines', id || null); }

  pipelines(page: GraphNode): GraphNode[] { return this.store.children(page.id, 'pipeline'); }
  interactions(page: GraphNode): GraphNode[] { return this.store.children(page.id, 'interaction'); }

  steps(pipeline: GraphNode): GraphNode[] {
    return this.store.children(pipeline.id, 'step').sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
  }

  stepType(t: string): string { return STEP_TYPES[t] ?? t; }
  interactionType(t: string): string { return INTERACTION_TYPES[t] ?? t; }
}
