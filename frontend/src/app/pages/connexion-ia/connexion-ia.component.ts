import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { BuilderApiService } from '../../core/builder-api.service';
import { BuilderStateService } from '../../core/builder-state.service';
import { AiProvider, AiProviderSettings, AppSpec, McpInfo, McpScope, McpToken } from '../../models/app-spec.model';
import { AiSettingsService, MESSAGE_JETON_ABONNEMENT } from '../../core/ai-settings.service';
import { val } from '../../core/form-utils';

const JETON = '<JETON>';

/**
 * Page « Intelligence artificielle » (route `/ia`, ancienne `/connexion-ia`) — lot 13 :
 * le seul endroit où se règle l'IA.
 *  1. Fournisseurs du chat intégré (Claude, Mistral, Albert) : clé au coffre du serveur
 *     (jamais relue), modèle par défaut, fournisseur choisi pour le chat — préférences
 *     gardées sur le serveur (`/api/ai-settings/`), partagées avec le ⚙ du chat.
 *  2. Claude Code et Vibe : jetons personnels du serveur MCP d'App Builder (contrat I5),
 *     pour piloter une spécification avec son propre abonnement. Le jeton complet n'est
 *     montré qu'une fois, juste après sa création ; il n'est gardé nulle part dans le navigateur.
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
  ai = inject(AiSettingsService);

  // ── Fournisseurs (lot 13) ──
  /** Saisie en cours, par fournisseur : jamais gardée, vidée après l'envoi au coffre. */
  keyInput = signal<Partial<Record<AiProvider, string>>>({});
  keyVisible = signal<Partial<Record<AiProvider, boolean>>>({});
  keyBusy = signal<AiProvider | null>(null);
  keyMessage = signal<{ provider: AiProvider; text: string; ok: boolean } | null>(null);

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
    return { url: i.url, claude: sub(i.claude), vibe: sub(i.vibe), env: sub(i.env ?? ''),
             mcpJson: i.mcp_json ?? '', withToken: !!t };
  });

  ngOnInit(): void {
    this.ai.load(true);
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

  // ── Fournisseurs ────────────────────────────────────────────────────────────

  setKeyInput(p: AiProvider, e: Event): void { this.keyInput.update(k => ({ ...k, [p]: val(e) })); }
  toggleKeyVisible(p: AiProvider): void { this.keyVisible.update(k => ({ ...k, [p]: !k[p] })); }

  saveKey(p: AiProviderSettings, retirer = false): void {
    const valeur = retirer ? '' : (this.keyInput()[p.id] ?? '').trim();
    if (!retirer && !valeur) return;
    if (retirer && !confirm(`Retirer la clé ${p.label} enregistrée sur le serveur ?`)) return;
    this.keyBusy.set(p.id);
    this.keyMessage.set(null);
    this.ai.saveKey(p.id, valeur).subscribe({
      next: () => {
        this.keyBusy.set(null);
        this.keyInput.update(k => ({ ...k, [p.id]: '' }));
        this.keyMessage.set({ provider: p.id, ok: true, text: retirer ? 'Clé retirée.' : 'Clé enregistrée sur le serveur.' });
      },
      error: (err: HttpErrorResponse | { error?: { code?: string; error?: string } }) => {
        this.keyBusy.set(null);
        if (err?.error?.code === 'oauth_token_refused') this.keyInput.update(k => ({ ...k, [p.id]: '' }));
        this.keyMessage.set({ provider: p.id, ok: false, text: err?.error?.code === 'oauth_token_refused'
          ? MESSAGE_JETON_ABONNEMENT : `Clé non enregistrée : ${err?.error?.error ?? 'erreur du serveur'}` });
      },
    });
  }

  setDefaultModel(p: AiProvider, e: Event): void { this.pref(this.ai.setModel(p, val(e)), p); }
  useForChat(p: AiProvider): void { this.pref(this.ai.setProvider(p), p); }

  private pref(appel: ReturnType<AiSettingsService['setProvider']>, p: AiProvider): void {
    this.keyMessage.set(null);
    appel.subscribe({
      error: (err: HttpErrorResponse) => {
        this.keyMessage.set({ provider: p, ok: false, text: err?.error?.error ?? 'Choix non enregistré.' });
        this.ai.load(true);
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
