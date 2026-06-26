import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BuilderStateService } from '../../core/builder-state.service';
import {
  EndpointGroup, Endpoint, HttpMethod, OperationType,
  QueryParam, EndpointStep, EndpointStepType, FieldType,
} from '../../models/app-spec.model';
import { NavbarComponent } from '../../shared/navbar/navbar.component';

@Component({
  selector: 'app-endpoints-page',
  standalone: true,
  imports: [FormsModule, NavbarComponent],
  templateUrl: './endpoints.component.html',
  styleUrl: './endpoints.component.scss',
})
export class EndpointsPageComponent {
  state = inject(BuilderStateService);

  selectedGroupId = signal<number | null>(null);
  expandedEndpointId = signal<number | null>(null);

  readonly methods: HttpMethod[] = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];
  readonly operations: OperationType[] = ['list', 'create', 'retrieve', 'update', 'partial_update', 'delete', 'custom'];
  readonly stepTypes: EndpointStepType[] = ['auth_check', 'validate', 'db_query', 'db_write', 'serialize', 'transform', 'error', 'custom'];
  readonly fieldTypes: FieldType[] = ['string', 'int', 'bool', 'decimal', 'datetime', 'text'];

  readonly methodColors: Record<HttpMethod, string> = {
    GET: '#10b981', POST: '#3b82f6', PUT: '#f59e0b',
    PATCH: '#8b5cf6', DELETE: '#ef4444',
  };

  readonly operationLabels: Record<OperationType, string> = {
    list: 'list', create: 'create', retrieve: 'retrieve',
    update: 'update', partial_update: 'partial_update',
    delete: 'delete', custom: 'custom',
  };

  get selectedGroup(): EndpointGroup | undefined {
    const id = this.selectedGroupId();
    return id !== null ? this.state.spec().endpoint_groups.find(g => g.id === id) : undefined;
  }

  selectGroup(id: number): void {
    this.selectedGroupId.set(id);
    this.expandedEndpointId.set(null);
  }

  toggleEndpoint(id: number): void {
    this.expandedEndpointId.update(v => v === id ? null : id);
  }

  val(e: Event): string { return (e.target as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value; }
  checked(e: Event): boolean { return (e.target as HTMLInputElement).checked; }

  // ── Groupe ───────────────────────────────────────────────────────────────────

  setGroupName(id: number, e: Event): void { this.state.updateEndpointGroup(id, { name: this.val(e) }); }
  setGroupDesc(id: number, e: Event): void { this.state.updateEndpointGroup(id, { description: this.val(e) }); }

  // ── Endpoint ─────────────────────────────────────────────────────────────────

  setMethod(gId: number, epId: number, e: Event): void {
    this.state.updateEndpoint(gId, epId, { method: this.val(e) as HttpMethod });
  }
  setPath(gId: number, epId: number, e: Event): void {
    this.state.updateEndpoint(gId, epId, { path: this.val(e) });
  }
  setDescription(gId: number, epId: number, e: Event): void {
    this.state.updateEndpoint(gId, epId, { description: this.val(e) });
  }
  setOperation(gId: number, epId: number, e: Event): void {
    this.state.updateEndpoint(gId, epId, { operation: this.val(e) as OperationType });
  }
  setLinkedModel(gId: number, epId: number, e: Event): void {
    this.state.updateEndpoint(gId, epId, { linked_model_name: this.val(e) });
  }
  setAuthRequired(gId: number, epId: number, e: Event): void {
    this.state.updateEndpoint(gId, epId, { auth_required: this.checked(e) });
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
    this.updateQueryParam(gId, ep, idx, { type: this.val(e) as FieldType });
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
    this.updateStep(gId, ep, idx, { type: this.val(e) as EndpointStepType });
  }

  removeStep(gId: number, ep: Endpoint, idx: number): void {
    this.state.updateEndpoint(gId, ep.id!, { steps: (ep.steps ?? []).filter((_, i) => i !== idx) });
  }
}
