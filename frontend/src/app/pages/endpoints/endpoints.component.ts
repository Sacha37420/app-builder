import { afterNextRender, Component, computed, effect, inject, Injector } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BuilderStateService } from '../../core/builder-state.service';
import { urlSelection } from '../../core/url-selection';
import { compact, val, checked } from '../../core/form-utils';
import { BackLinkComponent } from '../../shared/back-link/back-link.component';
import {
  EndpointGroup, Endpoint, EndpointAuth, EndpointAuthMode, HttpMethod, OperationType,
  QueryParam, EndpointStep, EndpointStepType, FieldType,
} from '../../models/app-spec.model';

@Component({
  selector: 'app-endpoints-page',
  standalone: true,
  imports: [FormsModule, BackLinkComponent],
  templateUrl: './endpoints.component.html',
  styleUrl: './endpoints.component.scss',
})
export class EndpointsPageComponent {
  state = inject(BuilderStateService);
  private injector = inject(Injector);

  /** Groupe et endpoint ouverts, portés par l'adresse (`?groupe=<id>&endpoint=<id>`, contrat I6). */
  readonly groupSel = urlSelection('groupe', 'endpoint_groups');
  readonly epSel = urlSelection('endpoint', 'endpoints');

  readonly methods: HttpMethod[] = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];
  readonly operations: OperationType[] = ['list', 'create', 'retrieve', 'update', 'partial_update', 'delete', 'custom'];
  readonly stepTypes: EndpointStepType[] = [
    'auth_check', 'validate', 'db_query', 'db_write', 'serialize', 'transform',
    'enqueue_job', 'external_call', 'notify', 'error', 'custom',
  ];
  readonly stepTypeLabels: Record<EndpointStepType, string> = {
    auth_check: 'contrôle d\'accès', validate: 'validation', db_query: 'lecture base', db_write: 'écriture base',
    serialize: 'sérialisation', transform: 'transformation', enqueue_job: 'tâche de fond',
    external_call: 'appel externe', notify: 'notification', error: 'erreur', custom: 'autre',
  };
  readonly fieldTypes: FieldType[] = ['string', 'int', 'bool', 'decimal', 'date', 'datetime', 'text', 'email', 'url', 'enum'];

  /** Modes d'authentification (I1 `Endpoint.auth.mode`). */
  readonly authModes: { id: EndpointAuthMode; label: string }[] = [
    { id: 'jwt', label: 'Jeton de connexion (Keycloak)' },
    { id: 'public', label: 'Public (sans connexion)' },
    { id: 'api_key', label: 'Clé d\'API' },
    { id: 'hmac_signature', label: 'Signature HMAC (webhook)' },
    { id: 'internal_key', label: 'Clé interne (service du lab)' },
    { id: 'ticket', label: 'Ticket à usage court' },
  ];

  readonly operationLabels: Record<OperationType, string> = {
    list: 'list', create: 'create', retrieve: 'retrieve',
    update: 'update', partial_update: 'partial_update',
    delete: 'delete', custom: 'custom',
  };

  private readonly group = computed<EndpointGroup | undefined>(() => {
    const id = this.groupSel.id();
    return id !== null ? this.state.spec().endpoint_groups.find(g => g.id === id) : undefined;
  });
  get selectedGroup(): EndpointGroup | undefined { return this.group(); }

  /** Noms de rôles connus (I1 `roles`) proposés à la saisie. */
  readonly roleNames = computed(() => (this.state.spec().roles ?? []).map(r => r.name));

  constructor() {
    // Arrivée par un lien (inspecteur, adresse partagée) : l'endpoint ouvert est amené à l'écran.
    effect(() => {
      const id = this.epSel.id();
      if (id === null || !this.group()) return;
      afterNextRender(() => {
        const el = document.getElementById(`endpoint-${id}`);
        if (!el) return;
        const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        el.scrollIntoView({ block: 'start', behavior: reduced ? 'auto' : 'smooth' });
      }, { injector: this.injector });
    });
  }

  /** L'adresse désigne un groupe que la spec ne contient pas. */
  missingGroup(): boolean {
    return this.groupSel.id() !== null && !this.group();
  }

  /** L'adresse désigne un endpoint absent du groupe ouvert. */
  missingEndpoint(): boolean {
    const id = this.epSel.id();
    const g = this.group();
    return id !== null && !!g && !g.endpoints.some(e => e.id === id);
  }

  selectGroup(id: number): void {
    this.groupSel.set(id, { endpoint: null });
  }

  toggleEndpoint(id: number): void {
    this.epSel.set(this.epSel.id() === id ? null : id);
  }

  isExpanded(id: number): boolean { return this.epSel.id() === id; }

  val = val;
  checked = checked;

  // ── Groupe ───────────────────────────────────────────────────────────────────

  setGroupName(id: number, e: Event): void { this.state.updateEndpointGroup(id, { name: val(e) }); }
  setGroupDesc(id: number, e: Event): void { this.state.updateEndpointGroup(id, { description: val(e) }); }

  // ── Endpoint ─────────────────────────────────────────────────────────────────

  setMethod(gId: number, epId: number, e: Event): void {
    this.state.updateEndpoint(gId, epId, { method: val(e) as HttpMethod });
  }
  setPath(gId: number, epId: number, e: Event): void {
    this.state.updateEndpoint(gId, epId, { path: val(e) });
  }
  setDescription(gId: number, epId: number, e: Event): void {
    this.state.updateEndpoint(gId, epId, { description: val(e) });
  }
  setOperation(gId: number, epId: number, e: Event): void {
    this.state.updateEndpoint(gId, epId, { operation: val(e) as OperationType });
  }
  setLinkedModel(gId: number, epId: number, e: Event): void {
    this.state.updateEndpoint(gId, epId, { linked_model_name: val(e) });
  }
  // ── Authentification (I1 `auth`) ─────────────────────────────────────────────
  // Règle de cohérence du contrat, reproduite à la saisie pour que l'écran ne mente pas :
  // mode ≠ jwt ⇒ auth_required=false et public_reason = reason ; retour à jwt ⇒ auth {}
  // et auth_required=true ; auth_required=false sans auth ⇒ « public ».

  authMode(ep: Endpoint): EndpointAuthMode {
    return ep.auth?.mode ?? (ep.auth_required ? 'jwt' : 'public');
  }

  authLabel(ep: Endpoint): string {
    const m = this.authMode(ep);
    return m === 'public' ? 'public' : (this.authModes.find(x => x.id === m)?.label ?? m);
  }

  /** Justification affichée : `auth.reason`, sinon l'ancien `public_reason`. */
  authReason(ep: Endpoint): string {
    return ep.auth?.reason ?? ep.public_reason ?? '';
  }

  setAuthMode(gId: number, ep: Endpoint, e: Event): void {
    const mode = val(e) as EndpointAuthMode;
    if (mode === 'jwt') {
      // `updateEndpoint` vide aussi `public_reason`.
      this.state.updateEndpoint(gId, ep.id!, { auth: {}, auth_required: true });
      return;
    }
    const reason = this.authReason(ep);
    const auth: EndpointAuth = compact({ ...(ep.auth ?? {}), mode, reason: reason || undefined });
    this.state.updateEndpoint(gId, ep.id!, { auth, auth_required: false, public_reason: reason });
  }

  setAuthText(gId: number, ep: Endpoint, key: 'caller' | 'key_source' | 'reason', e: Event): void {
    const v = val(e);
    const auth: EndpointAuth = compact({
      ...(ep.auth ?? {}), mode: this.authMode(ep), [key]: v.trim() ? v : undefined,
    });
    const patch: Partial<Endpoint> = { auth, auth_required: false };
    if (key === 'reason') patch.public_reason = v;
    this.state.updateEndpoint(gId, ep.id!, patch);
  }

  // ── Rôles requis ─────────────────────────────────────────────────────────────

  addRole(gId: number, ep: Endpoint, role: string): void {
    const r = role.trim();
    if (!r || ep.required_roles.includes(r)) return;
    this.state.updateEndpoint(gId, ep.id!, { required_roles: [...ep.required_roles, r] });
  }

  removeRole(gId: number, ep: Endpoint, role: string): void {
    this.state.updateEndpoint(gId, ep.id!, { required_roles: ep.required_roles.filter(r => r !== role) });
  }

  onRoleKeydown(gId: number, ep: Endpoint, e: KeyboardEvent): void {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      const input = e.target as HTMLInputElement;
      this.addRole(gId, ep, input.value);
      input.value = '';
    }
  }

  // ── Query params ─────────────────────────────────────────────────────────────

  addQueryParam(gId: number, ep: Endpoint): void {
    const qp: QueryParam = { name: 'filtre', type: 'string', required: false, description: '' };
    this.state.updateEndpoint(gId, ep.id!, { query_params: [...ep.query_params, qp] });
  }

  updateQueryParam(gId: number, ep: Endpoint, idx: number, patch: Partial<QueryParam>): void {
    const qps = ep.query_params.map((q, i) => i === idx ? { ...q, ...patch } : q);
    this.state.updateEndpoint(gId, ep.id!, { query_params: qps });
  }
  setQueryParamType(gId: number, ep: Endpoint, idx: number, e: Event): void {
    this.updateQueryParam(gId, ep, idx, { type: val(e) as FieldType });
  }

  removeQueryParam(gId: number, ep: Endpoint, idx: number): void {
    this.state.updateEndpoint(gId, ep.id!, { query_params: ep.query_params.filter((_, i) => i !== idx) });
  }

  // ── Steps serveur ─────────────────────────────────────────────────────────────

  addStep(gId: number, ep: Endpoint): void {
    const step: EndpointStep = { label: 'Nouvelle étape', type: 'custom' };
    this.state.updateEndpoint(gId, ep.id!, { steps: [...(ep.steps ?? []), step] });
  }

  updateStep(gId: number, ep: Endpoint, idx: number, patch: Partial<EndpointStep>): void {
    const steps = (ep.steps ?? []).map((s, i) => i === idx ? { ...s, ...patch } : s);
    this.state.updateEndpoint(gId, ep.id!, { steps });
  }
  setStepType(gId: number, ep: Endpoint, idx: number, e: Event): void {
    this.updateStep(gId, ep, idx, { type: val(e) as EndpointStepType });
  }

  removeStep(gId: number, ep: Endpoint, idx: number): void {
    this.state.updateEndpoint(gId, ep.id!, { steps: (ep.steps ?? []).filter((_, i) => i !== idx) });
  }
}
