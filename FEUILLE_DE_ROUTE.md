# Feuille de route — app-builder

Ce fichier est lu par une machine : `validate-app.sh` refuse de déployer s'il manque ou s'il ne
contient aucun lot au format ci-dessous. Garder les titres tels quels.

But de l'app : construire la spécification, le cahier des charges et la feuille de route d'une
nouvelle app du lab, de façon assez structurée pour que son développement soit automatisable par
une IA, avec une représentation graphique à toutes les échelles pour la personne qui la commande.

## Commande de test
python manage.py test

## Lot 1 — Éditeur de spécifications, chat IA et serrure de l'API   ·   statut : livré
**Objectif :** un membre conçoit une spécification (modèles, endpoints, services, pages, pipelines) à la main ou par le chat IA, et ne voit que les siennes.
**Tâches :**
- [x] Éditeur visuel et enregistrement automatique
- [x] Chat IA en deux échanges (texte, puis patch JSON dédié)
- [x] Cloisonnement à deux verrous, propriété par `owner_email`
**Tests à passer avant de clore le lot :**
- [x] Tests backend (commande ci-dessus)
- [x] Test de cloisonnement `frontend/e2e/cloisonnement.spec.ts`
**Vérifié le :** 2026-10-12 — commit `795cab6` déployé par le moteur, tests backend « ok » (lu dans l'état du projet le 2026-10-13, non relancés à la main). Cloisonnement : 3/3 verts le 2026-10-11 d'après le commit `f89fbb0`, « non-lancé » sur le déploiement du 2026-10-12.

## Lot 2 — Patchs IA fiables   ·   statut : livré
**Objectif :** un patch proposé par l'IA ne fait jamais perdre un élément que l'utilisateur n'a pas demandé de retirer, et tout patch appliqué est traçable et annulable.
**Tâches :**
- [x] Appliquer le patch côté serveur (`POST /api/apps/<id>/patch/`) : une seule implémentation, testable, atomique
- [x] Fusion par élément et non par bloc : un patch qui cite un champ, un endpoint, une interaction ou un pipeline n'efface pas ses voisins ; une liste de liens absente du patch laisse les liens en place
- [x] Documenter dans le prompt les suppressions (`remove_*`) et le renommage, aujourd'hui acceptés par le code mais jamais décrits à l'IA
- [x] Conserver les `steps` des endpoints (perdus à la normalisation du patch)
- [x] Refuser avec un message les références orphelines (`linked_model_name`, `to_model`, `endpoint_group_names`, `service_names`, `trigger_interaction`) au lieu de les ignorer
- [x] Enregistrer l'état « appliqué » de chaque patch et un instantané de la spec avant application (annulation)
- [x] Détecter une réponse tronquée (`stop_reason`) au lieu de retenter le même appel
**Tests à passer avant de clore le lot :**
- [x] `python manage.py test api.tests.PatchFusionTests` passe (ajout d'un endpoint à un groupe existant, patch de page sans `service_names`, `steps` conservés)
- [x] `python manage.py test api.tests.PatchSuppressionTests` passe (suppression et renommage sans doublon)
- [x] `python manage.py test api.tests.PatchReferencesTests` passe (référence orpheline refusée, spec inchangée)
- [x] `python manage.py test api.tests.PatchHistoriqueTests` passe (état appliqué persistant, annulation rend la spec d'avant)
**Vérifié le :** 2026-10-13 — `bash chantiers/tests/essai.sh app-builder` (PostgreSQL jetable, code du commit `42a60d8`) : 79 tests, OK, dont les quatre classes ci-dessus. Tests verts hors déploiement : le lot passera « livré » à la mise en service. Le blocage du déploiement (`.keycloak-client-opts` suivi par git) est levé par `42a60d8`. **Mis en service le 2026-10-13** : image du commit `57f79e5` construite pendant que l'ancienne tournait, `scripts/app-test.sh app-builder` vert sur cette image, migrations `0008` et `0009` jouées (les deux spécifications existantes intactes), test de cloisonnement 3/3 après déploiement. Vu en navigateur réel (compte `e2edev`) : jauge de contexte, pages « Vue d'ensemble », « Livrables » et « Lab & infra », puis la remise jusqu'au corps envoyé au moteur depuis lab-admin. Non vu : thème sombre ; création réelle d'un projet (demande un compte GitHub humain).

## Lot 3 — Mesure du contexte   ·   statut : livré
**Objectif :** l'utilisateur voit à tout moment la place qu'occupent sa spec et sa conversation par rapport à ce que le modèle choisi peut traiter, et l'app n'envoie jamais une requête vouée à l'échec.
**Tâches :**
- [x] Table des modèles (fenêtre, sortie maximale) côté serveur (`api/budget.py`) ; liste servie par `GET /api/models/` et non plus codée en dur dans le frontend
- [x] Estimation locale (aucun appel réseau) du prompt système, de la spec et de l'historique, rendue avec chaque réponse du chat et par `POST /api/chat/estimate/`  ; affichée en jauge au-dessus de la saisie
- [x] Spec envoyée sous forme compacte (liens par nom, sans identifiants ni valeurs vides, sans indentation) ; historique borné aux messages récents qui tiennent (24 au plus), le dernier toujours envoyé, la spec faisant mémoire
- [x] `chat_history` (et ses patchs) n'entre plus dans la spec envoyée à l'IA : écarté par le serveur, plus envoyé par le frontend
- [x] Refus explicite avant l'appel quand le budget est dépassé (413, `context_too_large`) ; erreur « contexte trop long » du fournisseur traduite de la même façon ; le patch n'est pas demandé s'il ne tient pas
- [x] Même estimateur appliqué aux lots générés (lot 5) : un lot ne dépasse pas 20 000 jetons estimés
**Tests à passer avant de clore le lot :**
- [x] `python manage.py test api.tests.BudgetContexteTests` passe (estimation croissante avec la spec, seuil par modèle, refus avant appel, historique tronqué sans perdre le dernier message)
- [x] `python manage.py test api.tests.ChatTests` reste vert
- [x] Frontend : liste des modèles lue sur l'API, jauge, `chat_history` plus envoyé ; `npm run build` sans erreur
**Vérifié le :** 2026-10-13 — `bash chantiers/tests/essai.sh app-builder` : suite complète verte, dont `BudgetContexteTests` (13) et `ChatTests` (8, inchangés). `npm run build` sans erreur ; jauge non essayée en navigateur. Fenêtres Mistral posées prudemment (32 000 pour `small` et `codestral`) faute de pouvoir les vérifier hors ligne. Tests verts hors déploiement. **Mis en service le 2026-10-13** : image du commit `57f79e5` construite pendant que l'ancienne tournait, `scripts/app-test.sh app-builder` vert sur cette image, migrations `0008` et `0009` jouées (les deux spécifications existantes intactes), test de cloisonnement 3/3 après déploiement. Vu en navigateur réel (compte `e2edev`) : jauge de contexte, pages « Vue d'ensemble », « Livrables » et « Lab & infra », puis la remise jusqu'au corps envoyé au moteur depuis lab-admin. Non vu : thème sombre ; création réelle d'un projet (demande un compte GitHub humain).

## Lot 4 — Spécification alignée sur le cadriciel   ·   statut : livré
**Objectif :** toute spécification décrit une app que le moteur du lab sait créer et déployer, sans rien y contredire.
**Tâches :**
- [x] Types d'app limités à ceux de `create_app` (`django`, `django-angular`, `angular`), `django-angular` par défaut ; une spec d'un autre type reste lisible et enregistrable telle quelle, mais n'est pas « prête » et on n'y revient pas
- [x] Nom de projet (`project_name`) saisi et validé selon la règle de forme de `check-app-name.sh`, distinct du titre (l'unicité et les noms réservés restent l'affaire du moteur)
- [x] `required_groups` obligatoire pour qu'une spec soit « prête »
- [x] Type `file` remplacé par `storage_file` (chemin d'un fichier du service `storage`) : `file` n'entre plus, ni par l'éditeur ni par un patch ; un ancien champ `file` bloque la remise jusqu'à conversion. Email : `uses_email`, envoi par `send_mail`
- [x] Route publique (`auth_required: false`) : justification `public_reason`, reportée dans la feuille de route générée
- [x] Champ structuré pour les règles métier (`business_rules`, fusionnées par titre dans les patchs)
- [x] Prompt IA mis à jour : moteur du lab, règles du gabarit, Foyer, plus de contradiction sur `file`
- [x] Page « Lab & infra » : fiche du projet, « Prête pour le lab ? » et empreinte (`GET /api/apps/<id>/lab/` : conteneurs, chemins `/<app>` et `/<app>-api`, client Keycloak et groupes, base, storage, email, routes publiques)
- [x] Garder les colonnes lues par lab-admin (`test_tables_lues_par_lab_admin`) : migration `0009` par ajout de colonnes seulement
**Tests à passer avant de clore le lot :**
- [x] `python manage.py test api.tests.ConformiteCadricielTests` passe (type refusé hors liste, slug invalide refusé, spec sans groupe non « prête », champ `file` refusé)
- [x] `python manage.py test api.tests.SpecificationTests.test_tables_lues_par_lab_admin` reste vert
- [x] `python manage.py test api.tests.MigrationCadricielTests` passe (les données d'avant la migration survivent)
- [x] `npm run build` du frontend sans erreur
**Vérifié le :** 2026-10-13 — `bash chantiers/tests/essai.sh app-builder` (PostgreSQL jetable) : suite complète verte, dont `ConformiteCadricielTests` (15), `ConformiteReglesTests` (4), `MigrationCadricielTests` (1) et `test_tables_lues_par_lab_admin` ; `npm run build` sans erreur (avertissements de budget de style antérieurs). Tests verts hors déploiement, interface non essayée en navigateur : le lot passera « livré » à la mise en service. **Mis en service le 2026-10-13** : image du commit `57f79e5` construite pendant que l'ancienne tournait, `scripts/app-test.sh app-builder` vert sur cette image, migrations `0008` et `0009` jouées (les deux spécifications existantes intactes), test de cloisonnement 3/3 après déploiement. Vu en navigateur réel (compte `e2edev`) : jauge de contexte, pages « Vue d'ensemble », « Livrables » et « Lab & infra », puis la remise jusqu'au corps envoyé au moteur depuis lab-admin. Non vu : thème sombre ; création réelle d'un projet (demande un compte GitHub humain).

## Lot 5 — Cahier des charges, feuille de route et remise au lab   ·   statut : livré
**Objectif :** à partir d'une spec « prête », l'utilisateur obtient le cahier des charges et les lots de la feuille de route de son app au format du lab, et lab-admin les lit pour lancer la construction.
**Tâches :**
- [x] Génération côté serveur du cahier des charges (Markdown) depuis la spec — déterministe, sans IA (`api/remise.py`)
- [x] Génération des lots métier de `FEUILLE_DE_ROUTE.md`, numérotés à partir de 2 (modèles, API, règles métier, services, pages, pipelines, recette), avec tests nommés dérivés des endpoints et des rôles. Ni en-tête, ni « Commande de test », ni Lot 1 : ils viennent du gabarit du lab, sur lequel le moteur greffe ces lots
- [x] Paramètres de création rendus tels que le moteur les attend (`name`, `type`, `required_groups`)
- [x] Mesure du contexte des lots : un lot ne dépasse pas 20 000 jetons estimés, la feuille de route 40 lots ; sinon la spec n'est pas « prête » (`context_budget`)
- [x] API de remise réservée au lab, en lecture seule : `GET /api/handoff/specs/`, `…/specs/<id>/`, `…/specs/<id>/kit/` — ouvertes au client de l'app et à ceux de `KEYCLOAK_HANDOFF_CLIENTS` (en service : `lab-admin`), qui n'entrent nulle part ailleurs ; clients intégrés du realm toujours refusés ; specs de l'appelant seulement ; jamais la conversation ni une clé
- [x] `GET /api/apps/<id>/livrables/` pour l'éditeur : mêmes textes, lot par lot, même quand la spec n'est pas prête
- [x] Générateurs de code de l'aperçu retirés (vues sans filtre de propriétaire, rôles ignorés) : la page « Code » devient « Livrables » (cahier des charges, feuille de route, blocages)
- Le « prompt à lancer côté lab-admin » prévu à l'origine n'est plus un livrable : le côté lab-admin est fait par le lab lui-même, qui consomme l'API de remise
**Tests à passer avant de clore le lot :**
- [x] `python manage.py test api.tests.FeuilleDeRouteGenereeTests` passe (la graine satisfait les règles du moteur ; greffée sur le gabarit elle passe l'expression de `validate-app.sh` ; chaque lot a au moins un test nommé ; un texte saisi ne peut pas casser le format ; budget de contexte)
- [x] `python manage.py test api.tests.CahierDesChargesTests` passe (groupes, règles métier, routes publiques et stockage y figurent ; export d'autrui impossible)
- [x] `python manage.py test api.tests.RemiseAuLabTests` passe (jeton `lab-admin` accepté sur les seules routes de remise et refusé ailleurs, `admin-cli` refusé partout, jeton d'un autre client refusé, specs d'autrui invisibles, aucune écriture, 409 si non prête)
- [x] `npm run build` du frontend sans erreur après le remplacement de la page « Code »
**Vérifié le :** 2026-10-13 — `bash chantiers/tests/essai.sh app-builder` : 137 tests, OK, dont les trois classes ci-dessus (37 tests). Page « Livrables » : `npm run build` sans erreur, plus aucun générateur de code dans le frontend (`grep`). Tests verts hors déploiement, interface non essayée en navigateur : le lot passera « livré » à la mise en service. **Mis en service le 2026-10-13** : image du commit `57f79e5` construite pendant que l'ancienne tournait, `scripts/app-test.sh app-builder` vert sur cette image, migrations `0008` et `0009` jouées (les deux spécifications existantes intactes), test de cloisonnement 3/3 après déploiement. Vu en navigateur réel (compte `e2edev`) : jauge de contexte, pages « Vue d'ensemble », « Livrables » et « Lab & infra », puis la remise jusqu'au corps envoyé au moteur depuis lab-admin. Non vu : thème sombre ; création réelle d'un projet (demande un compte GitHub humain).

## Lot 6 — Représentation graphique à toutes les échelles   ·   statut : livré
**Objectif :** la personne qui commande l'app la voit du plus large (sa place dans le lab) au plus fin (une étape de pipeline), en naviguant d'une échelle à l'autre.
**Tâches :**
- [x] API du graphe (`GET /api/apps/<id>/graph/`, `api/graphe.py`) : cinq échelles — dans le lab (groupes → Keycloak → interface → API → base / storage / email), architecture, données, pipelines, feuille de route — chaque nœud remontant à l'échelle au-dessus par `parent`
- [x] Lots de la feuille de route générée reliés aux éléments de la spec qu'ils construisent (liens `builds`)
- [x] Page « Vue d'ensemble » (`/overview`) : cinq échelles, fil d'Ariane, entrée dans un nœud, « Remonter », position dans l'URL (le retour arrière remonte d'une échelle), étiquettes « Lot N » sur chaque élément
- [x] Identité Foyer respectée (tokens, 900 px, cibles de 44 px)
**Tests à passer avant de clore le lot :**
- [x] `python manage.py test api.tests.VueEnsembleTests` passe (l'API rend le graphe d'une spec : nœuds et liens cohérents avec la spec)
- [x] `npm run build` du frontend sans erreur ; aucune couleur en dur dans les composants ajoutés (`grep` sur les valeurs hexadécimales)
- [x] Test de cloisonnement vert après déploiement
**Vérifié le :** 2026-10-13 — `bash chantiers/tests/essai.sh app-builder` : 158 tests, OK, dont `VueEnsembleTests` (6) et `GrapheReglesTests` (2). Arbre final : `npm run build` sans erreur (avertissements de budget de style sur cinq feuilles antérieures), `grep` de couleurs en dur vide sur `pages/overview/`. Interface non essayée en navigateur ; test de cloisonnement à lancer après déploiement : le lot passera « livré » à la mise en service. **Mis en service le 2026-10-13** : image du commit `57f79e5` construite pendant que l'ancienne tournait, `scripts/app-test.sh app-builder` vert sur cette image, migrations `0008` et `0009` jouées (les deux spécifications existantes intactes), test de cloisonnement 3/3 après déploiement. Vu en navigateur réel (compte `e2edev`) : jauge de contexte, pages « Vue d'ensemble », « Livrables » et « Lab & infra », puis la remise jusqu'au corps envoyé au moteur depuis lab-admin. Non vu : thème sombre ; création réelle d'un projet (demande un compte GitHub humain).
