import { Component, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { KeycloakService } from '../../core/keycloak.service';
import { BuilderStateService } from '../../core/builder-state.service';

@Component({
  selector: 'app-navbar',
  standalone: true,
  imports: [RouterLink, RouterLinkActive],
  templateUrl: './navbar.component.html',
  styleUrl: './navbar.component.scss',
})
export class NavbarComponent {
  private kc = inject(KeycloakService);
  state = inject(BuilderStateService);

  saving = signal(false);
  saveError = signal('');
  menuOpen = signal(false);

  get username(): string {
    return this.kc.username || this.kc.email;
  }

  toggleMenu(): void { this.menuOpen.update(v => !v); }

  closeMenu(): void { this.menuOpen.set(false); }

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

  logout(): void {
    this.kc.logout();
  }
}
