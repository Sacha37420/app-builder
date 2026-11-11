import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, map, switchMap, tap } from 'rxjs';
import { BuilderApiService } from './builder-api.service';
import { AiProvider, AiProviderSettings, AiSettings, ModelInfo } from '../models/app-spec.model';

/** Préfixe d'un jeton d'abonnement Claude : il ne s'utilise que dans Claude Code, jamais ici. */
export const PREFIXE_JETON_ABONNEMENT = 'sk-ant-oat';
export const MESSAGE_JETON_ABONNEMENT =
  "Ce jeton d'abonnement Claude (sk-ant-oat…) ne s'utilise que dans Claude Code : App Builder ne le garde pas. "
  + 'Déposez ici une clé d’API (sk-ant-api…), ou reliez votre Claude Code plus bas sur cette page.';

/** Anciennes préférences et clés gardées dans le navigateur avant le lot 13 : effacées, jamais envoyées. */
const ANCIENNES_ENTREES = ['ai_provider', 'ai_claude_model', 'ai_mistral_model', 'ai_claude_key', 'ai_mistral_key'];

/**
 * Réglages de l'IA, partagés par la page « Intelligence artificielle » et le chat.
 * Source unique : `GET/PUT /api/ai-settings/` (préférences gardées sur le serveur) et
 * `PUT /api/ai-keys/` (coffre). Le navigateur ne garde ni clé ni préférence.
 */
@Injectable({ providedIn: 'root' })
export class AiSettingsService {
  private api = inject(BuilderApiService);

  readonly settings = signal<AiSettings | null>(null);
  readonly unavailable = signal(false);

  readonly providers = computed<AiProviderSettings[]>(() => this.settings()?.providers ?? []);
  readonly configured = computed(() => this.providers().filter(p => p.configured));
  readonly provider = computed<AiProvider>(() => this.settings()?.preferences.provider ?? 'claude');
  readonly model = computed(() => this.modelOf(this.provider()));
  readonly current = computed(() => this.providers().find(p => p.id === this.provider()) ?? null);
  /** Une clé du fournisseur choisi est-elle au coffre ? Inconnu ⇒ vrai (le serveur reste juge). */
  readonly activeConfigured = computed(() => this.settings() ? !!this.current()?.configured : true);

  private chargement = false;

  constructor() {
    for (const k of ANCIENNES_ENTREES) {
      try { localStorage.removeItem(k); } catch { /* stockage indisponible : rien à effacer */ }
    }
  }

  /** Charge une fois (ou recharge si `force`). */
  load(force = false): void {
    if ((this.settings() && !force) || this.chargement) return;
    this.chargement = true;
    this.api.getAiSettings().subscribe({
      next: s => { this.settings.set(s); this.unavailable.set(false); this.chargement = false; },
      error: () => { this.unavailable.set(true); this.chargement = false; },
    });
  }

  modelOf(provider: AiProvider): string {
    const s = this.settings();
    return s?.preferences.models[provider] ?? this.providers().find(p => p.id === provider)?.default_model ?? '';
  }

  modelsOf(provider: AiProvider): ModelInfo[] {
    return this.providers().find(p => p.id === provider)?.models ?? [];
  }

  labelOf(provider: AiProvider): string {
    return this.providers().find(p => p.id === provider)?.label ?? provider;
  }

  setProvider(provider: AiProvider): Observable<AiSettings> {
    return this.api.putAiSettings({ provider }).pipe(tap(s => this.settings.set(s)));
  }

  setModel(provider: AiProvider, model: string): Observable<AiSettings> {
    return this.api.putAiSettings({ models: { [provider]: model } }).pipe(tap(s => this.settings.set(s)));
  }

  /** Dépose une clé au coffre (`''` la retire), puis relit l'état. Jeton d'abonnement Claude refusé ici même. */
  saveKey(provider: AiProvider, valeur: string): Observable<AiSettings> {
    const v = valeur.trim();
    if (provider === 'claude' && v.startsWith(PREFIXE_JETON_ABONNEMENT)) {
      return new Observable(o => o.error({ error: { code: 'oauth_token_refused' } }));
    }
    return this.api.putAiKeys({ [`${provider}_key`]: v }).pipe(
      switchMap(() => this.api.getAiSettings()),
      tap(s => this.settings.set(s)),
      map(s => s),
    );
  }
}
