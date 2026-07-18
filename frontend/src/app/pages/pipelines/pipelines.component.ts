import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BuilderStateService } from '../../core/builder-state.service';
import { Page, Pipeline, PipelineStep, PipelineStepType } from '../../models/app-spec.model';

@Component({
  selector: 'app-pipelines-page',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './pipelines.component.html',
  styleUrl: './pipelines.component.scss',
})
export class PipelinesPageComponent {
  state = inject(BuilderStateService);

  selectedPageId = signal<number | null>(null);
  expandedPipelineId = signal<number | null>(null);

  readonly stepTypes: PipelineStepType[] = [
    'trigger', 'service_call', 'transform', 'state_update', 'navigate', 'error',
  ];

  readonly stepTypeLabels: Record<PipelineStepType, string> = {
    trigger:      'Déclencheur',
    service_call: 'Appel service',
    transform:    'Transformation',
    state_update: 'Mise à jour état',
    navigate:     'Navigation',
    error:        'Erreur',
  };

  readonly stepTypeIcons: Record<PipelineStepType, string> = {
    trigger:      '⚡',
    service_call: '🔌',
    transform:    '⚙',
    state_update: '📦',
    navigate:     '→',
    error:        '⚠',
  };

  get selectedPage(): Page | undefined {
    const id = this.selectedPageId();
    return id !== null ? this.state.spec().pages.find(p => p.id === id) : undefined;
  }

  selectPage(id: number): void {
    this.selectedPageId.set(id);
    this.expandedPipelineId.set(null);
  }

  togglePipeline(id: number): void {
    this.expandedPipelineId.update(v => v === id ? null : id);
  }

  totalSteps(pipeline: Pipeline): number {
    return pipeline.steps.length;
  }

  stepClass(type: PipelineStepType): string {
    return `step-${type.replace('_', '-')}`;
  }

  val(e: Event): string { return (e.target as HTMLInputElement).value; }

  setPipelineName(pageId: number, pipeId: number, e: Event): void {
    this.state.updatePipeline(pageId, pipeId, { name: this.val(e) });
  }
  setPipelineDesc(pageId: number, pipeId: number, e: Event): void {
    this.state.updatePipeline(pageId, pipeId, { description: this.val(e) });
  }
  setStepType(pageId: number, pipeId: number, idx: number, e: Event): void {
    this.state.updatePipelineStep(pageId, pipeId, idx, { type: this.val(e) as PipelineStepType });
  }
  setStepLabel(pageId: number, pipeId: number, idx: number, e: Event): void {
    this.state.updatePipelineStep(pageId, pipeId, idx, { label: this.val(e) });
  }
  setStepServiceMethod(pageId: number, pipeId: number, idx: number, e: Event): void {
    this.state.updatePipelineStep(pageId, pipeId, idx, { service_method: this.val(e) });
  }
  setStepDataFlow(pageId: number, pipeId: number, idx: number, e: Event): void {
    this.state.updatePipelineStep(pageId, pipeId, idx, { data_flow: this.val(e) });
  }
  setStepDescription(pageId: number, pipeId: number, idx: number, e: Event): void {
    this.state.updatePipelineStep(pageId, pipeId, idx, { description: this.val(e) });
  }
  setStepOnError(pageId: number, pipeId: number, idx: number, e: Event): void {
    this.state.updatePipelineStep(pageId, pipeId, idx, { on_error: this.val(e) });
  }
  setStepServiceName(pageId: number, pipeId: number, idx: number, e: Event): void {
    this.state.updatePipelineStep(pageId, pipeId, idx, { service_name: this.val(e) });
  }
  setTriggerInteraction(pageId: number, pipeId: number, e: Event): void {
    this.state.updatePipeline(pageId, pipeId, { trigger_interaction: this.val(e) || undefined });
  }

  getPageInteractions(page: import('../../models/app-spec.model').Page) {
    return page.interactions;
  }
}
