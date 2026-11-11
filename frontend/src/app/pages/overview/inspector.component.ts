import { Component, computed, inject, output } from '@angular/core';
import { Router } from '@angular/router';
import { GraphLink, GraphNode } from '../../models/app-spec.model';
import { LINK_WORDS, OverviewStore } from './overview.store';

interface NeighbourGroup { key: string; label: string; nodes: GraphNode[]; more: number; }

/** Au-delà, un groupe de voisins se résume (« +12 ») : le panneau reste lisible. */
const MAX_PER_GROUP = 15;

/** Libellés des attributs les plus courants ; les autres s'affichent sous leur clé. */
const ATTR_LABELS: Record<string, string> = {
  method: 'Méthode', path: 'Chemin', operation: 'Opération', auth: 'Authentification', model: 'Modèle',
  route: 'Route', layout: 'Mise en page', pk: 'Clé primaire', fk: 'Clés étrangères', required: 'Requis',
  storage_fields: 'Champs fichier', kind: 'Genre', scope: 'Portée', trigger: 'Déclencheur', type: 'Type',
  roles: 'Rôles', public: 'Public', reason: 'Justification', field: 'Champ', initial: 'État initial',
  from: 'De', to: 'Vers', by: 'Par', action: 'Route', mode: 'Mode',
};

/**
 * Inspecteur de la vue d'ensemble : le nœud sélectionné (paramètre `noeud`),
 * dans l'ordre de l'étude 02 §3.3 — genre et nom, défauts, attributs, lots,
 * voisins groupés par sorte de lien, « Voir dans… », « Modifier ». Aucune
 * édition ici : « Modifier » mène à la page d'édition, sélection comprise.
 */
@Component({
  selector: 'app-ov-inspector',
  standalone: true,
  templateUrl: './inspector.component.html',
  styleUrl: './inspector.component.scss',
})
export class InspectorComponent {
  store = inject(OverviewStore);
  private router = inject(Router);
  closed = output<void>();

  node = computed(() => this.store.focus());

  attrs = computed<{ key: string; label: string; value: string }[]>(() => {
    const a = this.node()?.attrs ?? {};
    return Object.entries(a)
      .filter(([, v]) => v !== null && v !== undefined && v !== '' && !(Array.isArray(v) && v.length === 0))
      .map(([key, v]) => ({ key, label: ATTR_LABELS[key] ?? key, value: this.show(v) }));
  });

  groups = computed<NeighbourGroup[]>(() => {
    const n = this.node();
    if (!n) return [];
    const out: NeighbourGroup[] = [];
    for (const dir of ['out', 'in'] as const) {
      const byKind = new Map<string, GraphLink[]>();
      for (const l of this.store.allLinks(n.id, dir)) {
        if (l.kind === 'builds') continue;          // les lots ont leur propre ligne
        const list = byKind.get(l.kind);
        if (list) list.push(l); else byKind.set(l.kind, [l]);
      }
      for (const [kind, links] of byKind) {
        const nodes = links
          .map(l => this.store.node(dir === 'out' ? l.target : l.source))
          .filter((x): x is GraphNode => x !== null);
        const words = LINK_WORDS[kind] ?? [kind, `← ${kind}`];
        out.push({ key: `${dir}:${kind}`, label: dir === 'out' ? words[0] : words[1],
                   nodes: nodes.slice(0, MAX_PER_GROUP), more: Math.max(0, nodes.length - MAX_PER_GROUP) });
      }
    }
    return out;
  });

  lotNumbers = computed<number[]>(() => {
    const n = this.node();
    if (!n) return [];
    if (n.lots?.length) return n.lots;
    return this.store.lots(n.id).map(l => l.order ?? 0);
  });

  views = computed(() => {
    const n = this.node();
    if (!n) return [];
    const ids = new Set([n.scale, ...(n.appears_in ?? [])]);
    return (this.store.graph()?.scales ?? []).filter(s => ids.has(s.id));
  });

  private show(v: unknown): string {
    if (typeof v === 'boolean') return v ? 'oui' : 'non';
    if (Array.isArray(v)) return v.map(x => (typeof x === 'object' ? JSON.stringify(x) : String(x))).join(', ');
    if (v && typeof v === 'object') {
      return Object.entries(v as Record<string, unknown>)
        .filter(([, x]) => x !== '' && x !== null && x !== undefined)
        .map(([k, x]) => `${k} : ${typeof x === 'object' ? JSON.stringify(x) : String(x)}`).join(' · ');
    }
    return String(v);
  }

  edit(): void {
    const e = this.node()?.edit;
    if (!e?.route?.startsWith('/')) return;
    this.router.navigate([e.route], { queryParams: { ...e.query, retour: this.store.currentUrl() } });
  }

  goLot(k: number): void {
    const lot = this.store.node(`lot:${k}`);
    if (lot) this.store.goNode(lot);
    else this.router.navigate(['/preview'], { queryParams: { lot: k } });
  }
}
