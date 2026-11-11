import { afterNextRender, Component, computed, ElementRef, inject, Injector, output, signal, viewChild } from '@angular/core';
import { GraphNode } from '../../models/app-spec.model';
import { OverviewStore } from './overview.store';

const norm = (s: string): string => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

/**
 * « Aller à… » (Ctrl+K) : recherche sur le libellé et le chemin (`attrs.path`) de
 * tous les nœuds ; le choix pose la sélection et prend la vue d'origine du nœud.
 */
@Component({
  selector: 'app-ov-goto',
  standalone: true,
  styleUrl: './goto.component.scss',
  template: `
    <div class="ov-goto-backdrop" (click)="closed.emit()"></div>
    <div class="ov-goto" role="dialog" aria-modal="true" aria-labelledby="ov-goto-label">
      <label id="ov-goto-label" class="ov-insp-sub" for="ov-goto-input">Aller à…</label>
      <input #box id="ov-goto-input" class="ov-goto-input" type="search" autocomplete="off"
             role="combobox" aria-controls="ov-goto-list" [attr.aria-activedescendant]="active() >= 0 ? 'ov-goto-' + active() : null"
             [value]="query()" (input)="query.set($any($event.target).value); active.set(0)"
             (keydown)="key($event)" placeholder="Modèle, route, page, pipeline…" />
      <ul id="ov-goto-list" class="ov-goto-list" role="listbox">
        @for (n of results(); track n.id; let i = $index) {
          <li [id]="'ov-goto-' + i" role="option" [attr.aria-selected]="i === active()">
            <button type="button" class="ov-goto-item" [class.active]="i === active()" (click)="pick(n)" tabindex="-1">
              <span [class]="'ov-kind ' + store.kind(n).cat">{{ store.kind(n).label }}</span>
              <span>{{ n.label }}</span>
              <span class="ov-faint">{{ store.scaleLabel(n.scale) }}</span>
            </button>
          </li>
        } @empty {
          <li class="ov-faint ov-goto-none">{{ query() ? 'Aucun élément.' : 'Tapez quelques lettres.' }}</li>
        }
      </ul>
      <button type="button" class="ov-btn" (click)="closed.emit()">Fermer</button>
    </div>
  `,
})
export class GotoComponent {
  store = inject(OverviewStore);
  private injector = inject(Injector);
  closed = output<void>();
  private box = viewChild<ElementRef<HTMLInputElement>>('box');

  query = signal('');
  active = signal(0);

  results = computed<GraphNode[]>(() => {
    const q = norm(this.query().trim());
    if (!q) return [];
    const out: GraphNode[] = [];
    for (const n of this.store.all()) {
      const path = typeof n.attrs?.['path'] === 'string' ? (n.attrs['path'] as string) : '';
      if (norm(n.label).includes(q) || (path && norm(path).includes(q))) out.push(n);
      if (out.length >= 30) break;
    }
    return out;
  });

  constructor() {
    afterNextRender(() => this.box()?.nativeElement.focus(), { injector: this.injector });
  }

  key(e: KeyboardEvent): void {
    const n = this.results().length;
    if (e.key === 'ArrowDown') { e.preventDefault(); this.active.update(i => (n ? (i + 1) % n : 0)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); this.active.update(i => (n ? (i - 1 + n) % n : 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); const r = this.results()[this.active()]; if (r) this.pick(r); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.closed.emit(); }
  }

  pick(n: GraphNode): void {
    this.store.open(n.scale, n.id);
    this.closed.emit();
  }
}
