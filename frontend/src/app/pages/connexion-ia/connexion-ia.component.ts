import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { BuilderApiService } from '../../core/builder-api.service';
import { BuilderStateService } from '../../core/builder-state.service';
import { AppSpec, McpInfo, McpScope, McpToken } from '../../models/app-spec.model';
import { val } from '../../core/form-utils';

const JETON = '<JETON>';

/**
 * Page « Connexion IA » (route `/connexion-ia`) : jetons personnels du serveur MCP
 * d'App Builder (contrat I5), pour piloter une spécification depuis Claude Code ou
 * Mistral Vibe avec son propre abonnement. Le jeton complet n'est montré qu'une
 * fois, juste après sa création ; il n'est gardé nulle part dans le navigateur.
 */
@Component({
  selector: 'app-connexion-ia-page',
  standalone: true,
  imports: [DatePipe],
  templateUrl: './connexion-ia.component.html',
  styleUrl: './connexion-ia.component.scss',
})
export class ConnexionIaPageComponent implements OnInit {
  private api = inject(BuilderApiService);
  state = inject(BuilderStateService);

  tokens = signal<McpToken[]>([]);
  specs = signal<AppSpec[]>([]);
  info = signal<McpInfo | null>(null);
  loading = signal(true);
  failed = signal('');
  busy = signal(false);
  formError = signal('');

  // Formulaire de création
  name = signal('Mon Claude Code');
  scope = signal<McpScope>('ecrire');
  specChoice = signal<string>('');      // '' = toutes mes spécifications
  days = signal(30);

  /** Jeton tout juste créé : affiché une seule fois, oublié à la fermeture de l'encart ou de la page. */
  fresh = signal<McpToken | null>(null);
  copied = signal<string | null>(null);

  readonly active = computed(() => this.tokens().filter(t => !t.revoked));
  readonly revoked = computed(() => this.tokens().filter(t => t.revoked));

  /** Commandes de `GET /api/mcp/info/`, le jeton substitué dans le navigateur seulement s'il vient d'être créé. */
  readonly commands = computed(() => {
    const i = this.info();
    if (!i) return null;
    const t = this.fresh()?.token;
    const sub = (c: string) => (t ? c.split(JETON).join(t) : c);
    return { url: i.url, claude: sub(i.claude), vibe: sub(i.vibe), withToken: !!t };
  });

  ngOnInit(): void {
    this.refresh();
    this.api.getMcpInfo().subscribe({ next: i => this.info.set(i), error: () => this.info.set(null) });
    this.api.listApps().subscribe({ next: a => this.specs.set(a), error: () => this.specs.set([]) });
    const current = this.state.savedId();
    if (current !== null) this.specChoice.set(String(current));
  }

  refresh(): void {
    this.loading.set(true);
    this.api.listMcpTokens().subscribe({
      next: list => { this.tokens.set(list); this.loading.set(false); this.failed.set(''); },
      error: () => { this.loading.set(false); this.failed.set('La liste des jetons est indisponible.'); },
    });
  }

  specName(id: number | null): string {
    if (id === null) return 'toutes mes spécifications';
    return this.specs().find(s => s.id === id)?.name ?? `spécification n° ${id}`;
  }

  setName(e: Event): void { this.name.set(val(e)); }
  setScope(e: Event): void { this.scope.set(val(e) === 'lire' ? 'lire' : 'ecrire'); }
  setSpec(e: Event): void { this.specChoice.set(val(e)); }
  setDays(e: Event): void {
    const n = Math.round(Number(val(e)));
    this.days.set(Number.isFinite(n) ? Math.min(90, Math.max(1, n)) : 30);
  }

  create(): void {
    const name = this.name().trim();
    if (!name) { this.formError.set('Donnez un nom au jeton (par exemple, la machine où il servira).'); return; }
    this.busy.set(true);
    this.formError.set('');
    const body: { name: string; scope: McpScope; spec_id?: number; days?: number } = {
      name: name.slice(0, 80), scope: this.scope(), days: this.days(),
    };
    if (this.specChoice()) body.spec_id = Number(this.specChoice());
    this.api.createMcpToken(body).subscribe({
      next: t => {
        this.busy.set(false);
        this.fresh.set(t);
        const { token: _secret, ...stored } = t;
        this.tokens.update(list => [stored, ...list]);
      },
      error: (err: HttpErrorResponse) => {
        this.busy.set(false);
        const e = err.error;
        this.formError.set(typeof e?.error === 'string' ? e.error
          : (e && typeof e === 'object' ? Object.values(e).flat().map(String).join(' ') : '') || 'Création refusée.');
      },
    });
  }

  dismissFresh(): void { this.fresh.set(null); this.copied.set(null); }

  revoke(t: McpToken): void {
    if (!confirm(`Révoquer le jeton « ${t.name} » (${t.prefix}…) ? L'outil qui l'utilise perdra l'accès immédiatement.`)) return;
    this.busy.set(true);
    this.api.revokeMcpToken(t.id).subscribe({
      next: () => {
        this.busy.set(false);
        if (this.fresh()?.id === t.id) this.dismissFresh();
        this.refresh();
      },
      error: () => { this.busy.set(false); this.failed.set('Révocation refusée par le serveur.'); },
    });
  }

  async copy(what: string, text: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      this.copied.set(what);
      setTimeout(() => { if (this.copied() === what) this.copied.set(null); }, 2000);
    } catch {
      this.copied.set(null);
    }
  }
}
