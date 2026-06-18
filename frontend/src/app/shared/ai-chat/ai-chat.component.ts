import { Component, inject, signal, effect, ViewChild, ElementRef, AfterViewChecked, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BuilderApiService } from '../../core/builder-api.service';
import { BuilderStateService } from '../../core/builder-state.service';
import { ChatMessage, AiProvider, AgentPatch } from '../../models/app-spec.model';

type AppliedState = 'none' | 'merged' | 'replaced';

interface DisplayMessage extends ChatMessage {
  applied?: AppliedState;
}

interface ModelOption { id: string; label: string; }

const CLAUDE_MODELS: ModelOption[] = [
  { id: 'claude-opus-4-8',           label: 'Opus 4.8 — Ultra-puissant' },
  { id: 'claude-sonnet-4-6',         label: 'Sonnet 4.6 — Recommandé ★' },
  { id: 'claude-haiku-4-5-20251001', label: 'Haiku 4.5 — Rapide / économique' },
];

const MISTRAL_MODELS: ModelOption[] = [
  { id: 'mistral-large-latest', label: 'Large — Ultra-puissant' },
  { id: 'mistral-small-latest', label: 'Small — Recommandé ★' },
  { id: 'codestral-latest',     label: 'Codestral — Spécialisé code' },
  { id: 'open-mistral-nemo',    label: 'Nemo — Gratuit (tier libre)' },
];

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
  @ViewChild('messagesEl') messagesEl?: ElementRef<HTMLDivElement>;

  private api = inject(BuilderApiService);
  state = inject(BuilderStateService);

  messages    = signal<DisplayMessage[]>([]);
  inputText   = signal('');
  loading     = signal(false);
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

  readonly claudeModels  = CLAUDE_MODELS;
  readonly mistralModels = MISTRAL_MODELS;
  readonly starters      = STARTER_PROMPTS;

  private shouldScroll = false;

  constructor() {
    effect(() => localStorage.setItem(LS.provider,     this.provider()));
    effect(() => localStorage.setItem(LS.claudeKey,    this.claudeKey()));
    effect(() => localStorage.setItem(LS.claudeModel,  this.claudeModel()));
    effect(() => localStorage.setItem(LS.mistralKey,   this.mistralKey()));
    effect(() => localStorage.setItem(LS.mistralModel, this.mistralModel()));
  }

  ngOnInit(): void {
    this.provider.set((localStorage.getItem(LS.provider) ?? 'claude') as AiProvider);
    this.claudeKey.set(localStorage.getItem(LS.claudeKey)    ?? '');
    this.claudeModel.set(localStorage.getItem(LS.claudeModel)  ?? 'claude-sonnet-4-6');
    this.mistralKey.set(localStorage.getItem(LS.mistralKey)   ?? '');
    this.mistralModel.set(localStorage.getItem(LS.mistralModel) ?? 'mistral-small-latest');
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

  send(): void {
    const text = this.inputText().trim();
    if (!text || this.loading()) return;
    if (!this.activeKey) {
      this.error.set('Clé API manquante — ouvrez ⚙ et renseignez votre clé.');
      return;
    }

    this.messages.update(msgs => [...msgs, { role: 'user', content: text }]);
    this.inputText.set('');
    this.loading.set(true);
    this.error.set('');
    this.shouldScroll = true;

    this.api.chat(this.messages(), this.state.spec(), this.provider(), this.activeKey, this.activeModel)
      .subscribe({
        next: res => {
          this.messages.update(msgs => [...msgs, {
            role: 'assistant', content: res.content,
            spec_patch: res.spec_patch ?? null, applied: 'none',
          }]);
          this.loading.set(false);
          this.shouldScroll = true;
        },
        error: err => {
          this.error.set(`Erreur : ${err.error?.error ?? err.message ?? 'Erreur inconnue'}`);
          this.loading.set(false);
        },
      });
  }

  merge(msgIndex: number): void {
    const msg = this.messages()[msgIndex];
    if (!msg?.spec_patch) return;
    this.state.mergeFromAgent(msg.spec_patch);
    this.messages.update(msgs =>
      msgs.map((m, i) => i === msgIndex ? { ...m, applied: 'merged' as AppliedState } : m));
  }

  replace(msgIndex: number): void {
    const msg = this.messages()[msgIndex];
    if (!msg?.spec_patch) return;
    this.state.replaceFromAgent(msg.spec_patch);
    this.messages.update(msgs =>
      msgs.map((m, i) => i === msgIndex ? { ...m, applied: 'replaced' as AppliedState } : m));
  }

  patchSummary(patch: AgentPatch): string { return this.state.patchSummary(patch); }

  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); this.send(); }
  }

  clearHistory(): void { this.messages.set([]); this.error.set(''); }

  formatContent(content: string): string {
    return content
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br>');
  }
}
