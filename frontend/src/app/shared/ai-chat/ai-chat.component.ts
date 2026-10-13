import { Component, inject, signal, computed, effect, ViewChild, ElementRef, AfterViewChecked, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BuilderApiService } from '../../core/builder-api.service';
import { BuilderStateService } from '../../core/builder-state.service';
import { Subscription } from 'rxjs';
import { AiProvider, ChatContext, ChatMessage, ModelCatalogue, PatchMode, PersistedChatMessage } from '../../models/app-spec.model';

type AppliedState = 'none' | 'merged' | 'replaced';

interface Choices { multiple: boolean; items: string[]; }

interface DisplayMessage extends PersistedChatMessage {
  applied?: AppliedState;
  choices?: Choices | null;
}

interface ModelOption { id: string; label: string; }

type EtatJauge = 'normal' | 'attention' | 'alerte';

/** Délai d'anti-rebond de l'estimation du contexte. */
const DELAI_ESTIMATION_MS = 600;

const nombre = (n: number): string => n.toLocaleString('fr-FR');

const STARTER_PROMPTS = [
  'Je veux une app de gestion de stock avec tableau de bord et alertes de seuil',
  'Je veux un outil de suivi de tâches pour une petite équipe',
  'Je veux un site e-commerce avec catalogue, panier et commandes',
  'Je veux une app de réservation (créneaux, clients, confirmations)',
];

const LS = {
  provider:      'ai_provider',
  claudeKey:     'ai_claude_key',
  claudeModel:   'ai_claude_model',
  mistralKey:    'ai_mistral_key',
  mistralModel:  'ai_mistral_model',
};

@Component({
  selector: 'app-ai-chat',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './ai-chat.component.html',
  styleUrl: './ai-chat.component.scss',
})
export class AiChatComponent implements AfterViewChecked, OnInit {
  @ViewChild('messagesEl')  messagesEl?:  ElementRef<HTMLDivElement>;
  @ViewChild('chatInputEl') chatInputEl?: ElementRef<HTMLTextAreaElement>;

  private api = inject(BuilderApiService);
  state = inject(BuilderStateService);

  messages    = signal<DisplayMessage[]>([]);
  inputText   = signal('');
  loading     = signal(false);
  patchBusy   = signal(false);
  error       = signal('');
  showSettings  = signal(false);
  showTutorial  = signal(false);
  showClaudeKey = signal(false);
  showMistralKey = signal(false);

  provider     = signal<AiProvider>('claude');
  claudeKey    = signal('');
  claudeModel  = signal('claude-sonnet-4-6');
  mistralKey   = signal('');
  mistralModel = signal('mistral-small-latest');

  // State pour les choix du dernier message assistant
  selectedChoices = signal<Set<string>>(new Set());

  // Liste des modèles : servie par l'API. Tant qu'elle manque, le modèle mémorisé reste seul proposé.
  catalogue       = signal<ModelCatalogue | null>(null);
  modelsUnavailable = signal(false);
  readonly claudeModels  = computed(() => this.modelsOf('claude',  this.claudeModel()));
  readonly mistralModels = computed(() => this.modelsOf('mistral', this.mistralModel()));
  readonly starters      = STARTER_PROMPTS;

  // Mesure du contexte : dernière réponse de /api/chat/ ou dernière estimation.
  contexte     = signal<ChatContext | null>(null);
  readonly depasse = computed(() => this.contexte()?.fits === false);
  readonly jauge = computed(() => {
    const c = this.contexte();
    if (!c) return null;
    const etat: EtatJauge = c.ratio >= 1 || !c.fits ? 'alerte' : c.ratio >= 0.7 ? 'attention' : 'normal';
    const max = Math.max(c.available_tokens, 1);
    const pourcent = (c.ratio * 100).toLocaleString('fr-FR', { maximumFractionDigits: 1 });
    const modele = this.catalogue()?.providers[c.provider]?.models.find(m => m.id === c.model);
    return {
      etat,
      mot: { normal: '✓ À l\'aise', attention: '⚠ Presque plein', alerte: '⛔ Trop long' }[etat],
      max,
      now: Math.min(Math.max(c.estimated_tokens, 0), max),
      largeur: Math.min(Math.max(c.ratio, 0), 1) * 100,
      texte: `≈ ${nombre(c.estimated_tokens)} / ${nombre(Math.max(c.available_tokens, 0))} jetons (${pourcent} %) — ${modele ? modele.label.split(' — ')[0] : c.model}`,
    };
  });
  readonly nombre = nombre;

  private shouldScroll = false;
  /** Numéro de la mesure la plus récente : une réponse d'estimation plus ancienne est ignorée. */
  private mesureSeq = 0;

  constructor() {
    effect(() => localStorage.setItem(LS.provider,     this.provider()));
    effect(() => localStorage.setItem(LS.claudeKey,    this.claudeKey()));
    effect(() => localStorage.setItem(LS.claudeModel,  this.claudeModel()));
    effect(() => localStorage.setItem(LS.mistralKey,   this.mistralKey()));
    effect(() => localStorage.setItem(LS.mistralModel, this.mistralModel()));

    // Recharge le chat depuis le state (lui-même alimenté par le backend) à chaque changement de spec
    effect(() => {
      const _sid = this.state.specSessionId();
      this.messages.set(this.state.chatHistory() as DisplayMessage[]);
      this.error.set('');
      this.selectedChoices.set(new Set());
    });

    // Estime le contexte dès que change ce qui partirait : spec, fournisseur, modèle, messages, brouillon.
    effect(onCleanup => {
      const spec = this.state.spec();
      const provider = this.provider();
      const model = provider === 'claude' ? this.claudeModel() : this.mistralModel();
      const brouillon = this.inputText().trim();
      const envoi: ChatMessage[] = brouillon
        ? [...this.messages(), { role: 'user', content: brouillon }]
        : this.messages();
      const seq = ++this.mesureSeq;
      let appel: Subscription | undefined;
      const minuterie = setTimeout(() => {
        appel = this.api.estimateChat(envoi, spec, provider, model).subscribe({
          next: res => { if (seq === this.mesureSeq && res?.context) this.contexte.set(res.context); },
          error: () => { /* la jauge garde sa dernière mesure ; le serveur reste juge à l'envoi */ },
        });
      }, DELAI_ESTIMATION_MS);
      onCleanup(() => { clearTimeout(minuterie); appel?.unsubscribe(); });
    });
  }

  ngOnInit(): void {
    this.provider.set((localStorage.getItem(LS.provider) ?? 'claude') as AiProvider);
    this.claudeKey.set(localStorage.getItem(LS.claudeKey)    ?? '');
    this.claudeModel.set(localStorage.getItem(LS.claudeModel)  ?? 'claude-sonnet-4-6');
    this.mistralKey.set(localStorage.getItem(LS.mistralKey)   ?? '');
    this.mistralModel.set(localStorage.getItem(LS.mistralModel) ?? 'mistral-small-latest');

    this.api.getModels().subscribe({
      next: cat => {
        if (!cat?.providers?.claude?.models || !cat.providers.mistral?.models) { this.modelsUnavailable.set(true); return; }
        this.catalogue.set(cat);
        this.modelsUnavailable.set(false);
        // Un modèle mémorisé qui n'est plus proposé cède la place à celui par défaut.
        const { claude, mistral } = cat.providers;
        if (!claude.models.some(m => m.id === this.claudeModel()))   this.claudeModel.set(claude.default);
        if (!mistral.models.some(m => m.id === this.mistralModel())) this.mistralModel.set(mistral.default);
      },
      error: () => this.modelsUnavailable.set(true),
    });
  }

  /** Les modèles d'un fournisseur ; sans catalogue, le seul modèle mémorisé. */
  private modelsOf(provider: AiProvider, memorise: string): ModelOption[] {
    return this.catalogue()?.providers[provider].models ?? [{ id: memorise, label: memorise }];
  }

  ngAfterViewChecked(): void {
    if (this.shouldScroll) { this.scrollToBottom(); this.shouldScroll = false; }
  }

  private scrollToBottom(): void {
    const el = this.messagesEl?.nativeElement;
    if (el) el.scrollTop = el.scrollHeight;
  }

  get activeKey():   string { return this.provider() === 'claude' ? this.claudeKey()   : this.mistralKey(); }
  get activeModel(): string { return this.provider() === 'claude' ? this.claudeModel() : this.mistralModel(); }

  toggleSettings(): void { this.showSettings.update(v => !v); }
  toggleTutorial(): void { this.showTutorial.update(v => !v); }

  useStarter(text: string): void { this.inputText.set(text); this.send(); }

  // ── Gestion des choix ──────────────────────────────────────────────────────

  pickSingle(choice: string): void {
    this.inputText.set(choice);
    this.send();
  }

  toggleMulti(choice: string): void {
    this.selectedChoices.update(set => {
      const next = new Set(set);
      if (next.has(choice)) next.delete(choice);
      else next.add(choice);
      return next;
    });
  }

  isSelected(choice: string): boolean {
    return this.selectedChoices().has(choice);
  }

  sendSelection(): void {
    const sel = Array.from(this.selectedChoices());
    if (!sel.length) return;
    this.inputText.set(sel.join(', '));
    this.selectedChoices.set(new Set());
    this.send();
  }

  focusOther(): void {
    this.chatInputEl?.nativeElement.focus();
  }

  // ── Envoi ──────────────────────────────────────────────────────────────────

  send(): void {
    const text = this.inputText().trim();
    if (!text || this.loading()) return;
    if (!this.activeKey) {
      this.error.set('Clé API manquante — ouvrez ⚙ et renseignez votre clé.');
      return;
    }

    this.messages.update(msgs => [...msgs, { role: 'user', content: text }]);
    this.inputText.set('');
    this.selectedChoices.set(new Set());
    this.loading.set(true);
    this.error.set('');
    this.shouldScroll = true;

    this.api.chat(this.messages(), this.state.spec(), this.provider(), this.activeKey, this.activeModel)
      .subscribe({
        next: res => {
          const updated: DisplayMessage[] = [...this.messages(), {
            role: 'assistant', content: res.content,
            spec_patch: res.spec_patch ?? null,
            patch_summary: res.patch_summary ?? null,
            choices:    res.choices    ?? null,
            applied: 'none',
          }];
          if (res.context) { this.mesureSeq++; this.contexte.set(res.context); }
          this.messages.set(updated);
          this._persistChat(updated);
          this.loading.set(false);
          this.shouldScroll = true;
        },
        error: err => {
          const corps = err.error;
          if (corps?.context) { this.mesureSeq++; this.contexte.set(corps.context); }
          if (err.status === 413) {
            // Rien n'est parti : le message refusé quitte la liste et son texte revient dans la saisie.
            this.error.set(corps?.error ?? 'Cet envoi ne tient pas dans le modèle choisi.');
            const msgs = this.messages();
            const dernier = msgs[msgs.length - 1];
            if (dernier?.role === 'user' && dernier.content === text) this.messages.set(msgs.slice(0, -1));
            this.inputText.set(text);
          } else {
            this.error.set(`Erreur : ${corps?.error ?? err.message ?? 'Erreur inconnue'}`);
          }
          this.loading.set(false);
          this.shouldScroll = true;
        },
      });
  }

  merge(msgIndex: number): void { this.applyPatch(msgIndex, 'merge'); }

  replace(msgIndex: number): void {
    if (!confirm('Remplacer toute la spécification par cette proposition ? (annulable juste après)')) return;
    this.applyPatch(msgIndex, 'replace');
  }

  private applyPatch(msgIndex: number, mode: PatchMode): void {
    const msg = this.messages()[msgIndex];
    if (!msg?.spec_patch || this.patchBusy()) return;
    this.patchBusy.set(true);
    this.error.set('');
    this.state.applyAgentPatch(msg.spec_patch, mode).subscribe({
      next: application => {
        this.markPatch(msgIndex, mode === 'merge' ? 'merged' : 'replaced', application.id);
        this.patchBusy.set(false);
      },
      error: err => this.patchFailed(err),
    });
  }

  undo(msgIndex: number): void {
    const id = this.messages()[msgIndex]?.application_id;
    if (id == null || this.patchBusy()) return;
    if (!confirm('Annuler ce patch ? La spécification revient à son état d\'avant ; ce que vous avez modifié depuis est perdu.')) return;
    this.patchBusy.set(true);
    this.error.set('');
    this.state.undoAgentPatch(id).subscribe({
      next: () => { this.markPatch(msgIndex, 'none', null); this.patchBusy.set(false); },
      error: err => this.patchFailed(err),
    });
  }

  /** L'état « appliqué » est enregistré avec la conversation : il survit à un rechargement. */
  private markPatch(msgIndex: number, applied: AppliedState, applicationId: number | null): void {
    const updated = this.messages().map((m, i) =>
      i === msgIndex ? { ...m, applied, application_id: applicationId } : m);
    this.messages.set(updated);
    this._persistChat(updated);
  }

  private patchFailed(err: { error?: { error?: string; details?: string[] }; message?: string }): void {
    const details = err.error?.details?.length ? ' ' + err.error.details.join(' ; ') : '';
    this.error.set(`${err.error?.error ?? err.message ?? 'Erreur inconnue'}${details}`);
    this.patchBusy.set(false);
    this.shouldScroll = true;
  }

  isApplied(msg: DisplayMessage): boolean { return msg.applied === 'merged' || msg.applied === 'replaced'; }

  /** Seul le dernier patch appliqué s'annule : c'est le seul qui porte le bouton. */
  canUndo(msgIndex: number): boolean {
    const msgs = this.messages();
    if (msgs[msgIndex]?.application_id == null || !this.isApplied(msgs[msgIndex])) return false;
    return !msgs.some((m, i) => i !== msgIndex && this.isApplied(m) && (m.application_id ?? 0) > msgs[msgIndex].application_id!);
  }

  /** Résumé calculé par le serveur ; les messages d'avant ce calcul n'en ont pas. */
  patchSummary(msg: DisplayMessage): string {
    return msg.patch_summary ?? 'modifications de la spécification';
  }

  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (!this.depasse()) this.send();
    }
  }

  clearHistory(): void {
    if (!confirm("Effacer tout l'historique de conversation ? Cette action est irréversible.")) return;
    this.messages.set([]);
    this.error.set('');
    this.selectedChoices.set(new Set());
    this._persistChat([]);
  }

  private _persistChat(msgs: DisplayMessage[]): void {
    const id = this.state.savedId();
    if (id == null) return;
    this.state.setChatHistory(msgs as PersistedChatMessage[]);
    this.api.saveChatHistory(id, msgs as PersistedChatMessage[]).subscribe();
  }

  formatContent(content: string): string {
    return content
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br>');
  }
}
