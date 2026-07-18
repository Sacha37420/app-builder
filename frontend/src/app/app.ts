import { Component, ElementRef, HostListener, inject, signal, ViewChild } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { KeycloakService } from './core/keycloak.service';
import { ThemeService } from './core/theme.service';
import { BuilderStateService } from './core/builder-state.service';

interface NavItem {
  label: string;
  abbr: string;
  path: string;
  exact?: boolean;
}

const MOBILE_CLOSE_ANIM_MS = 220;

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, NgTemplateOutlet],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class AppComponent {
  protected kc = inject(KeycloakService);
  protected theme = inject(ThemeService);
  protected state = inject(BuilderStateService);

  collapsed = signal(false);
  mobileOpen = signal(false);
  mobileClosing = signal(false);

  saving = signal(false);
  saveError = signal('');

  protected noop = (): void => {};
  protected closeMobileFn = (): void => this.closeMobile();

  readonly navItems: NavItem[] = [
    { path: '/',             label: 'Canvas',       abbr: 'Cv', exact: true },
    { path: '/models',       label: '① Modèles',    abbr: 'Mo' },
    { path: '/endpoints',    label: '② API',        abbr: 'Ap' },
    { path: '/pages-config', label: '③ Pages',      abbr: 'Pa' },
    { path: '/pipelines',    label: '④ Pipelines',  abbr: 'Pi' },
    { path: '/preview',      label: 'Code',         abbr: 'Cd' },
    { path: '/infra',        label: 'Infra',        abbr: 'In' },
  ];

  @ViewChild('closeBtn') private closeBtnRef?: ElementRef<HTMLButtonElement>;
  @ViewChild('burgerBtn') private burgerBtnRef?: ElementRef<HTMLButtonElement>;

  toggleCollapsed(): void {
    this.collapsed.update(v => !v);
  }

  openMobile(): void {
    this.mobileOpen.set(true);
    this.mobileClosing.set(false);
    document.body.style.overflow = 'hidden';
    setTimeout(() => this.closeBtnRef?.nativeElement.focus());
  }

  closeMobile(): void {
    if (!this.mobileOpen() || this.mobileClosing()) return;
    this.mobileClosing.set(true);
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    setTimeout(() => {
      this.mobileOpen.set(false);
      this.mobileClosing.set(false);
      document.body.style.overflow = '';
      this.burgerBtnRef?.nativeElement.focus();
    }, reduced ? 0 : MOBILE_CLOSE_ANIM_MS);
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.mobileOpen()) this.closeMobile();
  }

  get username(): string {
    return this.kc.username || this.kc.email;
  }

  logout(): void {
    this.kc.logout();
  }

  /** Reprend exactement la logique de l'ancienne navbar (shared/navbar/navbar.component.ts). */
  saveNow(): void {
    this.saving.set(true);
    this.saveError.set('');
    this.state.saveNow().subscribe({
      next: () => this.saving.set(false),
      error: err => {
        this.saveError.set(err.error?.detail ?? 'Erreur sauvegarde');
        this.saving.set(false);
      },
    });
  }
}

// Export alias for compatibility with main.ts import { App }
export { AppComponent as App };
