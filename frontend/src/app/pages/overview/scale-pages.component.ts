import { Component, computed, inject } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { GraphNode } from '../../models/app-spec.model';
import { OverviewStore } from './overview.store';

interface SiteNode { segment: string; path: string; pages: GraphNode[]; children: SiteNode[]; }

/** La route d'une page : `attrs.route`, sinon le `detail` v1 (qui porte la route). */
function routeOf(n: GraphNode): string {
  const r = n.attrs?.['route'];
  return (typeof r === 'string' && r) ? r : (n.detail || '/');
}

/**
 * Vue « Pages » (notation `sitemap`) : le plan du site, arbre des segments de
 * route ; chaque page dit ses composants et qui y accède. L'arbre est à la fois
 * le schéma et sa liste équivalente.
 */
@Component({
  selector: 'app-ov-pages',
  standalone: true,
  imports: [NgTemplateOutlet],
  template: `
    @if (pages().length === 0) {
      <p class="ov-card ov-empty">Aucune page décrite.</p>
    } @else {
      <ng-template #branch let-nodes>
        <ul class="ov-tree">
          @for (s of nodes; track s.path) {
            <li>
              <span class="ov-mono ov-seg">{{ s.segment }}</span>
              @for (p of s.pages; track p.id) {
                <button type="button" class="ov-node k-green" [id]="store.domId(p.id)"
                        [class.is-focus]="store.isFocus(p.id)" [class.is-ghost]="store.isGhost(p)"
                        (click)="store.select(p)">
                  <span class="ov-kind">{{ store.kind(p).label }}</span> {{ p.label }}
                  @if (flag(p, 'public')) { <span class="ov-tag-warn">publique</span> }
                  @if (roles(p); as r) { <span class="ov-faint">rôles : {{ r }}</span> }
                  @if (p.issues?.length) { <span class="ov-tag-warn">⚠ {{ p.issues!.length }}</span> }
                </button>
              }
              @if (s.children.length) {
                <ng-container *ngTemplateOutlet="branch; context: { $implicit: s.children }" />
              }
            </li>
          }
        </ul>
      </ng-template>
      <ng-container *ngTemplateOutlet="branch; context: { $implicit: tree().children }" />
    }
  `,
})
export class ScalePagesComponent {
  store = inject(OverviewStore);

  pages = computed(() => this.store.ofKind('page'));

  tree = computed<SiteNode>(() => {
    const root: SiteNode = { segment: '/', path: '', pages: [], children: [] };
    const top: SiteNode = { segment: '/', path: '/', pages: [], children: [] };
    root.children.push(top);
    for (const p of this.pages()) {
      const segs = routeOf(p).split('/').filter(Boolean);
      let cur = top;
      let path = '';
      for (const seg of segs) {
        path += '/' + seg;
        let next = cur.children.find(c => c.path === path);
        if (!next) { next = { segment: '/' + seg, path, pages: [], children: [] }; cur.children.push(next); }
        cur = next;
      }
      cur.pages.push(p);
    }
    return root;
  });

  flag(p: GraphNode, key: string): boolean { return p.attrs?.[key] === true; }

  roles(p: GraphNode): string {
    const r = p.attrs?.['required_roles'];
    return Array.isArray(r) ? r.join(', ') : '';
  }
}
