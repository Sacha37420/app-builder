import { Component, computed, inject } from '@angular/core';
import { GraphNode, GraphSequence } from '../../models/app-spec.model';
import { OverviewStore } from './overview.store';

interface Lifeline { key: string; label: string; node: GraphNode | null; }
interface Msg { from: number; to: number; label: string; start: number; end: number; dir: 'r' | 'l' | 'self'; }
interface Seq { pipeline: GraphNode | null; title: string; lifelines: Lifeline[]; messages: Msg[]; }

const PSEUDO: Record<string, string> = { user: 'Utilisateur', utilisateur: 'Utilisateur', browser: 'Navigateur' };

/**
 * Diagrammes de séquence de la vue « Flux » (`sequences` du graphe v2) : lignes de
 * vie en colonnes, une ligne par message, flèche de la colonne d'origine à la
 * colonne cible. Une grille CSS suffit ; la liste ordonnée qui suit chaque
 * diagramme en est l'équivalent textuel.
 */
@Component({
  selector: 'app-ov-sequences',
  standalone: true,
  styleUrl: './sequences.component.scss',
  template: `
    @for (s of seqs(); track $index) {
      <section class="ov-card k-green ov-seq">
        <h3 class="ov-name">
          @if (s.pipeline) {
            <button type="button" class="ov-link" [class.is-focus]="store.isFocus(s.pipeline.id)" (click)="store.select(s.pipeline)">{{ s.title }}</button>
          } @else { {{ s.title }} }
        </h3>
        @if (store.mode() === 'carte') {
          <div class="ov-table-wrap" aria-hidden="true">
            <div class="ov-seq-grid" [style.grid-template-columns]="'repeat(' + s.lifelines.length + ', minmax(120px, 1fr))'">
              @for (l of s.lifelines; track $index) {
                <div class="ov-seq-head" [style.grid-column]="$index + 1">{{ l.label }}</div>
              }
              @for (m of s.messages; track $index; let row = $index) {
                @for (l of s.lifelines; track $index) {
                  <div class="ov-seq-life" [style.grid-column]="$index + 1" [style.grid-row]="row + 2"></div>
                }
                <div class="ov-seq-msg" [class]="'ov-seq-msg dir-' + m.dir"
                     [style.grid-column]="(m.start + 1) + ' / ' + (m.end + 2)" [style.grid-row]="row + 2">
                  <span class="ov-seq-label">{{ row + 1 }}. {{ m.label }}</span>
                </div>
              }
            </div>
          </div>
        }
        <ol class="ov-seq-list">
          @for (m of s.messages; track $index) {
            <li>{{ name(s, m.from) }} <span aria-hidden="true">→</span><span class="ov-sr">vers</span> {{ name(s, m.to) }} : {{ m.label }}</li>
          }
        </ol>
      </section>
    }
  `,
})
export class SequencesComponent {
  store = inject(OverviewStore);

  seqs = computed<Seq[]>(() => {
    const filter = this.store.filter();
    return (this.store.graph()?.sequences ?? [])
      .map(s => this.build(s))
      .filter(s => !filter || !s.pipeline || this.store.visible(s.pipeline));
  });

  private build(s: GraphSequence): Seq {
    const lifelines: Lifeline[] = (s.lifelines ?? []).map(k => {
      const node = this.store.node(k);
      return { key: k, node, label: node ? `${this.store.kind(node).label} ${node.label}` : (PSEUDO[k] ?? k) };
    });
    const at = (v: number | string): number =>
      typeof v === 'number' ? v : Math.max(0, lifelines.findIndex(l => l.key === v));
    const messages: Msg[] = (s.messages ?? []).map(m => {
      const from = at(m.from), to = at(m.to);
      return { from, to, label: m.label, start: Math.min(from, to), end: Math.max(from, to),
               dir: from === to ? 'self' : to > from ? 'r' : 'l' };
    });
    const pipeline = this.store.node(s.pipeline);
    return { pipeline, title: pipeline?.label ?? s.pipeline, lifelines, messages };
  }

  name(s: Seq, i: number): string { return s.lifelines[i]?.label ?? '?'; }
}
