import { Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';

/**
 * « ← Retour à la vue d'ensemble » quand une page d'édition a été ouverte depuis
 * l'inspecteur (paramètre `retour`). Seule une adresse de la vue d'ensemble est
 * suivie : le paramètre ne peut pas servir à mener ailleurs.
 */
@Component({
  selector: 'app-back-link',
  standalone: true,
  template: `
    @if (target(); as t) {
      <button type="button" class="back-link" (click)="go(t)">
        <span aria-hidden="true">←</span> Retour à la vue d'ensemble
      </button>
    }
  `,
  styles: `
    .back-link {
      display: inline-flex; align-items: center; gap: var(--space-2);
      min-height: 44px; padding: 0 var(--space-3); margin-bottom: var(--space-2);
      background: none; border: 1px solid var(--border); border-radius: var(--radius-sm);
      color: var(--accent); font: inherit; font-size: var(--text-sm); font-weight: 600; cursor: pointer;
      &:hover { background: var(--overlay-hover); }
      &:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    }
  `,
})
export class BackLinkComponent {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private params = toSignal(this.route.queryParamMap);

  target = computed(() => {
    const r = this.params()?.get('retour') ?? '';
    return /^\/overview(\?[^\s]*)?$/.test(r) ? r : null;
  });

  go(url: string): void { this.router.navigateByUrl(url); }
}
