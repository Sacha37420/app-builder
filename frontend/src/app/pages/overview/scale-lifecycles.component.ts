import { Component, computed, inject } from '@angular/core';
import { BuilderStateService } from '../../core/builder-state.service';
import { DataModel, GraphNode, StateTransition } from '../../models/app-spec.model';
import { OverviewStore } from './overview.store';

interface Box { value: string; x: number; initial: boolean; frozen: boolean; }
interface Arc { d: string; lx: number; ly: number; label: string; }
interface Chart {
  model: DataModel; node: GraphNode | null; field: string; boxes: Box[]; arcs: Arc[];
  width: number; height: number; top: number; transitions: StateTransition[];
}

const W = 140, H = 44, GAP = 50;

/**
 * Vue « Cycles de vie » (notation `statechart`) : pour chaque modèle qui décrit
 * des états (I1 `states`), ses états en ligne et ses transitions en arcs (vers
 * la droite au-dessus, vers la gauche en dessous). Lue sur la spec en cours
 * d'édition ; rien n'est deviné à partir d'un champ « statut ».
 */
@Component({
  selector: 'app-ov-lifecycles',
  standalone: true,
  template: `
    @if (charts().length === 0) {
      <p class="ov-card ov-empty">Aucun modèle ne décrit de cycle de vie (états et transitions). Décrivez-le dans la page Modèles.</p>
    }
    @for (c of charts(); track c.model.name) {
      <section class="ov-card k-cyan ov-lc">
        <h2 class="ov-name">
          @if (c.node) {
            <button type="button" class="ov-link" [class.is-focus]="store.isFocus(c.node.id)" (click)="store.select(c.node)">{{ c.model.name }}</button>
          } @else { {{ c.model.name }} }
          <span class="ov-faint ov-mono">· {{ c.field }}</span>
        </h2>
        @if (store.mode() === 'carte' && c.boxes.length) {
          <div class="ov-diagram" [style.height.px]="c.height">
            <div class="ov-diagram-inner" [style.width.px]="c.width" [style.height.px]="c.height">
              <svg class="ov-links" [attr.width]="c.width" [attr.height]="c.height" aria-hidden="true">
                <defs>
                  <marker [attr.id]="'arrow-' + $index" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                    <path d="M 0 0 L 10 5 L 0 10 z" class="ov-arrow" />
                  </marker>
                </defs>
                @for (a of c.arcs; track $index) {
                  <path [attr.d]="a.d" class="ov-edge" [attr.marker-end]="'url(#arrow-' + $index + ')'" />
                  <text [attr.x]="a.lx" [attr.y]="a.ly" class="ov-edge-label" text-anchor="middle">{{ a.label }}</text>
                }
              </svg>
              @for (b of c.boxes; track b.value) {
                <button type="button" class="ov-dnode" [style.left.px]="b.x" [style.top.px]="c.top"
                        [style.width.px]="W" [class.is-initial]="b.initial" [class.is-frozen]="b.frozen"
                        (click)="pick(c, b.value)">
                  {{ b.value }}
                  @if (b.initial) { <span class="ov-sr">(état initial)</span> }
                  @if (b.frozen) { <span class="ov-faint">figé</span> }
                </button>
              }
            </div>
          </div>
        }
        <ol class="ov-trans">
          @for (t of c.transitions; track $index) {
            <li>
              <span class="ov-mono">{{ (t.from || []).join(', ') || '∅' }}</span> <span aria-hidden="true">→</span>
              <span class="ov-sr">vers</span> <span class="ov-mono">{{ t.to }}</span>
              @if (t.by?.length) { <span class="ov-faint">· par {{ t.by!.join(', ') }}</span> }
              @if (t.action) { <span class="ov-faint ov-mono">· {{ t.action }}</span> }
              @if (t.side_effects?.length) { <span class="ov-faint">· effets : {{ t.side_effects!.join(', ') }}</span> }
            </li>
          } @empty {
            <li class="ov-faint">Aucune transition décrite.</li>
          }
        </ol>
      </section>
    }
  `,
})
export class ScaleLifecyclesComponent {
  store = inject(OverviewStore);
  private state = inject(BuilderStateService);
  readonly W = W;

  charts = computed<Chart[]>(() => this.state.spec().data_models
    .filter(m => (m.states?.values?.length ?? 0) > 0 || (m.states?.transitions?.length ?? 0) > 0)
    .map(m => this.chart(m)));

  private chart(m: DataModel): Chart {
    const st = m.states ?? {};
    const values = [...(st.values ?? [])];
    for (const t of st.transitions ?? []) {
      for (const v of [...(t.from ?? []), t.to]) if (v && !values.includes(v)) values.push(v);
    }
    const pos = new Map(values.map((v, i) => [v, i]));
    const centre = (i: number) => i * (W + GAP) + W / 2;
    const raw: { i: number; j: number; h: number; label: string }[] = [];
    let up = 0, down = 0;
    for (const t of st.transitions ?? []) {
      const j = pos.get(t.to);
      if (j === undefined) continue;
      for (const f of t.from ?? []) {
        const i = pos.get(f);
        if (i === undefined) continue;
        const h = i === j ? 30 : 24 + 18 * Math.abs(j - i);
        if (j >= i) up = Math.max(up, h); else down = Math.max(down, h);
        raw.push({ i, j, h, label: t.action ? t.action.split(' ')[0] : (t.by ?? []).join(', ') });
      }
    }
    const top = up + 20;
    const height = top + H + down + 20;
    const arcs: Arc[] = raw.map(({ i, j, h, label }) => {
      const xi = centre(i), xj = centre(j);
      if (i === j) {
        return { d: `M ${xi - 15} ${top} C ${xi - 30} ${top - h}, ${xi + 30} ${top - h}, ${xi + 15} ${top}`,
                 lx: xi, ly: top - h + 4, label };
      }
      if (j > i) return { d: `M ${xi} ${top} Q ${(xi + xj) / 2} ${top - 2 * h} ${xj} ${top}`, lx: (xi + xj) / 2, ly: top - h - 4, label };
      const y = top + H;
      return { d: `M ${xi} ${y} Q ${(xi + xj) / 2} ${y + 2 * h} ${xj} ${y}`, lx: (xi + xj) / 2, ly: y + h + 12, label };
    });
    return {
      model: m, node: this.store.byLabel('data_model', m.name), field: st.field ?? 'statut',
      boxes: values.map((v, i) => ({ value: v, x: i * (W + GAP), initial: v === st.initial, frozen: (st.frozen_in ?? []).includes(v) })),
      arcs, width: Math.max(values.length * (W + GAP) - GAP, W), height, top, transitions: st.transitions ?? [],
    };
  }

  /** Le nœud `state` du graphe s'il existe sous ce modèle, sinon le modèle lui-même. */
  pick(c: Chart, value: string): void {
    const own = c.node ? this.store.children(c.node.id, 'state').find(n => n.label === value) : null;
    const any = own ?? this.store.all().find(n => n.kind === 'state' && n.label === value && (!c.node || n.parent === c.node.id)) ?? null;
    this.store.select(any ?? c.node);
  }
}
