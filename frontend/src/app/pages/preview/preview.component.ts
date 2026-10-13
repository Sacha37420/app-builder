import { Component, computed, effect, inject, OnDestroy, signal, untracked } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { BuilderApiService } from '../../core/builder-api.service';
import { BuilderStateService } from '../../core/builder-state.service';
import { Livrables } from '../../models/app-spec.model';

type Doc = 'lots' | 'cahier';

const TYPE_LABELS: Record<string, string> = {
  'django-angular': 'Django + Angular',
  'django':         'Django seul (API)',
  'angular':        'Angular seul',
  'spring-angular': 'Spring + Angular',
  'spring':         'Spring seul',
};

const DOCS: { id: Doc; label: string; file: string }[] = [
  { id: 'lots',   label: 'FEUILLE_DE_ROUTE.md (lots)', file: 'lots.md' },
  { id: 'cahier', label: 'CAHIER_DES_CHARGES.md',      file: 'CAHIER_DES_CHARGES.md' },
];

/**
 * Page « Livrables » (route `/preview`, nom de classe gardé pour ne pas toucher
 * aux routes) : ce qui sera réellement remis au lab pour construire l'app — le
 * cahier des charges et la feuille de route générés par le serveur. Rien n'est
 * calculé ici : la page affiche la réponse de `GET /api/apps/<id>/livrables/`.
 */
@Component({
  selector: 'app-preview-page',
  standalone: true,
  imports: [RouterLink, DatePipe],
  templateUrl: './preview.component.html',
  styleUrl: './preview.component.scss',
})
export class PreviewPageComponent implements OnDestroy {
  state = inject(BuilderStateService);
  private api = inject(BuilderApiService);

  readonly docs = DOCS;

  livrables = signal<Livrables | null>(null);
  loading = signal(false);
  failed = signal(false);
  activeDoc = signal<Doc>('lots');
  /** Document dont le bouton « Copier » affiche « Copié » (2 s), sinon `null`. */
  copied = signal<Doc | null>(null);

  /** L'état affiché est celui de la dernière version enregistrée : le dire quand la spec a bougé depuis. */
  unsaved = computed(() => {
    const status = this.state.saveStatus();
    return this.state.isDirty() || status === 'pending' || status === 'saving';
  });

  /** Plus gros lot rapporté au plafond, en pourcentage (peut dépasser 100). */
  lotPercent = computed(() => {
    const ctx = this.livrables()?.context;
    if (!ctx || ctx.lot_budget_tokens <= 0) return 0;
    return Math.round((ctx.largest_lot_tokens / ctx.lot_budget_tokens) * 100);
  });
  lotOver = computed(() => this.lotPercent() > 100);

  docText = computed(() => {
    const l = this.livrables();
    if (!l) return '';
    return this.activeDoc() === 'lots' ? l.lots_md : l.cahier_des_charges_md;
  });
  docMeta = computed(() => DOCS.find(d => d.id === this.activeDoc())!);

  private request?: Subscription;
  private copiedTimer?: ReturnType<typeof setTimeout>;

  constructor() {
    // Au montage, puis à chaque fois que la spec enregistrée change : `lab` est
    // relu par le service après chaque enregistrement réussi et remis à `null`
    // à chaque changement de spec.
    effect(() => {
      const id = this.state.savedId();
      this.state.lab();
      untracked(() => this.load(id));
    });
  }

  ngOnDestroy(): void {
    this.request?.unsubscribe();
    clearTimeout(this.copiedTimer);
  }

  reload(): void { this.load(this.state.savedId()); }

  private load(id: number | null): void {
    // Une requête en cours ne vaut plus rien : sa réponse décrirait un état dépassé.
    this.request?.unsubscribe();
    if (id === null) {
      this.livrables.set(null);
      this.loading.set(false);
      this.failed.set(false);
      return;
    }
    // Autre spec que celle affichée : ne pas laisser les livrables de la précédente à l'écran.
    if (this.livrables()?.spec.id !== id) this.livrables.set(null);
    this.loading.set(true);
    this.failed.set(false);
    this.request = this.api.getLivrables(id).subscribe({
      next: res => {
        if (this.state.savedId() !== id) return;   // réponse arrivée après un changement de spec
        this.livrables.set(res);
        this.loading.set(false);
      },
      error: () => {
        if (this.state.savedId() !== id) return;
        this.livrables.set(null);
        this.failed.set(true);
        this.loading.set(false);
      },
    });
  }

  /** Nombre avec séparateur de milliers français (aucune locale Angular n'est enregistrée dans l'app). */
  n(value: number): string { return Math.round(value).toLocaleString('fr-FR'); }

  typeLabel(t: string): string { return TYPE_LABELS[t] ?? t; }

  copyDoc(): void {
    const doc = this.activeDoc();
    navigator.clipboard?.writeText(this.docText()).then(() => {
      this.copied.set(doc);
      clearTimeout(this.copiedTimer);
      this.copiedTimer = setTimeout(() => this.copied.set(null), 2000);
    }).catch(() => {});
  }

  downloadDoc(): void {
    const url = URL.createObjectURL(new Blob([this.docText()], { type: 'text/markdown' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = this.docMeta().file;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }
}
