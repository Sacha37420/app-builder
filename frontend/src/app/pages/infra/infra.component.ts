import { afterNextRender, Component, computed, effect, inject, Injector, signal, untracked } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { BuilderStateService } from '../../core/builder-state.service';
import { checked, csv, joinCsv, patchAt, removeAt, val } from '../../core/form-utils';
import { BackLinkComponent } from '../../shared/back-link/back-link.component';
import { LabPanelComponent } from './lab-panel.component';
import {
  AppExtensions, AppIntegration, AppJob, AppRole, BusinessRule, DataModel, ExternalApi,
  FieldType, IntegrationType, ModelField,
} from '../../models/app-spec.model';

const SQL_TYPE: Record<FieldType, (f: ModelField) => string> = {
  string:   f => `VARCHAR(${f.max_length ?? 200})`,
  text:     _ => 'TEXT',
  int:      _ => 'INTEGER',
  decimal:  _ => 'DECIMAL(10, 2)',
  bool:     _ => 'BOOLEAN',
  date:     _ => 'DATE',
  datetime: _ => 'TIMESTAMPTZ',
  email:    _ => 'VARCHAR(254)',
  url:      _ => 'VARCHAR(254)',
  enum:     _ => 'VARCHAR(50)',
  json:     _ => 'JSONB',
  // Secret : chiffré au coffre de l'app, jamais rendu par l'API.
  secret:   _ => 'TEXT',
  geo_point: _ => 'geometry(Point)',
  geometry: _ => 'geometry',
  // Fichier d'utilisateur : la colonne ne garde que le chemin dans le service storage.
  storage_file: _ => 'VARCHAR(500)',
  file:         _ => 'VARCHAR(500)',
};

export interface SqlColumn {
  name: string;
  sqlType: string;
  nullable: boolean;
  unique: boolean;
  default?: string;
  comment?: string;
}

export interface SqlTable {
  tableName: string;
  modelName: string;
  description: string;
  columns: SqlColumn[];
  fkConstraints: string[];
  m2mTables: { name: string; ddl: string }[];
}

function toSnake(s: string): string {
  return s.replace(/([A-Z])/g, m => `_${m.toLowerCase()}`).replace(/^_/, '');
}

function buildTable(model: DataModel, allModels: DataModel[]): SqlTable {
  const tableName = toSnake(model.name);
  const columns: SqlColumn[] = [
    { name: 'id', sqlType: 'SERIAL', nullable: false, unique: true, comment: 'Clé primaire' },
  ];
  const fkConstraints: string[] = [];
  const m2mTables: { name: string; ddl: string }[] = [];

  for (const f of model.fields) {
    columns.push({
      name: f.name,
      sqlType: (SQL_TYPE[f.type] ?? (() => 'TEXT'))(f),
      nullable: !f.required,
      unique: f.unique,
      default: f.default,
    });
  }

  for (const rel of model.relationships) {
    const targetTable = toSnake(rel.to_model);
    const onDel = rel.on_delete ?? 'CASCADE';

    if (rel.rel_type === 'FK') {
      const colName = `${rel.name}_id`;
      columns.push({ name: colName, sqlType: 'INTEGER', nullable: true, unique: false, comment: `FK → ${rel.to_model}` });
      fkConstraints.push(
        `CONSTRAINT fk_${tableName}_${rel.name} FOREIGN KEY (${colName}) REFERENCES ${targetTable}(id) ON DELETE ${onDel}`
      );
    } else if (rel.rel_type === 'O2O') {
      const colName = `${rel.name}_id`;
      columns.push({ name: colName, sqlType: 'INTEGER', nullable: true, unique: true, comment: `O2O → ${rel.to_model}` });
      fkConstraints.push(
        `CONSTRAINT fk_${tableName}_${rel.name} FOREIGN KEY (${colName}) REFERENCES ${targetTable}(id) ON DELETE ${onDel}`
      );
    } else if (rel.rel_type === 'M2M') {
      const junctionName = `${tableName}_${targetTable}`;
      m2mTables.push({
        name: junctionName,
        ddl: [
          `CREATE TABLE ${junctionName} (`,
          `  ${tableName}_id INTEGER NOT NULL REFERENCES ${tableName}(id) ON DELETE CASCADE,`,
          `  ${targetTable}_id INTEGER NOT NULL REFERENCES ${targetTable}(id) ON DELETE CASCADE,`,
          `  PRIMARY KEY (${tableName}_id, ${targetTable}_id)`,
          `);`,
        ].join('\n'),
      });
    }
  }

  return { tableName, modelName: model.name, description: model.description, columns, fkConstraints, m2mTables };
}

/** Sections de la page (contrat I6 : `/infra?section=…`). */
export type InfraSection = 'meta' | 'rules' | 'roles' | 'jobs' | 'integrations' | 'external_apis' | 'extensions';

const SECTIONS: { id: InfraSection; label: string }[] = [
  { id: 'meta', label: 'Fiche du lab' },
  { id: 'rules', label: 'Règles métier' },
  { id: 'roles', label: 'Rôles' },
  { id: 'jobs', label: 'Tâches de fond' },
  { id: 'integrations', label: 'Services du lab' },
  { id: 'external_apis', label: 'API externes' },
  { id: 'extensions', label: 'Extensions' },
];

/** Listes de la spec (I1) éditées ici, avec leur setter dans l'état. */
interface SpecLists {
  roles: AppRole[];
  jobs: AppJob[];
  integrations: AppIntegration[];
  external_apis: ExternalApi[];
}
type ListKey = keyof SpecLists;
type ExtKey = keyof AppExtensions;

@Component({
  selector: 'app-infra-page',
  standalone: true,
  imports: [LabPanelComponent, BackLinkComponent],
  templateUrl: './infra.component.html',
  styleUrl: './infra.component.scss',
})
export class InfraPageComponent {
  state = inject(BuilderStateService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private injector = inject(Injector);
  private params = toSignal(this.route.queryParamMap);

  readonly sections = SECTIONS;

  /** Section demandée par l'adresse ; `null` = page d'origine (fiche du lab + schéma SQL). */
  readonly section = computed<InfraSection | null>(() => {
    const s = this.params()?.get('section') ?? '';
    return SECTIONS.some(x => x.id === s) ? (s as InfraSection) : null;
  });
  /** Une valeur de `section` inconnue (lien ancien, faute de frappe). */
  readonly unknownSection = computed(() => {
    const s = this.params()?.get('section');
    return !!s && this.section() === null;
  });
  readonly current = computed<InfraSection>(() => this.section() ?? 'meta');

  readonly joinCsv = joinCsv;
  val = val;

  // ── Choix proposés ──────────────────────────────────────────────────────────
  readonly roleKinds = [
    { id: 'keycloak_group', label: 'Groupe Keycloak' },
    { id: 'object_role', label: 'Rôle sur un objet' },
  ] as const;
  readonly jobKinds = [
    { id: 'async', label: 'Asynchrone (lancée par une action)' },
    { id: 'scheduled', label: 'Planifiée' },
    { id: 'command', label: 'Commande manuelle' },
  ] as const;
  readonly integrationTypes: { id: IntegrationType; label: string }[] = [
    { id: 'storage', label: 'Fichiers (storage)' },
    { id: 'email', label: 'Envoi d\'email' },
    { id: 'keycloak_admin', label: 'Administration Keycloak' },
    { id: 'lab_media', label: 'Flux audio/vidéo (lab-media)' },
    { id: 'postgis', label: 'Données géographiques (PostGIS)' },
    { id: 'oauth_hub', label: 'Comptes externes (oauth-hub)' },
  ];
  readonly storageModes = [
    { id: 'user_token', label: 'Jeton de l\'utilisateur transmis' },
    { id: 'service_account', label: 'Compte de service de l\'app' },
    { id: 'per_object_share', label: 'Un partage par objet' },
    { id: 'public_republish', label: 'Republication publique par l\'app' },
  ];
  readonly apiAuths = [
    { id: 'none', label: 'Aucune' },
    { id: 'app_key', label: 'Clé de l\'app' },
    { id: 'user_key', label: 'Clé de l\'utilisateur' },
    { id: 'oauth_hub', label: 'Jeton via oauth-hub' },
  ] as const;
  readonly ruleKinds = [
    { id: 'invariant', label: 'Invariant' },
    { id: 'validation', label: 'Validation' },
    { id: 'side_effect', label: 'Effet de bord' },
    { id: 'access', label: 'Accès' },
  ] as const;

  readonly modelNames = computed(() => this.state.spec().data_models.map(m => m.name));
  readonly endpointRefs = computed(() =>
    this.state.spec().endpoint_groups.flatMap(g => g.endpoints.map(e => `${e.method} ${e.path}`)));
  readonly roleNames = computed(() => (this.state.spec().roles ?? []).map(r => r.name));

  /** Index des règles métier dont le titre saisi est vide (le serveur le refuserait). */
  readonly emptyRuleTitles = signal<ReadonlySet<number>>(new Set());

  constructor() {
    effect(() => {
      this.state.specSessionId();
      this.emptyRuleTitles.set(new Set());
    });
    // Section demandée par un lien : amenée à l'écran.
    effect(() => {
      const s = this.section();
      if (s === null) return;
      afterNextRender(() => {
        const el = document.getElementById(`infra-section-${s}`);
        if (!el) return;
        const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        el.scrollIntoView({ block: 'start', behavior: reduced ? 'auto' : 'smooth' });
      }, { injector: this.injector });
    });
  }

  /** Nombre d'éléments d'une section, affiché dans le sommaire (0 = rien). */
  countOf(id: InfraSection): number {
    const spec = this.state.spec();
    switch (id) {
      case 'meta': return 0;
      case 'rules': return spec.business_rules.length;
      case 'extensions': {
        const e = spec.extensions ?? {};
        return (e.data_io?.length ?? 0) + (e.realtime?.length ?? 0)
          + (e.computations?.length ?? 0) + (e.notifications?.length ?? 0);
      }
      default: return (spec[id] ?? []).length;
    }
  }

  goSection(id: InfraSection): void {
    untracked(() => this.router.navigate([], {
      relativeTo: this.route, queryParams: { section: id }, queryParamsHandling: 'merge', replaceUrl: true,
    }));
  }

  // ── Règles métier (I1 `business_rules`) ──────────────────────────────────────

  setRuleTitle(idx: number, e: Event): void {
    const title = val(e);
    const empty = new Set(this.emptyRuleTitles());
    if (title.trim() === '') {
      empty.add(idx);               // titre obligatoire : on n'envoie pas un titre vide
    } else {
      empty.delete(idx);
      this.state.updateBusinessRule(idx, { title });
    }
    this.emptyRuleTitles.set(empty);
  }
  setRuleDescription(idx: number, e: Event): void {
    this.state.updateBusinessRule(idx, { description: val(e) });
  }
  setRuleText(idx: number, key: 'applies_to', e: Event): void {
    this.state.updateBusinessRule(idx, { [key]: val(e).trim() || undefined });
  }
  setRuleKind(idx: number, e: Event): void {
    this.state.updateBusinessRule(idx, { kind: (val(e) || undefined) as BusinessRule['kind'] });
  }
  setRuleEnforcedBy(idx: number, e: Event): void {
    const list = csv(val(e));
    this.state.updateBusinessRule(idx, { enforced_by: list.length ? list : undefined });
  }
  removeRule(idx: number): void {
    this.state.removeBusinessRule(idx);
    this.emptyRuleTitles.set(new Set());   // les index ont glissé
  }

  // ── Listes de la spec (rôles, tâches, intégrations, API externes) ────────────

  list<K extends ListKey>(k: K): SpecLists[K] {
    return (this.state.spec()[k] ?? []) as SpecLists[K];
  }

  private setList<K extends ListKey>(k: K, items: SpecLists[K]): void {
    switch (k) {
      case 'roles': this.state.setRoles(items as AppRole[]); break;
      case 'jobs': this.state.setJobs(items as AppJob[]); break;
      case 'integrations': this.state.setIntegrations(items as AppIntegration[]); break;
      case 'external_apis': this.state.setExternalApis(items as ExternalApi[]); break;
    }
  }

  private readonly blanks: { [K in ListKey]: () => SpecLists[K][number] } = {
    roles: () => ({ name: 'nouveau-role', kind: 'keycloak_group' }),
    jobs: () => ({ name: 'NouvelleTache', kind: 'async', heavy: false }),
    integrations: () => ({ type: 'storage', mode: 'user_token' }),
    external_apis: () => ({ name: 'NouvelleApi', auth: 'none', called_from: 'backend' }),
  };

  addItem(k: ListKey): void {
    this.setList(k, [...this.list(k), this.blanks[k]()] as SpecLists[typeof k]);
  }
  removeItem(k: ListKey, idx: number): void {
    this.setList(k, removeAt(this.list(k) as object[], idx) as SpecLists[typeof k]);
  }
  /** Modifie une clé d'un élément ; une valeur vide retire la clé (`patchAt`). */
  patchItem(k: ListKey, idx: number, key: string, value: unknown): void {
    this.setList(k, patchAt(this.list(k) as object[], idx, { [key]: value }) as SpecLists[typeof k]);
  }
  itemText(k: ListKey, idx: number, key: string, e: Event): void { this.patchItem(k, idx, key, val(e).trim() || undefined); }
  itemCsv(k: ListKey, idx: number, key: string, e: Event): void { this.patchItem(k, idx, key, csv(val(e))); }
  itemBool(k: ListKey, idx: number, key: string, e: Event): void { this.patchItem(k, idx, key, checked(e)); }

  /** Une intégration qui change de type perd un mode qui ne vaut que pour storage. */
  setIntegrationType(idx: number, e: Event): void {
    const type = val(e) as IntegrationType;
    const cur = this.list('integrations')[idx];
    const storageMode = this.storageModes.some(m => m.id === cur?.mode);
    const mode = type === 'storage'
      ? (storageMode ? cur?.mode : 'user_token')
      : (storageMode ? undefined : cur?.mode);
    this.setList('integrations', patchAt(this.list('integrations'), idx, { type, mode }));
  }

  /** Un rôle qui n'est plus « sur un objet » perd `on_model`. */
  setRoleKind(idx: number, e: Event): void {
    const kind = val(e) as AppRole['kind'];
    const patch: Partial<AppRole> = { kind };
    if (kind !== 'object_role') patch.on_model = undefined;
    this.setList('roles', patchAt(this.list('roles'), idx, patch));
  }

  // ── Extensions (I1 `extensions`) ─────────────────────────────────────────────

  ext<K extends ExtKey>(k: K): NonNullable<AppExtensions[K]> {
    return (this.state.spec().extensions?.[k] ?? []) as NonNullable<AppExtensions[K]>;
  }
  private setExt(k: ExtKey, items: object[]): void {
    const next: Record<string, unknown> = { ...(this.state.spec().extensions ?? {}) };
    if (items.length) next[k] = items; else delete next[k];
    this.state.setExtensions(next as AppExtensions);
  }
  private readonly extBlanks: Record<ExtKey, () => object> = {
    data_io: () => ({ direction: 'import', format: 'csv', model: this.modelNames()[0] ?? '', mode: 'append', async: false }),
    realtime: () => ({ name: 'nouveau-flux', transport: 'poll' }),
    computations: () => ({ name: 'nouveau-calcul', run: 'sync' }),
    notifications: () => ({ event: '', channel: 'email', to: 'owner' }),
  };
  addExt(k: ExtKey): void { this.setExt(k, [...this.ext(k), this.extBlanks[k]()]); }
  removeExt(k: ExtKey, idx: number): void { this.setExt(k, removeAt(this.ext(k) as object[], idx)); }
  patchExt(k: ExtKey, idx: number, key: string, value: unknown): void {
    this.setExt(k, patchAt(this.ext(k) as object[], idx, { [key]: value }));
  }
  extText(k: ExtKey, idx: number, key: string, e: Event): void { this.patchExt(k, idx, key, val(e).trim() || undefined); }
  extCsv(k: ExtKey, idx: number, key: string, e: Event): void { this.patchExt(k, idx, key, csv(val(e))); }
  extBool(k: ExtKey, idx: number, key: string, e: Event): void { this.patchExt(k, idx, key, checked(e)); }

  // ── Schéma SQL ──────────────────────────────────────────────────────────────

  tables = computed<SqlTable[]>(() => {
    const models = this.state.spec().data_models;
    return models.map(m => buildTable(m, models));
  });

  ddlFor(table: SqlTable): string {
    const lines: string[] = [`CREATE TABLE ${table.tableName} (`];
    table.columns.forEach((col, i) => {
      const isLast = i === table.columns.length - 1 && table.fkConstraints.length === 0;
      const nullable = col.name === 'id' ? ' PRIMARY KEY' : (col.nullable ? '' : ' NOT NULL');
      const unique   = col.unique && col.name !== 'id' ? ' UNIQUE' : '';
      const def      = col.default ? ` DEFAULT '${col.default}'` : '';
      lines.push(`  ${col.name} ${col.sqlType}${nullable}${unique}${def}${isLast ? '' : ','}`);
    });
    table.fkConstraints.forEach((fk, i) => {
      const isLast = i === table.fkConstraints.length - 1;
      lines.push(`  ${fk}${isLast ? '' : ','}`);
    });
    lines.push(');');
    return lines.join('\n');
  }

  allDdl(): string {
    const parts: string[] = [];
    for (const t of this.tables()) {
      parts.push(this.ddlFor(t));
      for (const m2m of t.m2mTables) {
        parts.push(m2m.ddl);
      }
    }
    return parts.join('\n\n');
  }

  toSnake(s: string): string { return toSnake(s.trim()); }

  copyDdl(): void {
    navigator.clipboard.writeText(this.allDdl());
  }
}
