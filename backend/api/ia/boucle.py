"""Un tour de conversation : boucle d'outils bornée côté serveur (ou repli sans outils).

Spec lue en base → index dans le bloc variable du prompt → appel ; appels
d'outils ⇒ résultats et nouvel appel ; texte final ou `proposer_choix`
(terminal) ⇒ fin du tour. Bornes (contrat v1, §7) :
- au plus MAX_APPELS appels modèle par tour ;
- au plus MAX_ECHECS `proposer_operations` refusés de suite ;
- une horloge de tour (HORLOGE_S, sous les 120 s de gunicorn et du proxy) ;
- le contexte réévalué avant chaque appel d'après l'usage RÉEL du précédent.

Les blocs d'outils ne sortent jamais du tour : l'historique renvoyé par
l'interface au tour suivant est du texte (I4).
"""
import logging
import time

from .. import budget, conformite, lecture, patching
from . import fournisseurs, outils as outils_mod
from .prompt import REGLES, bloc_variable

log = logging.getLogger(__name__)

MAX_APPELS = 6
MAX_ECHECS = 3
HORLOGE_S = 90.0
MIN_RESTANT_S = 10.0     # en dessous, on ne lance pas un appel de plus

AVIS_TRONCATURE = ("\n\n⚠️ Réponse coupée : la limite de longueur du modèle a été atteinte. "
                   "Demandez la suite, ou avancez par étapes plus petites.")
_REFUS = ("Le modèle a refusé de traiter cette demande. Reformulez-la, ou choisissez un autre modèle.")
_BORNE = ("J'ai atteint la limite d'étapes pour un seul message. Ce que j'ai déjà proposé est ci-dessous ; "
          "écrivez « continue » pour que je poursuive.")
_HORLOGE = ("Ce message a pris trop de temps à traiter. Ce que j'ai déjà proposé est ci-dessous ; "
            "écrivez « continue » pour que je poursuive.")
_CONTEXTE = ("La conversation de ce tour ne tient plus dans la fenêtre du modèle. Ce que j'ai déjà proposé est "
             "ci-dessous ; effacez la conversation ou choisissez un modèle à plus grande fenêtre pour continuer.")
_ECHECS = ("Mes propositions ont été refusées {n} fois de suite par la vérification de la spécification ; "
           "je m'arrête là pour ce message. Dernières erreurs : {erreurs}")


def systeme_variable(spec: dict) -> tuple[str, str]:
    """(bloc variable, index) pour cette spec."""
    index = lecture.index_spec(spec)
    blocages = [b.get('message', '') for b in conformite.blocages(spec) if isinstance(b, dict)]
    return bloc_variable(index, blocages), index


def anthropique(fiche: dict) -> bool:
    return budget.FOURNISSEURS[budget.fournisseur(fiche['provider'])]['protocole'] == 'anthropic'


def outils_pour(fiche: dict) -> list | None:
    if not fiche.get('tools'):
        return None
    if anthropique(fiche):
        return outils_mod.pour_anthropic(strict=fiche.get('strict', True))
    return outils_mod.pour_mistral()     # format `function` commun aux compatibles OpenAI


class _Tour:

    def __init__(self, fiche, cle, spec, messages, base_version, debut):
        self.fiche, self.cle, self.spec = fiche, cle, spec
        self.conv = [dict(m) for m in messages]
        self.base_version = base_version
        self.fin = debut + HORLOGE_S
        self.variable, self.index = systeme_variable(spec)
        self.outils = outils_pour(fiche)
        self.etat = outils_mod.EtatDuTour(spec)
        self.usage = {'calls': 0, 'input_tokens': 0, 'output_tokens': 0, 'cache_read_tokens': 0}
        self.client = fournisseurs.client_anthropic(cle) if anthropique(fiche) else None
        self.textes = []
        self.tronque = False
        self.avis = ''

    def appeler(self, conv, format_json=None):
        restant = self.fin - time.monotonic()
        sortie = budget.sortie(self.fiche)
        if anthropique(self.fiche):
            r = fournisseurs.appeler_anthropic(self.client, self.fiche, REGLES, self.variable, conv, self.outils,
                                               sortie, restant, format_json=format_json)
        elif self.fiche['provider'] == 'mistral':
            r = fournisseurs.appeler_mistral(self.cle, self.fiche, REGLES, self.variable, conv, self.outils,
                                             sortie, restant, format_json=format_json is not None)
        else:
            r = fournisseurs.appeler_openai(self.fiche['provider'], self.cle, self.fiche, REGLES, self.variable,
                                            conv, self.outils, sortie, restant, format_json=format_json is not None)
        self.usage['calls'] += 1
        for k in ('input_tokens', 'output_tokens', 'cache_read_tokens'):
            self.usage[k] += r.usage.get(k, 0)
        # Contrôle du cache : on journalise des COMPTES, jamais du contenu.
        log.info('Chat : appel %d (%s) arrêt=%s entrée=%d sortie=%d cache=%d', self.usage['calls'],
                 self.fiche['id'], r.arret, r.usage.get('input_tokens', 0), r.usage.get('output_tokens', 0),
                 r.usage.get('cache_read_tokens', 0))
        return r

    # ── Boucle d'outils ───────────────────────────────────────────────────────

    def boucle(self):
        derniere = None
        while True:
            if self.usage['calls'] >= MAX_APPELS:
                self.avis = _BORNE
                break
            if self.usage['calls'] and self.fin - time.monotonic() < MIN_RESTANT_S:
                self.avis = _HORLOGE
                break
            if derniere is not None and not self._tient(derniere):
                self.avis = _CONTEXTE
                break
            r = self.appeler(self.conv)
            derniere = r
            if r.texte:
                self.textes.append(r.texte)
            if r.arret == 'refus':
                self.avis = _REFUS
                break
            if r.arret == 'tronque':
                self.tronque = True
                break
            if r.arret != 'outils' or not r.appels:
                break
            resultats = []
            for a in r.appels:
                if a.illisible:
                    contenu, erreur = outils_mod.compact({'error': 'arguments', 'detail': 'Arguments JSON illisibles.'}), True
                    if a.nom == 'proposer_operations':
                        self.etat.echecs_consecutifs += 1
                else:
                    contenu, erreur = self.etat.executer(a.nom, a.entree)
                log.info('Chat : outil %s%s', a.nom, ' (erreur)' if erreur else '')
                resultats.append((a.id, a.nom, contenu, erreur))
            self.conv.append(r.message_assistant)
            if anthropique(self.fiche):
                self.conv.append(fournisseurs.resultats_anthropic(resultats))
            else:
                self.conv.extend(fournisseurs.resultats_mistral(resultats))
            self._derniers_resultats = sum(budget.estimer_jetons(c) for _i, _n, c, _e in resultats)
            if self.etat.choix is not None:
                break
            if self.etat.echecs_consecutifs >= MAX_ECHECS:
                self.avis = _ECHECS.format(n=self.etat.echecs_consecutifs,
                                           erreurs=' ; '.join(self.etat.erreurs[:5]) or 'arguments illisibles')
                break

    def _tient(self, derniere) -> bool:
        """L'appel suivant tiendrait-il ? Usage réel du précédent + ses nouveaux résultats."""
        prochain = (derniere.usage.get('input_tokens', 0) + derniere.usage.get('output_tokens', 0)
                    + getattr(self, '_derniers_resultats', 0))
        disponible = self.fiche['context_window'] - budget.sortie(self.fiche) - budget.MARGE_JETONS
        return prochain <= disponible

    # ── Repli sans outils : une sortie structurée ─────────────────────────────

    def repli(self):
        from . import repli
        repli.tour(self)

    # ── Réponse ───────────────────────────────────────────────────────────────

    def resultat(self) -> dict:
        proposition = self.etat.proposition(self.base_version)
        choix = self.etat.choix
        contenu = self.textes[-1] if self.textes else ''
        if not contenu and choix:
            contenu = choix['question']
        if not contenu and proposition and proposition['operations']:
            contenu = 'Je propose : ' + (proposition['resume'].get('texte') or 'des modifications') + '.'
        if self.avis:
            contenu = (contenu + '\n\n' + self.avis).strip()
        if self.tronque:
            contenu = (contenu + AVIS_TRONCATURE).strip()
        return {'content': contenu, 'choices': choix, 'proposal': proposition, 'truncated': self.tronque,
                'usage': dict(self.usage), 'tool_results_tokens': self.etat.jetons_resultats}


def tour(*, fiche: dict, cle: str, spec: dict, messages: list, base_version: str, debut: float | None = None) -> dict:
    """Joue un tour. Lève `fournisseurs.ErreurFournisseur` si le PREMIER appel échoue ;
    une panne d'un appel suivant termine le tour avec ce qui a déjà été proposé."""
    t = _Tour(fiche, cle, spec, messages, base_version, time.monotonic() if debut is None else debut)
    try:
        if fiche.get('tools'):
            t.boucle()
        else:
            t.repli()
    except fournisseurs.ErreurFournisseur as exc:
        if t.usage['calls'] == 0:
            raise
        t.avis = exc.message or _CONTEXTE
    return t.resultat()


def mesure(fiche: dict, spec: dict, messages: list, retires: int = 0) -> dict:
    variable, index = systeme_variable(spec)
    outils = outils_pour(fiche)
    return budget.mesurer(fiche, REGLES + '\n\n' + variable, index, messages, budget.sortie(fiche), retires,
                          outils=outils, index=index, reserve_outils=budget.RESERVE_OUTILS if outils else 0)

