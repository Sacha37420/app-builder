import { Component, inject, input } from '@angular/core';
import { OverviewStore } from './overview.store';

/** Étiquettes « Lot N » d'un élément : chacune mène au lot qui le construit, dans la feuille de route. */
@Component({
  selector: 'app-ov-lots',
  standalone: true,
  template: `
    @for (l of store.lots(node()); track l.id) {
      <button type="button" class="ov-chip k-purple" (click)="store.goNode(l)"
              [attr.aria-label]="'Construit par le lot ' + l.order + ' : voir dans la feuille de route'">
        <span>Lot {{ l.order }}</span>
      </button>
    }
  `,
  styles: `:host { display: contents; }`,
})
export class LotTagsComponent {
  store = inject(OverviewStore);
  /** Identifiant du nœud dont on montre les lots. */
  node = input.required<string>();
}
