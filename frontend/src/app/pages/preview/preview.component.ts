import { Component, inject, signal, computed } from '@angular/core';
import { BuilderStateService } from '../../core/builder-state.service';
import { NavbarComponent } from '../../shared/navbar/navbar.component';
import {
  generateModelsPy, generateSerializersPy, generateViewsPy,
  generateUrlsPy, generateServiceTs, generateComponentTs,
} from './code-generators';
import { FrontendService, Page } from '../../models/app-spec.model';

type Tab = 'models_py' | 'serializers_py' | 'views_py' | 'urls_py' | 'service_ts' | 'component_ts';

@Component({
  selector: 'app-preview-page',
  standalone: true,
  imports: [NavbarComponent],
  templateUrl: './preview.component.html',
  styleUrl: './preview.component.scss',
})
export class PreviewPageComponent {
  state = inject(BuilderStateService);

  activeTab = signal<Tab>('models_py');
  selectedServiceId = signal<number | null>(null);
  selectedPageId = signal<number | null>(null);

  readonly tabs: { id: Tab; label: string; file: string }[] = [
    { id: 'models_py',      label: 'models.py',      file: 'backend/api/models.py' },
    { id: 'serializers_py', label: 'serializers.py', file: 'backend/api/serializers.py' },
    { id: 'views_py',       label: 'views.py',       file: 'backend/api/views.py' },
    { id: 'urls_py',        label: 'urls.py',         file: 'backend/api/urls.py' },
    { id: 'service_ts',     label: '*.service.ts',   file: 'frontend/src/app/core/<service>.ts' },
    { id: 'component_ts',   label: '*.component.ts', file: 'frontend/src/app/pages/<page>/' },
  ];

  get code(): string {
    const spec = this.state.spec();
    const tab = this.activeTab();

    if (tab === 'models_py')      return generateModelsPy(spec);
    if (tab === 'serializers_py') return generateSerializersPy(spec);
    if (tab === 'views_py')       return generateViewsPy(spec);
    if (tab === 'urls_py')        return generateUrlsPy(spec);

    if (tab === 'service_ts') {
      const svc = spec.services.find(s => s.id === this.selectedServiceId());
      return svc ? generateServiceTs(spec, svc) : '// Sélectionnez un service ci-dessus';
    }

    if (tab === 'component_ts') {
      const page = spec.pages.find(p => p.id === this.selectedPageId());
      return page ? generateComponentTs(spec, page) : '// Sélectionnez une page ci-dessus';
    }

    return '';
  }

  get currentFile(): string {
    const tab = this.tabs.find(t => t.id === this.activeTab());
    if (!tab) return '';
    const label = tab.file;
    if (this.activeTab() === 'service_ts') {
      const svc = this.state.spec().services.find(s => s.id === this.selectedServiceId());
      return svc ? label.replace('<service>', svc.name.toLowerCase() + '.service') : label;
    }
    if (this.activeTab() === 'component_ts') {
      const page = this.state.spec().pages.find(p => p.id === this.selectedPageId());
      return page ? label.replace('<page>', page.name.toLowerCase()) : label;
    }
    return label;
  }

  get completionScore(): { phase: string; score: number; total: number }[] {
    const spec = this.state.spec();
    const totalEndpoints = spec.endpoint_groups.reduce((s, g) => s + g.endpoints.length, 0);
    const enrichedEndpoints = spec.endpoint_groups
      .flatMap(g => g.endpoints)
      .filter(e => e.linked_model_name || e.operation !== 'custom').length;

    const totalPages = spec.pages.length;
    const enrichedPages = spec.pages.filter(p => p.layout !== 'mixed' || p.components.length > 0).length;
    const pipelinesTotal = spec.pages.reduce((s, p) => s + p.pipelines.length, 0);
    const pipelinesWithSteps = spec.pages
      .flatMap(p => p.pipelines)
      .filter(pl => pl.steps.length > 0).length;

    return [
      { phase: 'Phase 1 — Modèles', score: spec.data_models.length, total: Math.max(1, spec.data_models.length) },
      { phase: 'Phase 2 — Endpoints', score: enrichedEndpoints, total: Math.max(1, totalEndpoints) },
      { phase: 'Phase 3 — Pages', score: enrichedPages, total: Math.max(1, totalPages) },
      { phase: 'Phase 4 — Pipelines', score: pipelinesWithSteps, total: Math.max(1, pipelinesTotal) },
    ];
  }

  copyCode(): void {
    navigator.clipboard.writeText(this.code).catch(() => {});
  }

  setTab(tab: Tab): void {
    this.activeTab.set(tab);
  }
}
