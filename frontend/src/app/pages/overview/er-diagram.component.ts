import { Component, computed, inject, signal } from '@angular/core';
import { GraphLink, GraphNode } from '../../models/app-spec.model';
import { OverviewStore } from './overview.store';

interface Box { node: GraphNode; x: number; y: number; h: number; fields: { name: string; type: string }[]; more: number; }
interface Edge { d: string; label: string; s: { x: number; y: number; t: string }; t: { x: number; y: number; t: string }; near: boolean; }

const W = 220, HEAD = 48, ROW = 20, GX = 110, GY = 28, PAD = 24, MAX_FIELDS = 8;

/**
 * Diagramme entité-relation de la vue « Données » (notation `er`) : nœuds HTML
 * (`<button>`) au-dessus d'une couche SVG qui ne trace que les liens. Mise en page
 * en couches calculée ici, sans bibliothèque : un modèle est placé à droite des
 * modèles vers lesquels il pointe (profondeur de clés étrangères). Zoom sémantique
 * simple : en vue lointaine, seuls les noms ; le modèle sélectionné et ses
 * voisins gardent leurs champs.
 */
@Component({
  selector: 'app-ov-er',
  standalone: true,
  template: `
    <div class="ov-zoom" role="group" aria-label="Zoom du diagramme">
      <button type="button" class="ov-btn" (click)="zoomBy(-0.15)" aria-label="Dézoomer">−</button>
      <span class="ov-faint">{{ pct() }} %</span>
      <button type="button" class="ov-btn" (click)="zoomBy(0.15)" aria-label="Zoomer">+</button>
      <button type="button" class="ov-btn" (click)="zoom.set(1)">100 %</button>
    </div>
    <div class="ov-diagram" [style.height.px]="layout().height * zoom() + 2">
      <div class="ov-diagram-inner" [style.width.px]="layout().width" [style.height.px]="layout().height"
           [style.transform]="'scale(' + zoom() + ')'">
        <svg class="ov-links" [attr.width]="layout().width" [attr.height]="layout().height" aria-hidden="true">
          @for (e of layout().edges; track $index) {
            <path [attr.d]="e.d" class="ov-edge" [class.is-near]="e.near" />
            @if (e.s.t) { <text [attr.x]="e.s.x" [attr.y]="e.s.y" class="ov-edge-label" text-anchor="middle">{{ e.s.t }}</text> }
            @if (e.t.t) { <text [attr.x]="e.t.x" [attr.y]="e.t.y" class="ov-edge-label" text-anchor="middle">{{ e.t.t }}</text> }
          }
        </svg>
        @for (b of layout().boxes; track b.node.id) {
          <button type="button" class="ov-dnode ov-er-node k-cyan" [id]="store.domId(b.node.id)"
                  [style.left.px]="b.x" [style.top.px]="b.y" [style.width.px]="W" [style.min-height.px]="b.h"
                  [class.is-focus]="store.isFocus(b.node.id)" [class.is-ghost]="store.isGhost(b.node)"
                  [class.is-dim]="dim(b.node.id)" (click)="store.select(b.node)"
                  [attr.aria-label]="b.node.label + ' — ' + store.countLabel(b.node)">
            <span class="ov-er-name">{{ b.node.label }}</span>
            @if (b.node.issues?.length) { <span class="ov-tag-warn">⚠</span> }
            @for (f of b.fields; track $index) {
              <span class="ov-er-field"><span class="ov-mono">{{ f.name }}</span><span class="ov-faint">{{ f.type }}</span></span>
            }
            @if (b.more) { <span class="ov-faint">+{{ b.more }} champs</span> }
          </button>
        }
      </div>
    </div>
  `,
})
export class ErDiagramComponent {
  store = inject(OverviewStore);
  readonly W = W;
  zoom = signal(1);
  pct = computed(() => Math.round(this.zoom() * 100));

  zoomBy(d: number): void { this.zoom.update(z => Math.min(1.6, Math.max(0.4, Math.round((z + d) * 100) / 100))); }

  private models = computed(() => this.store.ofKind('data_model'));

  private rels = computed<GraphLink[]>(() => {
    const ids = new Set(this.models().map(m => m.id));
    const out: GraphLink[] = [];
    for (const m of this.models()) {
      for (const l of this.store.links(m.id, 'relation', 'out')) if (ids.has(l.target)) out.push(l);
    }
    return out;
  });

  /** Le modèle sélectionné et ses voisins par relation : ils gardent leurs champs à tout zoom. */
  private near = computed<Set<string> | null>(() => {
    const f = this.store.focus();
    if (!f || f.kind !== 'data_model') return null;
    const s = new Set([f.id]);
    for (const l of this.rels()) {
      if (l.source === f.id) s.add(l.target);
      if (l.target === f.id) s.add(l.source);
    }
    return s;
  });

  dim(id: string): boolean { const n = this.near(); return n !== null && !n.has(id); }

  layout = computed(() => {
    const models = this.models();
    const rels = this.rels();
    const targets = new Map<string, string[]>();
    for (const l of rels) if (l.source !== l.target) (targets.get(l.source) ?? targets.set(l.source, []).get(l.source)!).push(l.target);
    const rank = new Map<string, number>();
    const visiting = new Set<string>();
    const rankOf = (id: string): number => {
      if (rank.has(id)) return rank.get(id)!;
      if (visiting.has(id)) return 0;                 // cycle : coupé ici
      visiting.add(id);
      const r = Math.max(-1, ...(targets.get(id) ?? []).map(rankOf)) + 1;
      visiting.delete(id);
      rank.set(id, r);
      return r;
    };
    models.forEach(m => rankOf(m.id));

    const detailed = this.zoom() >= 0.75;
    const near = this.near();
    const cols = new Map<number, number>();         // rang → y courant
    const boxes: Box[] = [];
    const byId = new Map<string, Box>();
    for (const m of models) {
      const r = rank.get(m.id) ?? 0;
      const all = m.fields ?? [];
      const show = detailed || near?.has(m.id) ? all.slice(0, MAX_FIELDS) : [];
      const h = HEAD + show.length * ROW + (show.length && all.length > MAX_FIELDS ? ROW : 0);
      const y = cols.get(r) ?? PAD;
      const b: Box = { node: m, x: PAD + r * (W + GX), y, h, fields: show, more: show.length ? Math.max(0, all.length - show.length) : 0 };
      cols.set(r, y + h + GY);
      boxes.push(b);
      byId.set(m.id, b);
    }
    const width = PAD * 2 + (Math.max(0, ...rank.values()) + 1) * (W + GX) - GX;
    const height = Math.max(PAD * 2, ...[...cols.values()].map(y => y - GY + PAD));

    const edges: Edge[] = [];
    for (const l of rels) {
      const s = byId.get(l.source), t = byId.get(l.target);
      if (!s || !t) continue;
      const sy = s.y + HEAD / 2, ty = t.y + HEAD / 2;
      const card = l.cardinality ?? null;
      const focusId = this.store.focus()?.id;
      const isNear = !!focusId && (l.source === focusId || l.target === focusId);
      if (s === t) {
        const x = s.x + W;
        edges.push({ d: `M ${x} ${sy - 8} C ${x + 50} ${sy - 30}, ${x + 50} ${sy + 30}, ${x} ${sy + 8}`, label: l.label,
                     s: { x: x + 44, y: sy - 18, t: card?.source ?? '' }, t: { x: x + 44, y: sy + 26, t: card?.target ?? '' }, near: isNear });
        continue;
      }
      // La source est à droite de sa cible (elle pointe vers elle) ; sinon, même colonne : on contourne par la droite.
      let x1: number, x2: number;
      if (s.x > t.x) { x1 = s.x; x2 = t.x + W; }
      else if (s.x < t.x) { x1 = s.x + W; x2 = t.x; }
      else { x1 = s.x + W; x2 = t.x + W; }
      const dx = s.x === t.x ? 60 : (x2 - x1) / 2;
      const d = s.x === t.x
        ? `M ${x1} ${sy} C ${x1 + dx} ${sy}, ${x2 + dx} ${ty}, ${x2} ${ty}`
        : `M ${x1} ${sy} C ${x1 + dx} ${sy}, ${x2 - dx} ${ty}, ${x2} ${ty}`;
      const off = (x2 >= x1 ? 1 : -1) * 14;
      edges.push({ d, label: l.label, near: isNear,
                   s: { x: x1 + (s.x === t.x ? 14 : off), y: sy - 6, t: card?.source ?? '' },
                   t: { x: x2 - (s.x === t.x ? -14 : off), y: ty - 6, t: card?.target ?? '' } });
    }
    return { boxes, edges, width: Math.max(width, W + 2 * PAD), height };
  });
}
