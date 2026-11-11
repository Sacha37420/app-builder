/** Petites aides de saisie communes aux pages d'édition. */

export function val(e: Event): string {
  return (e.target as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value;
}

export function checked(e: Event): boolean {
  return (e.target as HTMLInputElement).checked;
}

/** Nombre saisi, ou `undefined` si le champ est vide ou illisible (la clé disparaît alors). */
export function num(e: Event): number | undefined {
  const raw = val(e).trim();
  if (raw === '') return undefined;
  const n = Number(raw.replace(',', '.'));
  return Number.isFinite(n) ? n : undefined;
}

/** « a, b ,c » → ['a', 'b', 'c'] (vides retirés, doublons retirés, ordre gardé). */
export function csv(raw: string): string[] {
  const out: string[] = [];
  for (const part of raw.split(',')) {
    const t = part.trim();
    if (t && !out.includes(t)) out.push(t);
  }
  return out;
}

export function joinCsv(list: readonly string[] | undefined | null): string {
  return (list ?? []).join(', ');
}

/** Copie d'un objet sans ses clés vides (`''`, `undefined`, `[]`) : la spec reste sans bruit. */
export function compact<T extends object>(o: T): T {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(o)) {
    if (v === undefined || v === '' || (Array.isArray(v) && v.length === 0)) continue;
    out[k] = v;
  }
  return out as T;
}

/** Remplace l'élément `idx` d'une liste par `{...ancien, ...patch}` (clés vides retirées). */
export function patchAt<T extends object>(list: readonly T[], idx: number, patch: Partial<T>): T[] {
  return list.map((x, i) => (i === idx ? compact({ ...x, ...patch }) : x));
}

export function removeAt<T>(list: readonly T[], idx: number): T[] {
  return list.filter((_, i) => i !== idx);
}
