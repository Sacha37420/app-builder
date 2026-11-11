import { Component, computed, inject } from '@angular/core';
import { GraphNode } from '../../models/app-spec.model';
import { OverviewStore } from './overview.store';

const OPS: Record<string, string> = {
  list: 'lister', create: 'créer', retrieve: 'lire', update: 'remplacer', partial_update: 'modifier',
  delete: 'supprimer', custom: 'autre',
};

/**
 * Vue « API » (notation `tree`) : l'arbre groupe → route, puis la matrice CRUD
 * modèles × opérations calculée par le serveur (`matrices.crud`). Un trou (modèle
 * sans `delete`, par exemple) se lit d'un coup d'œil ; une route publique sans
 * justification est signalée.
 */
@Component({
  selector: 'app-ov-api',
  standalone: true,
  template: `
    <h2 class="ov-h2">Routes par groupe</h2>
    @if (groups().length === 0) {
      <p class="ov-card ov-empty">Aucun groupe d'endpoints décrit.</p>
    } @else {
      <ul class="ov-tree">
        @for (g of groups(); track g.id) {
          <li>
            <button type="button" class="ov-node k-blue" [id]="store.domId(g.id)"
                    [class.is-focus]="store.isFocus(g.id)" [class.is-ghost]="store.isGhost(g)"
                    (click)="store.select(g)">
              <span class="ov-kind">{{ store.kind(g).label }}</span> {{ g.label }}
              <span class="ov-faint">{{ store.countLabel(g) }}</span>
            </button>
            <ul>
              @for (e of endpoints(g); track e.id) {
                <li>
                  <button type="button" class="ov-node ov-node-sm" [id]="store.domId(e.id)"
                          [class.is-focus]="store.isFocus(e.id)" [class.is-ghost]="store.isGhost(e)"
                          (click)="store.select(e)">
                    <span class="ov-mono">{{ e.label }}</span>
                    @if (op(e); as o) { <span class="ov-faint">{{ o }}</span> }
                    @if (e.public) { <span class="ov-tag-warn">public</span> }
                    @if (e.roles?.length) { <span class="ov-faint">rôles : {{ e.roles!.join(', ') }}</span> }
                    @if (e.issues?.length) { <span class="ov-tag-warn" [title]="issueText(e)">⚠ {{ e.issues!.length }}</span> }
                  </button>
                </li>
              }
            </ul>
          </li>
        }
      </ul>
    }

    <h2 class="ov-h2">Matrice CRUD — modèles × opérations</h2>
    @if (crud(); as m) {
      @if (m.rows.length === 0) {
        <p class="ov-card ov-empty">Aucun modèle.</p>
      } @else {
        <div class="ov-table-wrap">
          <table class="ov-matrix">
            <caption class="ov-sr">Routes de chaque modèle, par opération ; « — » : aucune route</caption>
            <thead>
              <tr><th scope="col">Modèle</th>
                @for (c of m.cols; track c) { <th scope="col">{{ opLabel(c) }}</th> }
              </tr>
            </thead>
            <tbody>
              @for (r of m.rows; track $index; let ri = $index) {
                @let rn = store.resolve(r, ['data_model']);
                <tr [class.is-ghost]="store.isGhost(rn)">
                  <th scope="row">
                    @if (rn) {
                      <button type="button" class="ov-link" [class.is-focus]="store.isFocus(rn.id)" (click)="store.select(rn)">{{ rn.label }}</button>
                    } @else { {{ r }} }
                  </th>
                  @for (c of m.cols; track c; let ci = $index) {
                    <td [class.ov-hole]="!(m.cells[ri]?.[ci]?.length)">
                      @for (route of m.cells[ri]?.[ci] ?? []; track route) {
                        @let en = store.byLabel('endpoint', route);
                        @if (en) {
                          <button type="button" class="ov-link ov-mono" [class.is-focus]="store.isFocus(en.id)" (click)="store.select(en)">{{ route }}</button>
                        } @else { <span class="ov-mono">{{ route }}</span> }
                      } @empty { <span aria-label="aucune route">—</span> }
                    </td>
                  }
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    } @else {
      <p class="ov-muted">Matrice indisponible : le serveur ne la fournit pas encore.</p>
    }
  `,
})
export class ScaleApiComponent {
  store = inject(OverviewStore);

  groups = computed(() => this.store.ofKind('endpoint_group'));
  crud = computed(() => this.store.graph()?.matrices?.crud ?? null);

  endpoints(g: GraphNode): GraphNode[] { return this.store.children(g.id, 'endpoint'); }

  op(e: GraphNode): string {
    const o = e.attrs?.['operation'];
    return typeof o === 'string' ? (OPS[o] ?? o) : '';
  }
  opLabel(c: string): string { return OPS[c] ?? c; }
  issueText(n: GraphNode): string { return (n.issues ?? []).map(i => i.message).join(' ; '); }
}
