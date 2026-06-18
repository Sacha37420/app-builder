import { Component, inject, signal, ViewChild, ElementRef, AfterViewChecked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BuilderApiService } from '../../core/builder-api.service';
import { BuilderStateService } from '../../core/builder-state.service';
import { ChatMessage, AiProvider, AgentPatch } from '../../models/app-spec.model';

type AppliedState = 'none' | 'merged' | 'replaced';

interface DisplayMessage extends ChatMessage {
  applied?: AppliedState;
}

const STARTER_PROMPTS = [
  'Je veux une app de gestion de stock avec tableau de bord et alertes de seuil',
  'Je veux un outil de suivi de tâches pour une petite équipe',
  'Je veux un site e-commerce avec catalogue, panier et commandes',
  'Je veux une app de réservation (créneaux, clients, confirmations)',
];

@Component({
  selector: 'app-ai-chat',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './ai-chat.component.html',
  styleUrl: './ai-chat.component.scss',
})
export class AiChatComponent implements AfterViewChecked {
  @ViewChild('messagesEl') messagesEl?: ElementRef<HTMLDivElement>;

  private api = inject(BuilderApiService);
  state = inject(BuilderStateService);

  messages = signal<DisplayMessage[]>([]);
  inputText = signal('');
  loading = signal(false);
  error = signal('');
  provider = signal<AiProvider>('claude');
  apiKey = signal('');
  showSettings = signal(false);

  readonly starters = STARTER_PROMPTS;
  private shouldScroll = false;

  ngAfterViewChecked(): void {
    if (this.shouldScroll) {
      this.scrollToBottom();
      this.shouldScroll = false;
    }
  }

  private scrollToBottom(): void {
    const el = this.messagesEl?.nativeElement;
    if (el) el.scrollTop = el.scrollHeight;
  }

  toggleSettings(): void {
    this.showSettings.update(v => !v);
  }

  useStarter(text: string): void {
    this.inputText.set(text);
    this.send();
  }

  send(): void {
    const text = this.inputText().trim();
    if (!text || this.loading()) return;
    if (!this.apiKey()) {
      this.error.set('Veuillez configurer une clé API dans les paramètres (icône ⚙).');
      return;
    }

    const userMsg: DisplayMessage = { role: 'user', content: text };
    this.messages.update(msgs => [...msgs, userMsg]);
    this.inputText.set('');
    this.loading.set(true);
    this.error.set('');
    this.shouldScroll = true;

    this.api.chat(this.messages(), this.state.spec(), this.provider(), this.apiKey())
      .subscribe({
        next: res => {
          const assistantMsg: DisplayMessage = {
            role: 'assistant',
            content: res.content,
            spec_patch: res.spec_patch ?? null,
            applied: 'none',
          };
          this.messages.update(msgs => [...msgs, assistantMsg]);
          this.loading.set(false);
          this.shouldScroll = true;
        },
        error: err => {
          const detail = err.error?.error ?? err.message ?? 'Erreur inconnue';
          this.error.set(`Erreur : ${detail}`);
          this.loading.set(false);
        },
      });
  }

  merge(msgIndex: number): void {
    const msg = this.messages()[msgIndex];
    if (!msg?.spec_patch) return;
    this.state.mergeFromAgent(msg.spec_patch);
    this.messages.update(msgs =>
      msgs.map((m, i) => i === msgIndex ? { ...m, applied: 'merged' as AppliedState } : m),
    );
  }

  replace(msgIndex: number): void {
    const msg = this.messages()[msgIndex];
    if (!msg?.spec_patch) return;
    this.state.replaceFromAgent(msg.spec_patch);
    this.messages.update(msgs =>
      msgs.map((m, i) => i === msgIndex ? { ...m, applied: 'replaced' as AppliedState } : m),
    );
  }

  patchSummary(patch: AgentPatch): string {
    return this.state.patchSummary(patch);
  }

  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.send();
    }
  }

  clearHistory(): void {
    this.messages.set([]);
    this.error.set('');
  }

  formatContent(content: string): string {
    return content
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br>');
  }
}
