/**
 * Message lisible quand une réponse d'erreur n'apporte pas le sien (proxy, coupure
 * réseau…). Jamais `HttpErrorResponse.message` : « Http failure response for <URL>: 504 … ».
 */
export function messageHttp(status: number | undefined): string {
  if (!status) return 'Serveur injoignable : vérifiez votre connexion puis réessayez.';
  if (status === 401) return 'Session expirée : rechargez la page pour vous reconnecter.';
  if (status === 403) return "Accès refusé : votre compte n'a pas accès à cette action.";
  if (status === 404) return 'Élément introuvable : il a peut-être été supprimé.';
  if (status === 504) return 'Le serveur a mis trop de temps à répondre : réessayez.';
  if (status >= 500) return 'Erreur du serveur : réessayez dans quelques minutes.';
  return 'Demande refusée par le serveur.';
}
