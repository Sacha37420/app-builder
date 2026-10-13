"""Mesure du contexte : combien de jetons pèse un texte, et ce qu'un modèle peut en tenir.

L'estimation est locale et déterministe — aucun appel réseau, aucune
bibliothèque de découpage : elle sert à décider AVANT d'appeler un fournisseur,
et à borner les lots remis à un agent de développement. Elle surestime
volontairement (mieux vaut refuser trop tôt qu'envoyer une requête vouée à l'échec).
"""
import math

# Ce qu'un agent de développement doit pouvoir tenir pour UN lot de la feuille de
# route générée, en plus du cahier des charges, des règles du lab et du code qu'il
# lira : au-delà, le lot doit être découpé.
LOT_BUDGET_JETONS = 20_000

# Octets UTF-8 par jeton. Les découpages réels donnent 3,5 à 4 caractères par
# jeton en français courant, nettement moins pour du JSON ou du code ; les
# lettres accentuées (2 octets) comptent double ici, ce qui va dans le bon sens.
_OCTETS_PAR_JETON = 3


def estimer_jetons(texte) -> int:
    """Nombre de jetons estimé d'un texte (0 pour un texte vide)."""
    if not texte:
        return 0
    if not isinstance(texte, str):
        texte = str(texte)
    return math.ceil(len(texte.encode('utf-8')) / _OCTETS_PAR_JETON)


# ── Ce que chaque modèle peut tenir ───────────────────────────────────────────
# Fenêtre de contexte (entrée + sortie) et sortie maximale, en jetons. Tenue ici,
# côté serveur : l'interface lit cette liste (GET /api/models/) au lieu de la
# recopier. Claude : valeurs publiées par Anthropic. Mistral : valeurs prudentes
# (les alias « -latest » changent de modèle sans prévenir) — une fenêtre
# sous-estimée fait refuser un peu tôt, jamais envoyer une requête perdue.
MODELES = (
    {'id': 'claude-sonnet-4-6', 'provider': 'claude', 'label': 'Sonnet 4.6 — Recommandé ★',
     'context_window': 1_000_000, 'max_output': 128_000},
    {'id': 'claude-opus-4-8', 'provider': 'claude', 'label': 'Opus 4.8 — Le plus puissant',
     'context_window': 1_000_000, 'max_output': 128_000},
    {'id': 'claude-haiku-4-5', 'provider': 'claude', 'label': 'Haiku 4.5 — Rapide / économique',
     'context_window': 200_000, 'max_output': 64_000},
    {'id': 'mistral-small-latest', 'provider': 'mistral', 'label': 'Small — Recommandé ★',
     'context_window': 32_000, 'max_output': 8_192},
    {'id': 'mistral-large-latest', 'provider': 'mistral', 'label': 'Large — Le plus puissant',
     'context_window': 128_000, 'max_output': 8_192},
    {'id': 'codestral-latest', 'provider': 'mistral', 'label': 'Codestral — Spécialisé code',
     'context_window': 32_000, 'max_output': 8_192},
    {'id': 'open-mistral-nemo', 'provider': 'mistral', 'label': 'Nemo — Économique',
     'context_window': 128_000, 'max_output': 8_192},
)
MODELE_PAR_DEFAUT = {'claude': 'claude-sonnet-4-6', 'mistral': 'mistral-small-latest'}
# Anciens identifiants encore enregistrés dans des navigateurs.
_ALIAS = {'claude-haiku-4-5-20251001': 'claude-haiku-4-5'}
# Modèle inconnu de la table : on le laisse passer, avec la plus petite fenêtre.
_FENETRE_INCONNUE = 32_000

# Marge gardée libre : l'estimation n'est pas un décompte exact.
MARGE_JETONS = 1_000
# « La spec fait mémoire » : au-delà, les messages les plus anciens ne partent plus.
HISTORIQUE_MAX_MESSAGES = 24


def fournisseur(provider) -> str:
    return 'mistral' if provider == 'mistral' else 'claude'


def modele(provider, identifiant=None) -> dict:
    """La fiche du modèle demandé (celui par défaut du fournisseur si aucun)."""
    provider = fournisseur(provider)
    identifiant = _ALIAS.get(identifiant, identifiant) or MODELE_PAR_DEFAUT[provider]
    for m in MODELES:
        if m['id'] == identifiant and m['provider'] == provider:
            return dict(m)
    return {'id': identifiant, 'provider': provider, 'label': identifiant,
            'context_window': _FENETRE_INCONNUE, 'max_output': 4_096}


def catalogue() -> dict:
    """La liste servie à l'interface, par fournisseur."""
    return {
        'providers': {p: {'default': MODELE_PAR_DEFAUT[p],
                          'models': [{c: m[c] for c in ('id', 'label', 'context_window', 'max_output')}
                                     for m in MODELES if m['provider'] == p]}
                      for p in ('claude', 'mistral')},
        'lot_budget_tokens': LOT_BUDGET_JETONS,
    }


def _contenu(message) -> str:
    c = message.get('content') if isinstance(message, dict) else ''
    return c if isinstance(c, str) else str(c or '')


def nettoyer(messages) -> list[dict]:
    """Ne garde d'un historique que ce qu'un fournisseur attend : rôle et texte.
    Les patchs, résumés et états d'application joints par l'interface ne partent pas."""
    propres = []
    for m in messages if isinstance(messages, list) else []:
        if isinstance(m, dict) and m.get('role') in ('user', 'assistant') and _contenu(m).strip():
            propres.append({'role': m['role'], 'content': _contenu(m)})
    return propres


def borner(messages: list[dict], budget: int) -> tuple[list[dict], int]:
    """Les messages les plus récents qui tiennent dans `budget` jetons.

    Le dernier message part toujours (c'est la question posée) ; on remonte
    ensuite tant qu'il reste de la place, sans dépasser HISTORIQUE_MAX_MESSAGES,
    et l'envoi commence par un message de l'utilisateur. Rend aussi le nombre de
    messages laissés de côté."""
    if not messages:
        return [], 0
    gardes, reste = [messages[-1]], budget - estimer_jetons(_contenu(messages[-1]))
    for m in reversed(messages[:-1]):
        poids = estimer_jetons(_contenu(m))
        if len(gardes) >= HISTORIQUE_MAX_MESSAGES or poids > reste:
            break
        gardes.insert(0, m)
        reste -= poids
    while len(gardes) > 1 and gardes[0]['role'] != 'user':
        gardes.pop(0)
    return gardes, len(messages) - len(gardes)


def mesurer(fiche: dict, prompt_systeme: str, spec_compacte: str, messages: list[dict],
            sortie: int, retires: int = 0) -> dict:
    """Ce que pèserait l'envoi, face à ce que le modèle peut tenir."""
    systeme = estimer_jetons(prompt_systeme)
    historique = sum(estimer_jetons(_contenu(m)) for m in messages)
    disponible = fiche['context_window'] - sortie - MARGE_JETONS
    total = systeme + historique
    return {
        'model': fiche['id'], 'provider': fiche['provider'],
        'context_window': fiche['context_window'], 'reserved_output_tokens': sortie,
        'available_tokens': disponible,
        'system_tokens': systeme, 'spec_tokens': estimer_jetons(spec_compacte), 'history_tokens': historique,
        'estimated_tokens': total,
        'ratio': round(total / disponible, 4) if disponible > 0 else 1.0,
        'fits': total <= disponible,
        'messages_sent': len(messages), 'messages_dropped': retires,
    }


_SIGNES_DE_DEPASSEMENT = ('prompt is too long', 'context window', 'context length', 'context_length',
                          'too many tokens', 'maximum context', 'too large for model', 'input is too long')


def est_un_depassement(erreur) -> bool:
    """L'erreur d'un fournisseur dit-elle « contexte trop long » ?"""
    texte = str(erreur).lower()
    reponse = getattr(erreur, 'response', None)
    try:
        texte += ' ' + (getattr(reponse, 'text', '') or '').lower()
    except Exception:
        pass
    return any(s in texte for s in _SIGNES_DE_DEPASSEMENT)
