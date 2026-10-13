import { computed, inject, Injectable, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import {
  GraphLink, GraphLinkKind, GraphNode, GraphNodeKind, GraphScaleId, SpecGraph,
} from '../../models/app-spec.model';

/** Libellé et teinte (palette `--cat-*`) d'un genre de nœud : jamais la couleur seule. */
export interface KindMeta { label: string; cat: string; }

export const KINDS: Record<GraphNodeKind, KindMeta> = {
  groups:         { label: 'Accès',              cat: 'k-amber' },
  keycloak:       { label: 'Connexion',          cat: 'k-purple' },
  frontend:       { label: 'Interface',          cat: 'k-green' },
  api:            { label: 'API',                cat: 'k-blue' },
  database:       { label: 'Base de données',    cat: 'k-cyan' },
  storage:        { label: 'Fichiers',           cat: 'k-gray' },
  email:          { label: 'Email',              cat: 'k-gray' },
  business_rule:  { label: 'Règle métier',       cat: 'k-amber' },
  endpoint_group: { label: "Groupe d'endpoints", cat: 'k-blue' },
  endpoint:       { label: 'Route',              cat: 'k-blue' },
  service:        { label: 'Service',            cat: 'k-purple' },
  page:           { label: 'Page',               cat: 'k-green' },
  data_model:     { label: 'Modèle',             cat: 'k-cyan' },
  interaction:    { label: 'Interaction',        cat: 'k-amber' },
  pipeline:       { label: 'Pipeline',           cat: 'k-green' },
  step:           { label: 'Étape',              cat: 'k-gray' },
  lot:            { label: 'Lot',                cat: 'k-purple' },
};

/** Ce que compte `count` selon le genre (singulier, pluriel). */
const COUNT_WORDS: Partial<Record<GraphNodeKind, [string, string]>> = {
  groups:         ['groupe', 'groupes'],
  frontend:       ['page', 'pages'],
  api:            ['route', 'routes'],
  database:       ['modèle', 'modèles'],
  storage:        ['champ fichier', 'champs fichier'],
  endpoint_group: ['route', 'routes'],
  page:           ['pipeline', 'pipelines'],
  data_model:     ['champ', 'champs'],
  pipeline:       ['étape', 'étapes'],
};

export interface Crumb {
  label: string;
  scale: GraphScaleId;
  node: string | null;
  current: boolean;
}

interface Index {
  byId: Map<string, GraphNode>;
  dom: Map<string, string>;
  out: Map<string, GraphLink[]>;
  in: Map<string, GraphLink[]>;
}

/**
 * État partagé de la page « Vue d'ensemble » : le graphe reçu du serveur, et la
 * position courante (échelle + nœud en focus) lue dans l'URL — `?echelle=…&noeud=…` —
 * pour que le retour arrière du navigateur remonte d'un cran. Fourni par la page,
 * injecté par chaque échelle. Aucun calcul métier : seulement des index de lecture.
 */
@Injectable()
export class OverviewStore {
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  private params = toSignal(this.route.queryParamMap);

  readonly graph = signal<SpecGraph | null>(null);

  private index = computed<Index>(() => {
    const idx: Index = { byId: new Map(), dom: new Map(), out: new Map(), in: new Map() };
    const g = this.graph();
    if (!g) return idx;
    g.nodes.forEach((n, i) => { idx.byId.set(n.id, n); idx.dom.set(n.id, `ov-n-${i}`); });
    for (const l of g.links) {
      if (!idx.out.has(l.source)) idx.out.set(l.source, []);
      if (!idx.in.has(l.target)) idx.in.set(l.target, []);
      idx.out.get(l.source)!.push(l);
      idx.in.get(l.target)!.push(l);
    }
    return idx;
  });

  /** Échelle courante ; une valeur inconnue dans l'URL retombe sur la plus large. */
  readonly scale = computed<GraphScaleId>(() => {
    const e = this.params()?.get('echelle');
    return this.graph()?.scales.some(s => s.id === e) ? (e as GraphScaleId) : 'overview';
  });

  /** Nœud en focus (celui dans lequel on est entré, ou que l'on regarde). */
  readonly focus = computed<GraphNode | null>(() =>
    this.index().byId.get(this.params()?.get('noeud') ?? '') ?? null);

  /**
   * Quand le focus est un nœud d'une échelle plus large, l'échelle courante est
   * filtrée sur ce qui en descend. Sans objet pour « Dans le lab » (tout y est
   * racine) et pour la feuille de route (un lot ne descend de rien).
   */
  readonly filter = computed<GraphNode | null>(() => {
    const f = this.focus();
    const s = this.scale();
    return f && f.scale !== s && s !== 'overview' && s !== 'roadmap' ? f : null;
  });

  readonly crumbs = computed<Crumb[]>(() => {
    const f = this.focus();
    const s = this.scale();
    if (!f) return [{ label: this.scaleLabel(s), scale: s, node: null, current: true }];
    const chain = [...this.ancestors(f).reverse(), f];
    const elsewhere = f.scale !== s;
    const out: Crumb[] = [{ label: this.scaleLabel(chain[0].scale), scale: chain[0].scale, node: null, current: false }];
    chain.forEach((n, i) => out.push({
      label: n.label, scale: n.scale, node: n.id, current: !elsewhere && i === chain.length - 1,
    }));
    if (elsewhere) out.push({ label: this.scaleLabel(s), scale: s, node: f.id, current: true });
    return out;
  });

  readonly canUp = computed(() => {
    const f = this.focus();
    return !!f && (f.scale !== this.scale() || this.node(f.parent) !== null);
  });

  // ── Navigation (toujours par l'URL) ────────────────────────────────────────

  open(scale: GraphScaleId, node: string | null = null): void {
    this.router.navigate([], { relativeTo: this.route, queryParams: { echelle: scale, noeud: node } });
  }

  /** Va au nœud, dans sa propre échelle (défilé et mis en avant). */
  goNode(n: GraphNode): void { this.open(n.scale, n.id); }

  /** Entre dans le nœud : l'échelle qu'il ouvre, filtrée sur lui. */
  enter(n: GraphNode): void { this.open(n.opens ?? n.scale, n.id); }

  /** Remonte d'un cran : à l'échelle du nœud en focus, puis à son parent. */
  up(): void {
    const f = this.focus();
    if (!f) return;
    if (f.scale !== this.scale()) { this.goNode(f); return; }
    const p = this.node(f.parent);
    if (p) this.goNode(p);
  }

  // ── Lecture du graphe ──────────────────────────────────────────────────────

  node(id: string | null | undefined): GraphNode | null {
    return id ? this.index().byId.get(id) ?? null : null;
  }

  /** Ancêtres, du plus proche au plus lointain. */
  ancestors(n: GraphNode): GraphNode[] {
    const out: GraphNode[] = [];
    let p = this.node(n.parent);
    while (p && !out.includes(p) && p !== n) { out.push(p); p = this.node(p.parent); }
    return out;
  }

  descends(n: GraphNode, from: GraphNode): boolean { return this.ancestors(n).includes(from); }

  /** Vrai si le nœud passe le filtre courant. */
  visible(n: GraphNode): boolean {
    const f = this.filter();
    return !f || n.id === f.id || this.descends(n, f);
  }

  /** Nœuds d'un genre, dans l'ordre du serveur, filtre appliqué. */
  ofKind(kind: GraphNodeKind): GraphNode[] {
    return (this.graph()?.nodes ?? []).filter(n => n.kind === kind && this.visible(n));
  }

  children(id: string, kind: GraphNodeKind): GraphNode[] {
    return (this.graph()?.nodes ?? []).filter(n => n.parent === id && n.kind === kind);
  }

  links(id: string, kind: GraphLinkKind, dir: 'out' | 'in'): GraphLink[] {
    return (this.index()[dir].get(id) ?? []).filter(l => l.kind === kind);
  }

  /** Nœuds à l'autre bout des liens d'un genre. */
  linked(id: string, kind: GraphLinkKind, dir: 'out' | 'in'): GraphNode[] {
    return this.links(id, kind, dir)
      .map(l => this.node(dir === 'out' ? l.target : l.source))
      .filter((n): n is GraphNode => n !== null);
  }

  /** Les lots de la feuille de route qui construisent ce nœud. */
  lots(id: string): GraphNode[] { return this.linked(id, 'builds', 'in'); }

  // ── Affichage ──────────────────────────────────────────────────────────────

  domId(id: string): string { return this.index().dom.get(id) ?? ''; }

  isFocus(id: string): boolean { return this.focus()?.id === id; }

  kind(n: GraphNode): KindMeta { return KINDS[n.kind] ?? { label: n.kind, cat: 'k-gray' }; }

  scaleLabel(id: GraphScaleId): string {
    return this.graph()?.scales.find(s => s.id === id)?.label ?? id;
  }

  /** « 4 routes », ou '' quand le nœud ne compte rien. */
  countLabel(n: GraphNode): string {
    const words = COUNT_WORDS[n.kind];
    if (n.count === undefined || !words) return '';
    return `${this.n(n.count)} ${n.count > 1 ? words[1] : words[0]}`;
  }

  /** Nombre au format français (aucune locale Angular n'est enregistrée dans l'app). */
  n(value: number): string { return Math.round(value).toLocaleString('fr-FR'); }
}
