import { computed, inject, Injectable, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import {
  GraphLink, GraphLinkKind, GraphNode, GraphNodeKind, GraphScaleId, SpecGraph,
} from '../../models/app-spec.model';

/** Libellé et teinte (palette `--cat-*`) d'un genre de nœud : jamais la couleur seule. */
export interface KindMeta { label: string; cat: string; }

/** Repli client des genres (le serveur v2 les donne dans `kinds`, qui prime). */
export const KINDS: Record<string, KindMeta> = {
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
  role:           { label: 'Rôle',               cat: 'k-amber' },
  job:            { label: 'Tâche de fond',      cat: 'k-purple' },
  integration:    { label: 'Service du lab',     cat: 'k-gray' },
  external_api:   { label: 'API externe',        cat: 'k-gray' },
  state:          { label: 'État',               cat: 'k-cyan' },
  transition:     { label: 'Transition',         cat: 'k-cyan' },
};

/** Libellés des genres de lien, pour l'inspecteur (« lu par », « appelle »…). */
export const LINK_WORDS: Record<string, [string, string]> = {
  flow: ['mène à', 'vient de'], contains: ['contient', 'fait partie de'], uses: ['utilise', 'utilisé par'],
  calls: ['appelle', 'appelé par'], reads: ['lit', 'lu par'], relation: ['pointe vers', 'référencé par'],
  triggers: ['déclenche', 'déclenché par'], next: ['précède', 'suit'], invokes: ['invoque', 'invoqué par'],
  builds: ['construit', 'construit par'],
};

/** Ce que compte `count` selon le genre (singulier, pluriel). */
const COUNT_WORDS: Partial<Record<string, [string, string]>> = {
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
  /** `"<collection>#<id>"` (I6 `ref`) → nœud : le lien partagé survit à un renommage. */
  byRef: Map<string, GraphNode>;
  byKind: Map<string, GraphNode[]>;
  byParent: Map<string, GraphNode[]>;
  dom: Map<string, string>;
  domToId: Map<string, string>;
  out: Map<string, GraphLink[]>;
  in: Map<string, GraphLink[]>;
}

export type ViewMode = 'carte' | 'liste';

const FILTERED_SCALES: GraphScaleId[] = ['architecture', 'data', 'pipelines'];

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
    const idx: Index = {
      byId: new Map(), byRef: new Map(), byKind: new Map(), byParent: new Map(),
      dom: new Map(), domToId: new Map(), out: new Map(), in: new Map(),
    };
    const g = this.graph();
    if (!g) return idx;
    const push = <K, V>(m: Map<K, V[]>, k: K, v: V) => { const l = m.get(k); if (l) l.push(v); else m.set(k, [v]); };
    g.nodes.forEach((n, i) => {
      idx.byId.set(n.id, n);
      idx.dom.set(n.id, `ov-n-${i}`);
      idx.domToId.set(`ov-n-${i}`, n.id);
      if (n.ref && n.ref.id !== null && n.ref.id !== undefined) idx.byRef.set(`${n.ref.collection}#${n.ref.id}`, n);
      push(idx.byKind, n.kind, n);
      if (n.parent) push(idx.byParent, n.parent, n);
    });
    for (const l of g.links) {
      if (!idx.out.has(l.source)) idx.out.set(l.source, []);
      if (!idx.in.has(l.target)) idx.in.set(l.target, []);
      idx.out.get(l.source)!.push(l);
      idx.in.get(l.target)!.push(l);
    }
    return idx;
  });

  /**
   * Vue courante : `vue`, ou l'ancien `echelle` (liens existants) ; une valeur
   * inconnue retombe sur la plus large.
   */
  readonly scale = computed<GraphScaleId>(() => {
    const p = this.params();
    const e = p?.get('vue') ?? p?.get('echelle');
    return this.graph()?.scales.some(s => s.id === e) ? (e as GraphScaleId) : 'overview';
  });

  /**
   * Nœud sélectionné — la sélection unique, partagée par toutes les vues. `noeud`
   * accepte l'id du nœud et la référence stable `<collection>#<id>`.
   */
  readonly focus = computed<GraphNode | null>(() => {
    const raw = this.params()?.get('noeud') ?? '';
    const idx = this.index();
    return idx.byId.get(raw) ?? idx.byRef.get(raw) ?? null;
  });

  /** Curseur « l'app après le lot N » (`lot`) ; `null` = tous les lots. */
  readonly lotCursor = computed<number | null>(() => {
    const v = this.params()?.get('lot');
    return v && /^[0-9]{1,4}$/.test(v) ? Number(v) : null;
  });

  /** Numéros de lots connus (nœuds `lot`), dans l'ordre. */
  readonly lotNumbers = computed<number[]>(() =>
    (this.index().byKind.get('lot') ?? []).map(n => n.order ?? 0).sort((a, b) => a - b));

  /** `carte` (diagramme) ou `liste` ; par défaut liste sous 900 px. */
  readonly mode = computed<ViewMode>(() => {
    const m = this.params()?.get('mode');
    if (m === 'carte' || m === 'liste') return m;
    try { return window.matchMedia('(max-width: 899px)').matches ? 'liste' : 'carte'; } catch { return 'carte'; }
  });

  /** L'échelle courante telle que le serveur la décrit (notation, disponibilité). */
  readonly scaleInfo = computed(() => this.graph()?.scales.find(s => s.id === this.scale()) ?? null);

  /**
   * Quand le focus est un nœud d'une échelle plus large, l'échelle courante est
   * filtrée sur ce qui en descend. Sans objet pour « Dans le lab » (tout y est
   * racine) et pour la feuille de route (un lot ne descend de rien).
   */
  readonly filter = computed<GraphNode | null>(() => {
    const f = this.focus();
    const s = this.scale();
    // Seulement pour les échelles v1 qui descendent l'une de l'autre ; les vues v2
    // (API, sécurité…) montrent la sélection dans l'inspecteur sans rien masquer.
    return f && f.scale !== s && FILTERED_SCALES.includes(s) ? f : null;
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

  /** Change de vue (entrée d'historique) ; garde le curseur de lot et le mode. */
  open(scale: GraphScaleId, node: string | null = null): void {
    this.router.navigate([], {
      relativeTo: this.route, queryParamsHandling: 'merge',
      queryParams: { vue: scale, echelle: null, noeud: node },
    });
  }

  /** Sélectionne un nœud sans changer de vue ni empiler d'entrée (sinon « retour » devient inutilisable). */
  select(n: GraphNode | null): void {
    this.router.navigate([], {
      relativeTo: this.route, queryParamsHandling: 'merge', replaceUrl: true,
      queryParams: { noeud: n?.id ?? null },
    });
  }

  setParam(key: 'lot' | 'mode', value: string | number | null): void {
    this.router.navigate([], {
      relativeTo: this.route, queryParamsHandling: 'merge', replaceUrl: true, queryParams: { [key]: value },
    });
  }

  /** Adresse courante (pour le retour depuis une page d'édition). */
  currentUrl(): string { return this.router.url; }

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

  /** Nœud désigné par l'id d'un élément du DOM (`ov-n-<rang>`), pour la sélection au clic. */
  fromDom(domId: string): GraphNode | null { return this.node(this.index().domToId.get(domId)); }

  /** Premier nœud d'un genre portant ce libellé (lignes et colonnes des matrices). */
  byLabel(kind: string, label: string): GraphNode | null {
    return (this.index().byKind.get(kind) ?? []).find(n => n.label === label) ?? null;
  }

  /** Un identifiant de ligne/colonne rendu par le serveur : id de nœud, ou libellé d'un genre attendu. */
  resolve(key: string, kinds: string[] = []): GraphNode | null {
    const direct = this.node(key) ?? this.index().byRef.get(key) ?? null;
    if (direct) return direct;
    for (const k of kinds) { const n = this.byLabel(k, key); if (n) return n; }
    return null;
  }

  all(): GraphNode[] { return this.graph()?.nodes ?? []; }

  /** Construit après le lot du curseur : affiché en fantôme. */
  isGhost(n: GraphNode | null | undefined): boolean {
    const cur = this.lotCursor();
    if (cur === null || !n?.lots?.length) return false;
    return Math.min(...n.lots) > cur;
  }

  /** Les nœuds qui appartiennent à une vue : leur échelle, ou les vues où le serveur les projette. */
  inScale(n: GraphNode, scale: GraphScaleId): boolean {
    return n.scale === scale || (n.appears_in ?? []).includes(scale);
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
    return (this.index().byKind.get(kind) ?? []).filter(n => this.visible(n));
  }

  children(id: string, kind: GraphNodeKind): GraphNode[] {
    return (this.index().byParent.get(id) ?? []).filter(n => n.kind === kind);
  }

  /** Tous les liens d'un nœud, dans un sens. */
  allLinks(id: string, dir: 'out' | 'in'): GraphLink[] { return this.index()[dir].get(id) ?? []; }

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
  lots(id: string): GraphNode[] {
    const viaLinks = this.linked(id, 'builds', 'in');
    if (viaLinks.length) return viaLinks;
    const n = this.node(id);
    return (n?.lots ?? []).map(k => this.node(`lot:${k}`)).filter((x): x is GraphNode => x !== null);
  }

  // ── Affichage ──────────────────────────────────────────────────────────────

  domId(id: string): string { return this.index().dom.get(id) ?? ''; }

  isFocus(id: string): boolean { return this.focus()?.id === id; }

  kind(n: GraphNode): KindMeta {
    const server = this.graph()?.kinds?.[n.kind];
    if (server?.label) return { label: server.label, cat: /^k-[a-z]+$/.test(server.cat ?? '') ? server.cat : (KINDS[n.kind]?.cat ?? 'k-gray') };
    return KINDS[n.kind] ?? { label: n.kind, cat: 'k-gray' };
  }

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
