import { Component, inject, OnInit, signal } from '@angular/core';
import { BuilderStateService } from '../../core/builder-state.service';
import { BuilderApiService } from '../../core/builder-api.service';
import { SchemaCanvasComponent } from '../../shared/schema-canvas/schema-canvas.component';
import { AiChatComponent } from '../../shared/ai-chat/ai-chat.component';
import { NavbarComponent } from '../../shared/navbar/navbar.component';
import { AppSpec } from '../../models/app-spec.model';

@Component({
  selector: 'app-builder',
  standalone: true,
  imports: [SchemaCanvasComponent, AiChatComponent, NavbarComponent],
  templateUrl: './builder.component.html',
  styleUrl: './builder.component.scss',
})
export class BuilderComponent implements OnInit {
  state = inject(BuilderStateService);
  private api = inject(BuilderApiService);

  savedApps = signal<AppSpec[]>([]);
  saving = signal(false);
  saveError = signal('');
  showAppList = signal(false);

  ngOnInit(): void {
    this.loadList();
  }

  loadList(): void {
    this.api.listApps().subscribe({
      next: apps => this.savedApps.set(apps),
      error: () => {},
    });
  }

  save(): void {
    this.saving.set(true);
    this.saveError.set('');
    const id = this.state.savedId();
    const spec = this.state.spec();

    const obs = id
      ? this.api.updateApp(id, spec)
      : this.api.createApp(spec);

    obs.subscribe({
      next: saved => {
        this.state.markSaved(saved.id!);
        this.saving.set(false);
        this.loadList();
      },
      error: err => {
        this.saveError.set(err.error?.detail ?? 'Erreur lors de la sauvegarde.');
        this.saving.set(false);
      },
    });
  }

  loadApp(app: AppSpec): void {
    this.state.loadSpec(app);
    this.showAppList.set(false);
  }

  newApp(): void {
    this.state.resetSpec();
    this.showAppList.set(false);
  }

  toggleAppList(): void {
    this.showAppList.update(v => !v);
  }
}
