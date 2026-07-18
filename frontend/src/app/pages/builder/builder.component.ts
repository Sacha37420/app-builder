import { Component, inject, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { BuilderStateService } from '../../core/builder-state.service';
import { BuilderApiService } from '../../core/builder-api.service';
import { SchemaCanvasComponent } from '../../shared/schema-canvas/schema-canvas.component';
import { AiChatComponent } from '../../shared/ai-chat/ai-chat.component';
import { AppSpec } from '../../models/app-spec.model';

@Component({
  selector: 'app-builder',
  standalone: true,
  imports: [RouterLink, SchemaCanvasComponent, AiChatComponent],
  templateUrl: './builder.component.html',
  styleUrl: './builder.component.scss',
})
export class BuilderComponent implements OnInit {
  state = inject(BuilderStateService);
  private api = inject(BuilderApiService);

  savedApps = signal<AppSpec[]>([]);
  showAppList = signal(false);

  /** Repliée par défaut sous 900px : évite que la rangée de navigation/actions
   *  n'empiète sur la hauteur, réduite, allouée au canevas de schéma. */
  toolbarExpanded = signal(false);

  /** Sous 900px, canevas et chat ne tiennent plus côte à côte : un onglet
   *  bascule entre les deux au lieu de les empiler (ce qui les rendrait
   *  illisibles). Sans effet en desktop, où les deux restent affichés. */
  mobileView = signal<'canvas' | 'chat'>('canvas');

  ngOnInit(): void {
    this.loadList();
  }

  private loadList(): void {
    this.api.listApps().subscribe({
      next: apps => this.savedApps.set(apps),
      error: () => {},
    });
  }

  save(): void {
    this.state.saveNow().subscribe({
      next: () => this.loadList(),
      error: () => {},
    });
  }

  loadApp(app: AppSpec): void {
    this.state.loadSpec(app);
    this.showAppList.set(false);
  }

  deleteApp(app: AppSpec, event: Event): void {
    event.stopPropagation();
    if (!app.id) return;
    if (!confirm(`Supprimer l'application "${app.name}" ? Cette action est irréversible.`)) return;

    this.api.deleteApp(app.id).subscribe({
      next: () => {
        if (this.state.spec().id === app.id) this.state.resetSpec();
        this.loadList();
      },
      error: () => {},
    });
  }

  newApp(): void {
    this.state.resetSpec();
    this.showAppList.set(false);
  }

  toggleAppList(): void {
    this.showAppList.update(v => !v);
  }
}
