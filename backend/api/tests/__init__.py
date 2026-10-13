"""Tests backend d'app-builder — `python manage.py test`.

Un module par famille ; tout est réexporté ici pour que les noms de la feuille
de route restent valables (`python manage.py test api.tests.RemiseAuLabTests`).
Les modules ne s'appellent pas `test_*.py` : la découverte ne les charge qu'une
fois, par ce fichier.
"""
from .socle import *  # noqa: F401,F403
from .conformite import *  # noqa: F401,F403
