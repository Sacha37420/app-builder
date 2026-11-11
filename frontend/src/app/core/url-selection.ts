import { computed, effect, inject, Signal, untracked } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { BuilderStateService, IdCollection } from './builder-state.service';

export interface UrlSelection {
  /** Identifiant courant désigné par l'adresse (après correspondance des anciens ids), ou `null`. */
  id: Signal<number | null>;
  /** Pose (ou retire, `null`) la sélection dans l'adresse, sans empiler d'entrée d'historique. */
  set(id: number | null, extra?: Record<string, string | number | null>): void;
}

/**
 * Sélection d'une page d'édition portée par un paramètre d'adresse (`?modele=12`),
 * pour que l'inspecteur de la vue d'ensemble y mène directement (contrat I6,
 * `edit.route` + `edit.query`). Un identifiant ancien — le serveur recrée les
 * éléments à chaque enregistrement — est traduit en l'identifiant courant, et
 * l'adresse réécrite. À appeler dans un contexte d'injection (constructeur).
 */
export function urlSelection(param: string, collection: IdCollection): UrlSelection {
  const route = inject(ActivatedRoute);
  const router = inject(Router);
  const state = inject(BuilderStateService);
  const params = toSignal(route.queryParamMap);

  const raw = computed<number | null>(() => {
    const v = params()?.get(param);
    return v && /^-?[0-9]{1,9}$/.test(v) ? Number(v) : null;
  });
  const id = computed<number | null>(() => {
    const r = raw();
    return r === null ? null : state.resolveId(collection, r);
  });

  const set = (value: number | null, extra: Record<string, string | number | null> = {}): void => {
    untracked(() => router.navigate([], {
      relativeTo: route, queryParams: { [param]: value, ...extra }, queryParamsHandling: 'merge', replaceUrl: true,
    }));
  };

  effect(() => {
    const r = raw();
    const cur = id();
    if (r !== null && cur !== null && cur !== r) set(cur);
  });

  return { id, set };
}
