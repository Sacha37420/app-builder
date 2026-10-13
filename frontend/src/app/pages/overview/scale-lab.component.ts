import { Component, computed, inject } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { GraphNode } from '../../models/app-spec.model';
import { OverviewStore } from './overview.store';
import { LotTagsComponent } from './lot-tags.component';

interface Hop { node: GraphNode; label: string | null; }

/**
 * Échelle « Dans le lab » : la chaîne groupes → Keycloak → interface → API, puis
 * l'embranchement base / storage / email, dessinée en suivant les liens `flow`.
 */
@Component({
  selector: 'app-ov-lab',
  standalone: true,
  imports: [NgTemplateOutlet, LotTagsComponent],
  templateUrl: './scale-lab.component.html',
  styleUrl: './scale-lab.component.scss',
})
export class ScaleLabComponent {
  store = inject(OverviewStore);

  /** Le tronc (un seul successeur à chaque pas) puis les branches du dernier nœud. */
  layout = computed<{ trunk: Hop[]; branches: Hop[] }>(() => {
    const s = this.store;
    const infra = (s.graph()?.nodes ?? []).filter(n => n.scale === 'overview' && n.kind !== 'business_rule');
    const trunk: Hop[] = [];
    const branches: Hop[] = [];
    const seen = new Set<string>();
    let current = infra.find(n => s.links(n.id, 'flow', 'in').length === 0) ?? null;
    let label: string | null = null;
    while (current && !seen.has(current.id)) {
      seen.add(current.id);
      trunk.push({ node: current, label });
      const next = s.links(current.id, 'flow', 'out');
      if (next.length !== 1) {
        for (const l of next) {
          const n = s.node(l.target);
          if (n && !seen.has(n.id)) { seen.add(n.id); branches.push({ node: n, label: l.label }); }
        }
        break;
      }
      label = next[0].label;
      current = s.node(next[0].target);
    }
    // Un nœud que la chaîne n'aurait pas atteint reste visible, sans flèche.
    for (const n of infra) if (!seen.has(n.id)) branches.push({ node: n, label: '' });
    return { trunk, branches };
  });

  rules = computed(() => this.store.ofKind('business_rule'));
}
