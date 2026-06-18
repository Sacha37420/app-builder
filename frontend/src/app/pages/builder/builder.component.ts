import { Component, inject, OnInit, signal } from '@angular/core';
import { BuilderStateService } from '../../core/builder-state.service';
import { BuilderApiService } from '../../core/builder-api.service';
import { SchemaCanvasComponent } from '../../shared/schema-canvas/schema-canvas.component';
import { AiChatComponent } from '../../shared/ai-chat/ai-chat.component';
import { AppSpec } from '../../models/app-spec.model';

@Component({
  selector: 'app-builder',
  standalone: true,
  imports: [SchemaCanvasComponent, AiChatComponent],
  templateUrl: './builder.component.html',
  styleUrl: './builder.component.scss',
})
export class BuilderComponent implements OnInit {
  state = inject(BuilderStateService);
  private api = inject(BuilderApiService);

  savedApps = signal<AppSpec[]>([]);
  showAppList = signal(false);

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

  newApp(): void {
    this.state.resetSpec();
    this.showAppList.set(false);
  }

  toggleAppList(): void {
    this.showAppList.update(v => !v);
  }
}
