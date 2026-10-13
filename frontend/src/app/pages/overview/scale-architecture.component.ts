import { Component, computed, effect, inject, signal } from '@angular/core';
import { GraphLinkKind, GraphNode } from '../../models/app-spec.model';
import { OverviewStore } from './overview.store';
import { LotTagsComponent } from './lot-tags.component';

/**
 * Échelle « Architecture » : Pages → Services → Groupes d'endpoints. Les liens
 * `uses` et `calls` ne sont pas tracés : l'élément survolé, en focus clavier ou
 * épinglé d'un clic sur sa carte est mis en avant avec ses voisins directs, le reste estompé,
 * et chaque carte nomme ses voisins en toutes lettres.
 */
@Component({
  selector: 'app-ov-architecture',
  standalone: true,
  imports: [LotTagsComponent],
  templateUrl: './scale-architecture.component.html',
  styleUrl: './scale-architecture.component.scss',
})
export class ScaleArchitectureComponent {
  store = inject(OverviewStore);

  pages = computed(() => this.store.ofKind('page'));
  services = computed(() => this.store.ofKind('service'));
  groups = computed(() => this.store.ofKind('endpoint_group'));
  empty = computed(() => this.pages().length + this.services().length + this.groups().length === 0);

  /** Survol ou focus clavier (passager), et épingle posée d'un clic (durable). */
  hover = signal<string | null>(null);
  pinned = signal<string | null>(null);
  /** Groupes dépliés sur leurs endpoints. */
  private opened = signal<ReadonlySet<string>>(new Set());

  /** L'élément dont on montre les liens ; à défaut, le nœud en focus de la page. */
  private active = computed<string | null>(() => {
    const own = this.hover() ?? this.pinned();
    if (own) return own;
    const f = this.store.focus();
    if (!f || f.scale !== 'architecture') return null;
    return f.kind === 'endpoint' ? f.parent : f.id;
  });

  /** L'élément actif et ses voisins directs (`uses`, `calls`, dans les deux sens). */
  private near = computed<ReadonlySet<string> | null>(() => {
    const id = this.active();
    if (!id) return null;
    const s = this.store;
    const out = new Set<string>([id]);
    for (const kind of ['uses', 'calls'] as const) {
      for (const dir of ['out', 'in'] as const) s.linked(id, kind, dir).forEach(n => out.add(n.id));
    }
    return out;
  });

  constructor() {
    // Entrer sur un groupe ou sur un de ses endpoints le déplie.
    effect(() => {
      const f = this.store.focus();
      const id = f?.kind === 'endpoint_group' ? f.id : f?.kind === 'endpoint' ? f.parent : null;
      if (id) this.opened.update(set => new Set(set).add(id));
    });
  }

  isDim(id: string): boolean { const n = this.near(); return n !== null && !n.has(id); }
  isNear(id: string): boolean { return this.near()?.has(id) ?? false; }

  togglePin(id: string): void { this.pinned.update(p => (p === id ? null : id)); }

  isOpen(id: string): boolean { return this.opened().has(id); }

  toggleOpen(id: string): void {
    this.opened.update(set => {
      const next = new Set(set);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  endpoints(g: GraphNode): GraphNode[] { return this.store.children(g.id, 'endpoint'); }

  /** Noms des voisins, en une ligne ; '' quand il n'y en a pas. */
  names(id: string, kind: GraphLinkKind, dir: 'out' | 'in'): string {
    return this.store.linked(id, kind, dir).map(n => n.label).join(', ');
  }
}
