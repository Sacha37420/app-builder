import { Component, computed, inject } from '@angular/core';
import { OverviewStore } from './overview.store';
import { LotTagsComponent } from './lot-tags.component';

/** Types de champ en clair, pour un lecteur qui ne code pas. */
const TYPES: Record<string, string> = {
  string: 'texte court', text: 'texte long', int: 'nombre entier', decimal: 'nombre décimal',
  bool: 'oui / non', datetime: 'date et heure', json: 'données libres (JSON)',
  storage_file: 'fichier (storage)', file: 'fichier',
};

/** Échelle « Données » : une carte par modèle, ses champs et ses relations dans les deux sens. */
@Component({
  selector: 'app-ov-data',
  standalone: true,
  imports: [LotTagsComponent],
  templateUrl: './scale-data.component.html',
  styleUrl: './scale-data.component.scss',
})
export class ScaleDataComponent {
  store = inject(OverviewStore);

  models = computed(() => this.store.ofKind('data_model'));

  typeLabel(t: string): string { return TYPES[t] ?? t; }

  /** Qui lit ce modèle (routes et pages), en une ligne ; '' sinon. */
  readers(id: string): string {
    return this.store.linked(id, 'reads', 'in')
      .map(n => `${this.store.kind(n).label.toLowerCase()} ${n.label}`).join(', ');
  }
}
