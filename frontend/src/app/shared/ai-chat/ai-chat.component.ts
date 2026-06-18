import { Component, inject, signal, ViewChild, ElementRef, AfterViewChecked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BuilderApiService } from '../../core/builder-api.service';
import { BuilderStateService } from '../../core/builder-state.service';
import { ChatMessage, AiProvider } from '../../models/app-spec.model';

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

  messages = signal<ChatMessage[]>([]);
  inputText = signal('');
  loading = signal(false);
  error = signal('');
  provider = signal<AiProvider>('claude');
  apiKey = signal('');
  showSettings = signal(false);

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

  send(): void {
    const text = this.inputText().trim();
    if (!text || this.loading()) return;
    if (!this.apiKey()) {
      this.error.set('Veuillez configurer une clé API dans les paramètres.');
      return;
    }

    const userMsg: ChatMessage = { role: 'user', content: text };
    this.messages.update(msgs => [...msgs, userMsg]);
    this.inputText.set('');
    this.loading.set(true);
    this.error.set('');
    this.shouldScroll = true;

    const allMessages = [...this.messages()];

    this.api.chat(allMessages, this.state.spec(), this.provider(), this.apiKey())
      .subscribe({
        next: res => {
          const assistantMsg: ChatMessage = { role: 'assistant', content: res.content };
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
    return content.replace(/\n/g, '<br>');
  }
}
