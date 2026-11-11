import { afterNextRender, Component, effect, inject, Injector } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BuilderStateService } from '../../core/builder-state.service';
import { urlSelection } from '../../core/url-selection';
import { BackLinkComponent } from '../../shared/back-link/back-link.component';
import { checked, csv, joinCsv, num, patchAt, removeAt, val, compact } from '../../core/form-utils';
import {
  AccessAction, AccessScope, DataModel, FieldType, ModelAccess, ModelConstraint, ModelField, ModelKind,
  ModelStates, RelType, StateTransition,
} from '../../models/app-spec.model';

@Component({
  selector: 'app-models-page',
  standalone: true,
  imports: [FormsModule, BackLinkComponent],
  templateUrl: './models.component.html',
  styleUrl: './models.component.scss',
})
export class ModelsPageComponent {
  state = inject(BuilderStateService);
  private injector = inject(Injector);

  /** Le modèle ouvert, porté par l'adresse (`?modele=<id>`, contrat I6). */
  readonly selection = urlSelection('modele', 'data_models');

  readonly fieldTypes: FieldType[] = [
    'string', 'text', 'int', 'decimal', 'bool', 'date', 'datetime', 'email', 'url', 'enum',
    'json', 'storage_file', 'secret', 'geo_point', 'geometry',
  ];
  // `file` n'est plus proposé : un champ qui le porte encore s'affiche avec un avertissement.
  readonly fieldTypeLabels: Partial<Record<FieldType, string>> = {
    storage_file: 'Fichier (service storage)', secret: 'Secret (chiffré)', enum: 'Liste de valeurs',
    geo_point: 'Point géographique', geometry: 'Géométrie (PostGIS)',
  };
  readonly relTypes: RelType[] = ['FK', 'M2M', 'O2O'];
  readonly onDeleteChoices = ['CASCADE', 'SET_NULL', 'PROTECT', 'DO_NOTHING'] as const;

  readonly kinds: { id: ModelKind; label: string }[] = [
    { id: 'entity', label: 'Entité (cas courant)' },
    { id: 'singleton', label: 'Singleton (une seule ligne : réglages)' },
    { id: 'reference', label: 'Référentiel (liste de valeurs administrée)' },
    { id: 'log', label: 'Journal (ajout seul)' },
    { id: 'join', label: 'Liaison entre deux modèles' },
  ];
  readonly scopes: { id: AccessScope; label: string }[] = [
    { id: 'owner', label: 'Propriétaire seul' },
    { id: 'shared', label: 'Propriétaire + partages nominatifs' },
    { id: 'group', label: 'Tout le groupe autorisé' },
    { id: 'parent', label: 'Suit la portée d\'un parent' },
    { id: 'public_read', label: 'Lecture publique (anonyme)' },
    { id: 'global', label: 'Global (tous les membres)' },
  ];
  readonly actions: AccessAction[] = ['read', 'create', 'update', 'delete', 'manage_shares'];
  readonly actionLabels: Record<AccessAction, string> = {
    read: 'lire', create: 'créer', update: 'modifier', delete: 'supprimer', manage_shares: 'gérer les partages',
  };

  readonly joinCsv = joinCsv;

  constructor() {
    // Arrivée par un lien (inspecteur, adresse partagée) : le modèle ouvert est amené à l'écran.
    effect(() => {
      const id = this.selection.id();
      if (id === null) return;
      afterNextRender(() => {
        const el = document.getElementById(`model-${id}`);
        if (!el) return;
        const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        el.scrollIntoView({ block: 'start', behavior: reduced ? 'auto' : 'smooth' });
      }, { injector: this.injector });
    });
  }

  /** L'adresse désigne un modèle que la spec ne contient pas (supprimé, ou autre spec). */
  missing(): boolean {
    const id = this.selection.id();
    return id !== null && !this.state.spec().data_models.some(m => m.id === id);
  }

  toggle(id: number): void {
    this.selection.set(this.selection.id() === id ? null : id);
  }

  isExpanded(id: number): boolean {
    return this.selection.id() === id;
  }

  djField(type: FieldType, maxLen?: number): string {
    const map: Record<FieldType, string> = {
      string:   `CharField(max_length=${maxLen ?? 200})`,
      text:     'TextField()',
      int:      'IntegerField()',
      decimal:  'DecimalField(max_digits=10, decimal_places=2)',
      bool:     'BooleanField(default=False)',
      date:     'DateField()',
      datetime: 'DateTimeField()',
      email:    'EmailField()',
      url:      'URLField()',
      enum:     'CharField(choices=…)',
      json:     'JSONField(default=dict)',
      secret:   'TextField()  # chiffré au coffre, jamais rendu par l\'API',
      geo_point: 'PointField()  # PostGIS',
      geometry: 'GeometryField()  # PostGIS',
      storage_file: 'CharField(max_length=500)  # chemin dans le service storage du lab',
      file:         'CharField(max_length=500)  # chemin dans le service storage du lab',
    };
    return `models.${map[type] ?? 'Field()'}`;
  }

  relLabel(rel: RelType): string {
    return { FK: 'ForeignKey', M2M: 'ManyToManyField', O2O: 'OneToOneField' }[rel];
  }

  val = val;
  checked = checked;

  setModelName(id: number, e: Event): void { this.state.updateDataModel(id, { name: val(e) }); }
  setModelDesc(id: number, e: Event): void { this.state.updateDataModel(id, { description: val(e) }); }
  setModelKind(id: number, e: Event): void { this.state.updateDataModel(id, { kind: val(e) as ModelKind }); }

  setFieldName(mId: number, idx: number, e: Event): void     { this.state.updateField(mId, idx, { name: val(e) }); }
  setFieldType(mId: number, idx: number, e: Event): void     { this.state.updateField(mId, idx, { type: val(e) as FieldType }); }
  setFieldRequired(mId: number, idx: number, e: Event): void { this.state.updateField(mId, idx, { required: checked(e) }); }
  setFieldUnique(mId: number, idx: number, e: Event): void   { this.state.updateField(mId, idx, { unique: checked(e) }); }
  setFieldMaxLen(mId: number, idx: number, e: Event): void   { this.state.updateField(mId, idx, { max_length: +val(e) }); }
  setFieldDefault(mId: number, idx: number, e: Event): void  { this.state.updateField(mId, idx, { default: val(e) || undefined }); }

  /** Attribut facultatif d'un champ (I1) : une valeur vide retire la clé. */
  setFieldAttr(mId: number, idx: number, key: keyof ModelField, value: unknown): void {
    const empty = value === '' || value === undefined || (Array.isArray(value) && value.length === 0);
    this.state.updateField(mId, idx, { [key]: empty ? undefined : value } as Partial<ModelField>);
  }
  fieldNum(mId: number, idx: number, key: keyof ModelField, e: Event): void { this.setFieldAttr(mId, idx, key, num(e)); }
  fieldText(mId: number, idx: number, key: keyof ModelField, e: Event): void { this.setFieldAttr(mId, idx, key, val(e).trim()); }
  fieldCsv(mId: number, idx: number, key: keyof ModelField, e: Event): void { this.setFieldAttr(mId, idx, key, csv(val(e))); }
  fieldBool(mId: number, idx: number, key: keyof ModelField, e: Event): void { this.setFieldAttr(mId, idx, key, checked(e) || undefined); }

  setRelName(mId: number, idx: number, e: Event): void        { this.state.updateRelationship(mId, idx, { name: val(e) }); }
  setRelType(mId: number, idx: number, e: Event): void        { this.state.updateRelationship(mId, idx, { rel_type: val(e) as RelType }); }
  setRelToModel(mId: number, idx: number, e: Event): void     { this.state.updateRelationship(mId, idx, { to_model: val(e) }); }
  setRelRelatedName(mId: number, idx: number, e: Event): void { this.state.updateRelationship(mId, idx, { related_name: val(e) }); }
  setRelOnDelete(mId: number, idx: number, e: Event): void    { this.state.updateRelationship(mId, idx, { on_delete: val(e) as any }); }

  // ── Accès (I1 `access`) ─────────────────────────────────────────────────────

  access(m: DataModel): ModelAccess { return m.access ?? {}; }

  setAccess(m: DataModel, patch: Partial<ModelAccess>): void {
    this.state.updateDataModel(m.id!, { access: compact({ ...this.access(m), ...patch }) });
  }
  accessText(m: DataModel, key: 'owner_field' | 'parent' | 'share_model' | 'public_flag' | 'reason', e: Event): void {
    this.setAccess(m, { [key]: val(e).trim() || undefined });
  }
  setScope(m: DataModel, e: Event): void {
    const scope = (val(e) || undefined) as AccessScope | undefined;
    this.setAccess(m, { scope });
  }
  addAccessRule(m: DataModel): void {
    this.setAccess(m, { rules: [...(this.access(m).rules ?? []), { action: 'read', who: ['owner'] }] });
  }
  setRuleAction(m: DataModel, idx: number, e: Event): void {
    this.setAccess(m, { rules: patchAt(this.access(m).rules ?? [], idx, { action: val(e) as AccessAction }) });
  }
  setRuleWho(m: DataModel, idx: number, e: Event): void {
    this.setAccess(m, { rules: patchAt(this.access(m).rules ?? [], idx, { who: csv(val(e)) }) });
  }
  removeAccessRule(m: DataModel, idx: number): void {
    this.setAccess(m, { rules: removeAt(this.access(m).rules ?? [], idx) });
  }
  addHidden(m: DataModel): void {
    this.setAccess(m, { hidden_fields: [...(this.access(m).hidden_fields ?? []), { field: m.fields[0]?.name ?? '', unless: 'owner' }] });
  }
  setHidden(m: DataModel, idx: number, key: 'field' | 'unless', e: Event): void {
    this.setAccess(m, { hidden_fields: patchAt(this.access(m).hidden_fields ?? [], idx, { [key]: val(e).trim() }) });
  }
  removeHidden(m: DataModel, idx: number): void {
    this.setAccess(m, { hidden_fields: removeAt(this.access(m).hidden_fields ?? [], idx) });
  }

  boolFields(m: DataModel): string[] { return m.fields.filter(f => f.type === 'bool').map(f => f.name); }
  relationNames(m: DataModel): string[] { return m.relationships.filter(r => r.rel_type !== 'M2M').map(r => r.name); }

  // ── États (I1 `states`) ─────────────────────────────────────────────────────

  states(m: DataModel): ModelStates { return m.states ?? {}; }
  hasStates(m: DataModel): boolean { return Object.keys(this.states(m)).length > 0; }

  setStates(m: DataModel, patch: Partial<ModelStates>): void {
    this.state.updateDataModel(m.id!, { states: compact({ ...this.states(m), ...patch }) });
  }
  startStates(m: DataModel): void {
    const field = m.fields.find(f => /statu|state|etat/i.test(f.name))?.name ?? 'statut';
    this.setStates(m, { field, initial: 'brouillon', values: ['brouillon'], transitions: [] });
  }
  clearStates(m: DataModel): void {
    if (!confirm(`Retirer le cycle de vie de ${m.name} ?`)) return;
    this.state.updateDataModel(m.id!, { states: {} });
  }
  statesText(m: DataModel, key: 'field' | 'initial', e: Event): void { this.setStates(m, { [key]: val(e).trim() || undefined }); }
  statesCsv(m: DataModel, key: 'values' | 'frozen_in', e: Event): void { this.setStates(m, { [key]: csv(val(e)) }); }
  addTransition(m: DataModel): void {
    const values = this.states(m).values ?? [];
    const t: StateTransition = { from: values[0] ? [values[0]] : [], to: values[1] ?? '', by: ['owner'] };
    this.setStates(m, { transitions: [...(this.states(m).transitions ?? []), t] });
  }
  transCsv(m: DataModel, idx: number, key: 'from' | 'by' | 'side_effects', e: Event): void {
    this.setStates(m, { transitions: patchAt(this.states(m).transitions ?? [], idx, { [key]: csv(val(e)) }) });
  }
  transText(m: DataModel, idx: number, key: 'to' | 'action', e: Event): void {
    this.setStates(m, { transitions: patchAt(this.states(m).transitions ?? [], idx, { [key]: val(e).trim() }) });
  }
  removeTransition(m: DataModel, idx: number): void {
    this.setStates(m, { transitions: removeAt(this.states(m).transitions ?? [], idx) });
  }

  // ── Contraintes (I1 `constraints`) ──────────────────────────────────────────

  addConstraint(m: DataModel): void {
    const c: ModelConstraint = { kind: 'unique', fields: [] };
    this.state.updateDataModel(m.id!, { constraints: [...(m.constraints ?? []), c] });
  }
  setConstraint(m: DataModel, idx: number, patch: Partial<ModelConstraint>): void {
    this.state.updateDataModel(m.id!, { constraints: patchAt(m.constraints ?? [], idx, patch) });
  }
  constraintKind(m: DataModel, idx: number, e: Event): void { this.setConstraint(m, idx, { kind: val(e) as ModelConstraint['kind'] }); }
  constraintText(m: DataModel, idx: number, key: 'name' | 'condition', e: Event): void { this.setConstraint(m, idx, { [key]: val(e).trim() }); }
  constraintFields(m: DataModel, idx: number, e: Event): void { this.setConstraint(m, idx, { fields: csv(val(e)) }); }
  removeConstraint(m: DataModel, idx: number): void {
    this.state.updateDataModel(m.id!, { constraints: removeAt(m.constraints ?? [], idx) });
  }
}
