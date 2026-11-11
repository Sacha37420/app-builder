import { Component, inject, signal, computed, effect, ViewChild, ElementRef, AfterViewChecked, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { BuilderApiService } from '../../core/builder-api.service';
import { BuilderStateService } from '../../core/builder-state.service';
import { Subscription, switchMap } from 'rxjs';
import {
  AiProvider, ChatContext, ChatMessage, ChatUsage, ModelCatalogue, PersistedChatMessage, ProposalState,
} from '../../models/app-spec.model';

type DisplayMessage = PersistedChatMessage;

interface ModelOption { id: string; label: string; tools?: boolean; }

/** Préfixe d'un jeton d'abonnement Claude : il ne s'utilise que dans Claude Code (contrat §7). */
const PREFIXE_JETON_ABONNEMENT = 'sk-ant-oat';
const MESSAGE_JETON_ABONNEMENT =
  "Ce jeton d'abonnement Claude (sk-ant-oat…) ne s'utilise que dans Claude Code : App Builder ne le garde pas. "
  + 'Déposez ici une clé API (sk-ant-api…), ou pilotez la spécification depuis votre Claude Code '
  + '(page « Connexion IA »).';

/** Ce que l'agent sait d'une de ses propositions au tour suivant : du texte, jamais les opérations. */
const ETAT_POUR_IA: Record<ProposalState, string> = {
  proposed: 'proposition non appliquée',
  applied: "proposition appliquée par l'utilisateur",
  undone: "proposition appliquée puis annulée par l'utilisateur",
  stale: 'proposition périmée : la spécification a changé avant son application',
  refused: 'proposition refusée par le serveur',
};

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
  claudeModel:   'ai_claude_model',
  mistralModel:  'ai_mistral_model',
};

/**
 * Anciennes entrées où les clés étaient gardées en clair dans le navigateur.
 * Effacées à l'ouverture, SANS être envoyées au serveur : l'utilisateur ressaisit
 * sa clé une fois, elle va alors au coffre du serveur (`/api/ai-keys/`).
 */
const ANCIENNES_CLES = ['ai_claude_key', 'ai_mistral_key'];

@Component({
  selector: 'app-ai-chat',
  standalone: true,
  imports: [FormsModule, RouterLink],
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
  // Saisie en cours seulement (jamais persistée, vidée après l'envoi au coffre).
  claudeKey    = signal('');
  claudeModel  = signal('claude-sonnet-4-6');
  mistralKey   = signal('');
  mistralModel = signal('mistral-small-latest');
  // Ce que dit le coffre du serveur : une clé est-elle enregistrée ? (jamais la clé)
  claudeConfigured  = signal(false);
  mistralConfigured = signal(false);
  keysKnown         = signal(false);
  keySaving         = signal(false);
  keyMessage        = signal('');

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
  /** Consommation du dernier tour (I4 `usage`). */
  usage        = signal<ChatUsage | null>(null);
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
    effect(() => localStorage.setItem(LS.claudeModel,  this.claudeModel()));
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
      const appId = this.state.savedId();
      const seq = ++this.mesureSeq;
      let appel: Subscription | undefined;
      const minuterie = setTimeout(() => {
        appel = this.api.estimateChat(appId, this.historyForAi(envoi), spec, provider, model).subscribe({
          next: res => { if (seq === this.mesureSeq && res?.context) this.contexte.set(res.context); },
          error: () => { /* la jauge garde sa dernière mesure ; le serveur reste juge à l'envoi */ },
        });
      }, DELAI_ESTIMATION_MS);
      onCleanup(() => { clearTimeout(minuterie); appel?.unsubscribe(); });
    });
  }

  ngOnInit(): void {
    this.provider.set((localStorage.getItem(LS.provider) ?? 'claude') as AiProvider);
    this.claudeModel.set(localStorage.getItem(LS.claudeModel)  ?? 'claude-sonnet-4-6');
    for (const ancienne of ANCIENNES_CLES) {
      try { localStorage.removeItem(ancienne); } catch { /* stockage indisponible : rien à effacer */ }
    }
    this.refreshKeys();
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

  /** Libellé d'un modèle dans la liste : un modèle sans outils passe par une sortie structurée (moins sûre). */
  modelLabel(m: ModelOption): string {
    return m.tools === false ? `${m.label} — sans outils` : m.label;
  }

  ngAfterViewChecked(): void {
    if (this.shouldScroll) { this.scrollToBottom(); this.shouldScroll = false; }
  }

  private scrollToBottom(): void {
    const el = this.messagesEl?.nativeElement;
    if (el) el.scrollTop = el.scrollHeight;
  }

  /** Une clé du fournisseur choisi est-elle au coffre ? (inconnu ⇒ on laisse le serveur juger) */
  get activeKeyConfigured(): boolean {
    if (!this.keysKnown()) return true;
    return this.provider() === 'claude' ? this.claudeConfigured() : this.mistralConfigured();
  }

  // ── Coffre des clés (serveur) ──────────────────────────────────────────────

  refreshKeys(): void {
    this.api.getAiKeys().subscribe({
      next: etat => {
        this.claudeConfigured.set(!!etat?.claude_key_configured);
        this.mistralConfigured.set(!!etat?.mistral_key_configured);
        this.keysKnown.set(true);
      },
      error: () => this.keysKnown.set(false),
    });
  }

  /** Envoie la clé saisie au coffre du serveur ; `''` la retire. */
  saveKey(provider: AiProvider, retirer = false): void {
    const saisie = provider === 'claude' ? this.claudeKey : this.mistralKey;
    const valeur = retirer ? '' : saisie().trim();
    if (!retirer && !valeur) return;
    if (!retirer && provider === 'claude' && valeur.startsWith(PREFIXE_JETON_ABONNEMENT)) {
      // Refusé avant tout envoi : ce jeton ne doit jamais quitter le navigateur vers App Builder.
      saisie.set('');
      this.keyMessage.set(MESSAGE_JETON_ABONNEMENT);
      return;
    }
    if (retirer && !confirm('Retirer la clé enregistrée sur le serveur ?')) return;
    this.keySaving.set(true);
    this.keyMessage.set('');
    const corps = provider === 'claude' ? { claude_key: valeur } : { mistral_key: valeur };
    this.api.putAiKeys(corps).subscribe({
      next: () => {
        saisie.set('');
        this.keySaving.set(false);
        this.keyMessage.set(retirer ? 'Clé retirée.' : 'Clé enregistrée sur le serveur.');
        this.refreshKeys();
      },
      error: err => {
        this.keySaving.set(false);
        this.keyMessage.set(err?.error?.code === 'oauth_token_refused'
          ? MESSAGE_JETON_ABONNEMENT
          : `Clé non enregistrée : ${err?.error?.error ?? 'erreur du serveur'}`);
      },
    });
  }
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

  /**
   * L'historique tel qu'il repart vers le serveur : du texte seulement (I4). Une
   * proposition y est résumée en une phrase, avec ce que l'utilisateur en a fait :
   * l'agent ne revoit jamais les opérations elles-mêmes.
   */
  private historyForAi(msgs: ChatMessage[]): ChatMessage[] {
    return msgs.map(m => {
      if (m.role !== 'assistant' || !m.proposal) return { role: m.role, content: m.content };
      const etat = ETAT_POUR_IA[m.proposal_state ?? 'proposed'];
      return { role: m.role, content: `${m.content}\n\n[${etat} : ${m.proposal.resume?.texte ?? ''}]` };
    });
  }

  send(): void {
    const text = this.inputText().trim();
    if (!text || this.loading()) return;
    if (!this.activeKeyConfigured) {
      this.error.set('Clé API non enregistrée — ouvrez ⚙ et enregistrez votre clé.');
      return;
    }

    this.messages.update(msgs => [...msgs, { role: 'user', content: text }]);
    this.inputText.set('');
    this.selectedChoices.set(new Set());
    this.loading.set(true);
    this.error.set('');
    this.shouldScroll = true;
    const provider = this.provider();
    const model = this.activeModel;

    // Le serveur lit la spec en base (I4 : `app_id`) : ce qui est en attente est enregistré d'abord.
    this.state.ensureSaved().pipe(
      switchMap(id => this.api.chat(id, this.historyForAi(this.messages()), provider, model)),
    ).subscribe({
      next: res => {
        const updated: DisplayMessage[] = [...this.messages(), {
          role: 'assistant', content: res.content,
          choices: res.choices ?? null,
          proposal: res.proposal ?? null,
          proposal_state: res.proposal ? 'proposed' : undefined,
          truncated: res.truncated || undefined,
        }];
        if (res.context) { this.mesureSeq++; this.contexte.set(res.context); }
        this.usage.set(res.usage ?? null);
        this.messages.set(updated);
        this._persistChat(updated);
        this.loading.set(false);
        this.shouldScroll = true;
      },
      error: (err: HttpErrorResponse) => {
        const corps = err.error;
        if (corps?.context) { this.mesureSeq++; this.contexte.set(corps.context); }
        if (corps?.code === 'key_not_configured') this.refreshKeys();
        if (err.status === 413 || err.status === 400 || this.state.savedId() === null) {
          // Rien n'est parti : le message refusé quitte la liste et son texte revient dans la saisie.
          const msgs = this.messages();
          const dernier = msgs[msgs.length - 1];
          if (dernier?.role === 'user' && dernier.content === text) this.messages.set(msgs.slice(0, -1));
          this.inputText.set(text);
        }
        if (err.status === 413) {
          this.error.set(corps?.error ?? 'Cet envoi ne tient pas dans le modèle choisi.');
        } else if (this.state.saveStatus() === 'error') {
          this.error.set("La spécification n'a pas pu être enregistrée : corrigez-la avant d'interroger l'agent.");
        } else {
          this.error.set(`Erreur : ${corps?.error ?? corps?.detail ?? err.message ?? 'Erreur inconnue'}`);
        }
        this.loading.set(false);
        this.shouldScroll = true;
      },
    });
  }

  // ── Propositions (I4) ──────────────────────────────────────────────────────

  apply(msgIndex: number): void {
    const msg = this.messages()[msgIndex];
    const p = msg?.proposal;
    if (!p || this.patchBusy() || msg.proposal_state !== 'proposed') return;
    if (p.erreurs?.length) return;
    if (p.resume?.destructive
        && !confirm('Cette proposition retire, renomme ou raccourcit des éléments de la spécification. '
          + "L'appliquer quand même ? (annulable juste après)")) return;
    this.patchBusy.set(true);
    this.error.set('');
    this.state.applyOperations(p.operations, p.base_version).subscribe({
      next: application => {
        this.markProposal(msgIndex, { proposal_state: 'applied', application_id: application.id, proposal_errors: undefined });
        this.patchBusy.set(false);
      },
      error: (err: HttpErrorResponse) => this.applyFailed(msgIndex, err),
    });
  }

  private applyFailed(msgIndex: number, err: HttpErrorResponse): void {
    const corps = err.error ?? {};
    if (err.status === 409 && corps.code === 'version_perimee') {
      // La spec a changé depuis la proposition : on relit la version du serveur, puis
      // l'utilisateur peut redemander une proposition sur cette version.
      this.markProposal(msgIndex, { proposal_state: 'stale' });
      this.state.reloadFromServer().subscribe({
        next: () => this.patchBusy.set(false),
        error: () => { this.patchBusy.set(false); this.error.set('La spécification n\'a pas pu être relue.'); },
      });
      return;
    }
    if (err.status === 400) {
      const erreurs: string[] = Array.isArray(corps.erreurs) && corps.erreurs.length
        ? corps.erreurs.map(String) : [String(corps.error ?? 'Proposition refusée par le serveur.')];
      this.markProposal(msgIndex, { proposal_state: 'refused', proposal_errors: erreurs });
      this.patchBusy.set(false);
      return;
    }
    this.error.set(`${corps.error ?? corps.detail ?? err.message ?? 'Erreur inconnue'}`);
    this.patchBusy.set(false);
    this.shouldScroll = true;
  }

  /** Après un 409 : relance l'agent pour qu'il refasse sa proposition sur la version actuelle. */
  askAgain(): void {
    this.inputText.set('La spécification a changé depuis ta dernière proposition : refais-la sur la version actuelle.');
    this.send();
  }

  /** Après un refus du serveur : renvoie les erreurs à l'agent, pour qu'il corrige sa proposition. */
  askFix(msgIndex: number): void {
    const erreurs = this.messages()[msgIndex]?.proposal_errors ?? [];
    this.inputText.set(`Ta proposition a été refusée par le serveur :\n- ${erreurs.join('\n- ')}\nCorrige-la.`);
    this.send();
  }

  undo(msgIndex: number): void {
    const id = this.messages()[msgIndex]?.application_id;
    if (id == null || this.patchBusy()) return;
    if (!confirm('Annuler cette application ? La spécification revient à son état d\'avant ; ce que vous avez modifié depuis est perdu.')) return;
    this.patchBusy.set(true);
    this.error.set('');
    this.state.undoAgentPatch(id).subscribe({
      next: () => { this.markProposal(msgIndex, { proposal_state: 'undone' }); this.patchBusy.set(false); },
      error: (err: HttpErrorResponse) => {
        this.error.set(`${err.error?.error ?? err.message ?? 'Erreur inconnue'}`);
        this.patchBusy.set(false);
      },
    });
  }

  /** L'état d'une proposition est enregistré avec la conversation : il survit à un rechargement. */
  private markProposal(msgIndex: number, patch: Partial<DisplayMessage>): void {
    const updated = this.messages().map((m, i) => (i === msgIndex ? { ...m, ...patch } : m));
    this.messages.set(updated);
    this._persistChat(updated);
    this.shouldScroll = true;
  }

  /** Seule la dernière application encore en place s'annule : c'est la seule qui porte le bouton. */
  canUndo(msgIndex: number): boolean {
    const msgs = this.messages();
    const m = msgs[msgIndex];
    if (m?.application_id == null || m.proposal_state !== 'applied') return false;
    return !msgs.some((o, i) => i !== msgIndex && o.proposal_state === 'applied' && (o.application_id ?? 0) > m.application_id!);
  }

  /** Message de l'ancien protocole (patch complet) : il ne s'applique plus, il se redemande. */
  isLegacyPatch(msg: DisplayMessage): boolean {
    return msg.role === 'assistant' && !msg.proposal && !!msg.spec_patch;
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
