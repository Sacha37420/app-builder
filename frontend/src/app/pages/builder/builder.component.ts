import { Component, inject, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { BuilderStateService } from '../../core/builder-state.service';
import { BuilderApiService } from '../../core/builder-api.service';
import { SpecSummaryComponent } from '../../shared/spec-summary/spec-summary.component';
import { AiChatComponent } from '../../shared/ai-chat/ai-chat.component';
import { AppSpec } from '../../models/app-spec.model';

@Component({
  selector: 'app-builder',
  standalone: true,
  imports: [RouterLink, SpecSummaryComponent, AiChatComponent],
  templateUrl: './builder.component.html',
  styleUrl: './builder.component.scss',
})
export class BuilderComponent implements OnInit {
  state = inject(BuilderStateService);
  private api = inject(BuilderApiService);

  savedApps = signal<AppSpec[]>([]);
  showAppList = signal(false);
  listError = signal('');

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
    this.listError.set('');
    this.api.listApps().subscribe({
      next: apps => this.savedApps.set(apps),
      error: () => this.listError.set("La liste de vos applications n'a pas pu être chargée : réessayez."),
    });
  }

  save(): void {
    this.state.saveNow().subscribe({
      next: () => this.loadList(),
      error: () => {},
    });
  }

  /** Changer de spec alors qu'une modification n'est pas encore partie la perdrait. */
  private peutQuitter(): boolean {
    const status = this.state.saveStatus();
    if (!this.state.isDirty() && status !== 'pending' && status !== 'saving') return true;
    return confirm("Des modifications de l'application ouverte ne sont pas encore enregistrées. Les abandonner ?");
  }

  loadApp(app: AppSpec): void {
    if (!app.id || !this.peutQuitter()) return;
    // Relue sur le serveur : la liste a pu être chargée avant les dernières modifications
    // (enregistrement automatique, propositions appliquées) ; ouverte telle quelle, sa copie
    // ancienne repartait au prochain enregistrement et les effaçait.
    this.api.getApp(app.id).subscribe({
      next: spec => { this.state.loadSpec(spec); this.showAppList.set(false); },
      error: () => this.listError.set(`« ${app.name} » n'a pas pu être ouverte : réessayez.`),
    });
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
      error: () => this.listError.set(`« ${app.name} » n'a pas pu être supprimée : réessayez.`),
    });
  }

  newApp(): void {
    if (!this.peutQuitter()) return;
    this.state.resetSpec();
    this.showAppList.set(false);
  }

  toggleAppList(): void {
    this.showAppList.update(v => !v);
    if (this.showAppList()) this.loadList();
  }
}
