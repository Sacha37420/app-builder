/**
 * Configuration injectée au démarrage du conteneur (`assets/env.js`, écrit par
 * `nginx-entrypoint.sh`).
 */
export interface LabEnv {
  keycloakUrl?: string;
  keycloakRealm?: string;
  keycloakClientId?: string;
  appUrl?: string;
  apiUrl?: string;
}

export function labEnv(): LabEnv {
  return (window as unknown as { __env?: LabEnv }).__env ?? {};
}

/** Base de l'API d'App Builder, sans barre finale. */
export function apiUrl(): string {
  return (labEnv().apiUrl ?? 'http://localhost:8087').replace(/\/+$/, '');
}

/**
 * Les SEULES adresses auxquelles le jeton de l'utilisateur est joint
 * (`auth.interceptor.ts`, `token-scope.ts`) : l'API d'App Builder. Cette
 * interface n'appelle aucune autre API avec le jeton (les fournisseurs d'IA
 * sont appelés par le backend).
 */
export function tokenBases(): string[] {
  return [apiUrl()];
}
