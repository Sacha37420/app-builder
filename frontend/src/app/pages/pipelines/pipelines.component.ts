import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BuilderStateService } from '../../core/builder-state.service';
import { Page, Pipeline, PipelineStep, PipelineStepType } from '../../models/app-spec.model';
import { NavbarComponent } from '../../shared/navbar/navbar.component';

@Component({
  selector: 'app-pipelines-page',
  standalone: true,
  imports: [FormsModule, NavbarComponent],
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
}
