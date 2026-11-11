import { afterNextRender, Component, computed, effect, inject, Injector } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BuilderStateService } from '../../core/builder-state.service';
import { urlSelection } from '../../core/url-selection';
import { val } from '../../core/form-utils';
import { BackLinkComponent } from '../../shared/back-link/back-link.component';
import { Page, Pipeline, PipelineStep, PipelineStepType } from '../../models/app-spec.model';

@Component({
  selector: 'app-pipelines-page',
  standalone: true,
  imports: [FormsModule, BackLinkComponent],
  templateUrl: './pipelines.component.html',
  styleUrl: './pipelines.component.scss',
})
export class PipelinesPageComponent {
  state = inject(BuilderStateService);
  private injector = inject(Injector);

  /** Page et pipeline ouverts, portés par l'adresse (`?page=<id>&pipeline=<id>`, contrat I6). */
  readonly pageSel = urlSelection('page', 'pages');
  readonly pipeSel = urlSelection('pipeline', 'pipelines');

  readonly stepTypes: PipelineStepType[] = [
    'trigger', 'service_call', 'transform', 'state_update', 'navigate',
    'enqueue_job', 'poll_job', 'client_compute', 'error',
  ];

  readonly stepTypeLabels: Record<PipelineStepType, string> = {
    trigger:      'Déclencheur',
    service_call: 'Appel service',
    transform:    'Transformation',
    state_update: 'Mise à jour état',
    navigate:     'Navigation',
    enqueue_job:  'Lancer une tâche',
    poll_job:     'Suivre une tâche',
    client_compute: 'Calcul navigateur',
    error:        'Erreur',
  };

  readonly stepTypeIcons: Record<PipelineStepType, string> = {
    trigger:      '⚡',
    service_call: '🔌',
    transform:    '⚙',
    state_update: '📦',
    navigate:     '→',
    enqueue_job:  '⏵',
    poll_job:     '⟳',
    client_compute: '∑',
    error:        '⚠',
  };

  private readonly page = computed<Page | undefined>(() => {
    const id = this.pageSel.id();
    return id !== null ? this.state.spec().pages.find(p => p.id === id) : undefined;
  });
  get selectedPage(): Page | undefined { return this.page(); }

  constructor() {
    // Arrivée par un lien : le pipeline désigné est amené à l'écran.
    effect(() => {
      const id = this.pipeSel.id();
      if (id === null || !this.page()) return;
      afterNextRender(() => {
        const el = document.getElementById(`pipeline-${id}`);
        if (!el) return;
        const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        el.scrollIntoView({ block: 'start', behavior: reduced ? 'auto' : 'smooth' });
      }, { injector: this.injector });
    });
  }

  /** L'adresse désigne une page que la spec ne contient pas. */
  missingPage(): boolean { return this.pageSel.id() !== null && !this.page(); }

  /** L'adresse désigne un pipeline absent de la page ouverte. */
  missingPipeline(): boolean {
    const id = this.pipeSel.id();
    const p = this.page();
    return id !== null && !!p && !p.pipelines.some(pl => pl.id === id);
  }

  selectPage(id: number): void {
    this.pageSel.set(id, { pipeline: null });
  }

  togglePipeline(id: number): void {
    this.pipeSel.set(this.pipeSel.id() === id ? null : id);
  }

  isExpanded(id: number): boolean { return this.pipeSel.id() === id; }

  totalSteps(pipeline: Pipeline): number {
    return pipeline.steps.length;
  }

  stepClass(type: PipelineStepType): string {
    return `step-block step-${type.replaceAll('_', '-')}`;
  }

  val = val;

  setPipelineName(pageId: number, pipeId: number, e: Event): void {
    this.state.updatePipeline(pageId, pipeId, { name: val(e) });
  }
  setPipelineDesc(pageId: number, pipeId: number, e: Event): void {
    this.state.updatePipeline(pageId, pipeId, { description: val(e) });
  }
  setStepType(pageId: number, pipeId: number, idx: number, e: Event): void {
    this.state.updatePipelineStep(pageId, pipeId, idx, { type: val(e) as PipelineStepType });
  }
  setStepLabel(pageId: number, pipeId: number, idx: number, e: Event): void {
    this.state.updatePipelineStep(pageId, pipeId, idx, { label: val(e) });
  }
  setStepServiceMethod(pageId: number, pipeId: number, idx: number, e: Event): void {
    this.state.updatePipelineStep(pageId, pipeId, idx, { service_method: val(e) });
  }
  setStepDataFlow(pageId: number, pipeId: number, idx: number, e: Event): void {
    this.state.updatePipelineStep(pageId, pipeId, idx, { data_flow: val(e) });
  }
  setStepDescription(pageId: number, pipeId: number, idx: number, e: Event): void {
    this.state.updatePipelineStep(pageId, pipeId, idx, { description: val(e) });
  }
  setStepOnError(pageId: number, pipeId: number, idx: number, e: Event): void {
    this.state.updatePipelineStep(pageId, pipeId, idx, { on_error: val(e) });
  }
  setStepServiceName(pageId: number, pipeId: number, idx: number, e: Event): void {
    this.state.updatePipelineStep(pageId, pipeId, idx, { service_name: val(e) });
  }
  setTriggerInteraction(pageId: number, pipeId: number, e: Event): void {
    this.state.updatePipeline(pageId, pipeId, { trigger_interaction: val(e) || undefined });
  }

  getPageInteractions(page: import('../../models/app-spec.model').Page) {
    return page.interactions;
  }
}
