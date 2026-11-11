import { Component, computed, inject } from '@angular/core';
import { GraphNode } from '../../models/app-spec.model';
import { OverviewStore } from './overview.store';

interface CellView { text: string; icon: string; cls: string; }

const CELLS: Record<string, CellView> = {
  allow:        { text: 'autorisé',  icon: '✓', cls: 'ov-allow' },
  deny:         { text: 'refusé',    icon: '·', cls: 'ov-deny' },
  inconsistent: { text: 'à revoir', icon: '◐', cls: 'ov-incons' },
};

/**
 * Vue « Sécurité » (notation `matrix`) : la matrice rôles × ressources calculée
 * par le serveur (`matrices.security`). Le texte de la cellule dit tout, l'icône
 * et la teinte ne font que le doubler. En mode liste (téléphone), un accordéon
 * par ligne.
 */
@Component({
  selector: 'app-ov-security',
  standalone: true,
  template: `
    <p class="ov-muted">
      Deux verrous protègent l'app : le flow Keycloak à la connexion, puis l'API qui vérifie elle-même
      le client (<span class="ov-mono">azp</span>) et les groupes du jeton. La matrice dit qui atteint quoi.
    </p>
    @if (matrix(); as m) {
      @if (incoherent() > 0) {
        <p class="ov-muted">
          {{ incoherent() }} case(s) « à revoir » : une page ouverte à cette ligne appelle une route qui lui est
          réservée ailleurs. Ce n'est pas forcément une erreur (la page peut masquer l'action) ; le détail est dans les notes.
        </p>
      }
      @if (store.mode() === 'carte') {
        <div class="ov-table-wrap">
          <table class="ov-matrix">
            <caption class="ov-sr">Accès de chaque rôle ou groupe à chaque ressource</caption>
            <thead>
              <tr><th scope="col">Qui</th>
                @for (c of m.cols; track $index) {
                  @let cn = col(c);
                  <th scope="col" [class.is-ghost]="store.isGhost(cn)">
                    @if (cn) {
                      <button type="button" class="ov-link" [class.is-focus]="store.isFocus(cn.id)" (click)="store.select(cn)">{{ cn.label }}</button>
                    } @else { {{ c }} }
                  </th>
                }
              </tr>
            </thead>
            <tbody>
              @for (r of m.rows; track $index; let ri = $index) {
                <tr>
                  <th scope="row">{{ rowLabel(r) }}</th>
                  @for (c of m.cols; track $index; let ci = $index) {
                    @let v = cell(m.cells[ri]?.[ci]);
                    <td [class]="v.cls" [attr.title]="m.notes['' + ri + ',' + ci] || null">
                      <span aria-hidden="true">{{ v.icon }}</span> {{ v.text }}
                      @if (m.notes['' + ri + ',' + ci]) { <sup>*</sup> }
                    </td>
                  }
                </tr>
              }
            </tbody>
          </table>
        </div>
      } @else {
        @for (r of m.rows; track $index; let ri = $index) {
          <details class="ov-card ov-acc">
            <summary>{{ rowLabel(r) }}</summary>
            <ul>
              @for (c of m.cols; track $index; let ci = $index) {
                @let v = cell(m.cells[ri]?.[ci]);
                <li [class]="v.cls">
                  <span aria-hidden="true">{{ v.icon }}</span> {{ v.text }} —
                  @let cn = col(c);
                  @if (cn) { <button type="button" class="ov-link" (click)="store.select(cn)">{{ cn.label }}</button> } @else { {{ c }} }
                  @if (m.notes['' + ri + ',' + ci]; as note) { <span class="ov-faint">({{ note }})</span> }
                </li>
              }
            </ul>
          </details>
        }
      }
      @if (notes().length) {
        <h3 class="ov-h2">Notes</h3>
        <ul class="ov-notes">
          @for (n of notes(); track n.key) { <li><strong>{{ n.where }}</strong> : {{ n.text }}</li> }
        </ul>
      }
    } @else {
      <p class="ov-card ov-empty">Matrice indisponible : le serveur ne la fournit pas encore.</p>
    }
  `,
})
export class ScaleSecurityComponent {
  store = inject(OverviewStore);

  matrix = computed(() => this.store.graph()?.matrices?.security ?? null);

  incoherent = computed(() => {
    const m = this.matrix();
    return m ? m.cells.flat().filter(c => c === 'inconsistent').length : 0;
  });

  notes = computed(() => {
    const m = this.matrix();
    if (!m) return [];
    return Object.entries(m.notes ?? {}).map(([key, text]) => {
      const [r, c] = key.split(',').map(Number);
      const cn = this.col(m.cols[c] ?? '');
      return { key, text, where: `${this.rowLabel(m.rows[r] ?? '')} × ${cn?.label ?? m.cols[c] ?? '?'}` };
    });
  });

  col(c: string): GraphNode | null { return this.store.resolve(c, ['endpoint', 'page']); }

  cell(v: string | undefined): CellView {
    return CELLS[v ?? ''] ?? { text: v ?? '?', icon: '', cls: '' };
  }

  rowLabel(r: string): string {
    if (r === 'public') return 'Visiteur anonyme';
    const [kind, ...rest] = r.split(':');
    const name = rest.join(':');
    if (!name) return r;
    if (kind === 'groupe' || kind === 'group') return `Groupe ${name}`;
    if (kind === 'role') return `Rôle ${name}`;
    return r;
  }
}
