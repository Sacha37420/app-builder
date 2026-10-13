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
