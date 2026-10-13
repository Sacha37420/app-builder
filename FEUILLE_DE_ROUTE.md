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

## Lot 2 — Patchs IA fiables   ·   statut : en cours
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
- [ ] `python manage.py test api.tests.PatchFusionTests` passe (ajout d'un endpoint à un groupe existant, patch de page sans `service_names`, `steps` conservés)
- [ ] `python manage.py test api.tests.PatchSuppressionTests` passe (suppression et renommage sans doublon)
- [ ] `python manage.py test api.tests.PatchReferencesTests` passe (référence orpheline refusée, spec inchangée)
- [ ] `python manage.py test api.tests.PatchHistoriqueTests` passe (état appliqué persistant, annulation rend la spec d'avant)
**Blocage (2026-10-13) :** code poussé (`de9a6c6`), déploiement refusé par le moteur à l'étape « sync » avant tout test : le dépôt suit `.keycloak-client-opts`, fichier réservé au cadriciel. Le retirer de git ferait supprimer le fichier de l'hôte au prochain checkout (il y est aujourd'hui suivi), et `validate-app.sh` refuserait alors l'app : il faut une action sur l'hôte, hors de cet espace. Les tests ci-dessus n'ont donc pas été lancés par le lab.
**Vérifié le :**

## Lot 3 — Mesure du contexte   ·   statut : à faire
**Objectif :** l'utilisateur voit à tout moment la place qu'occupent sa spec et sa conversation par rapport à ce que le modèle choisi peut traiter, et l'app n'envoie jamais une requête vouée à l'échec.
**Tâches :**
- [ ] Table des modèles (fenêtre d'entrée, sortie maximale) côté serveur ; liste des modèles servie par l'API et non plus codée en dur dans le frontend
- [ ] Estimation de la taille (prompt système + spec + historique) rendue avec chaque réponse et affichée en jauge
- [ ] Spec envoyée sous forme compacte ; historique borné aux derniers échanges, la spec faisant mémoire
- [ ] Ne plus envoyer à l'IA `chat_history` (et ses patchs) à l'intérieur de la spec : le frontend le joint aujourd'hui à chaque message
- [ ] Refus explicite avant l'appel quand le budget est dépassé ; erreur « contexte trop long » du fournisseur traduite
- [ ] Même mesure appliquée aux lots générés (lot 5) : un lot ne dépasse pas ce qu'un agent de développement peut tenir
**Tests à passer avant de clore le lot :**
- [ ] `python manage.py test api.tests.BudgetContexteTests` passe (estimation croissante avec la spec, seuil par modèle, refus avant appel, historique tronqué sans perdre le dernier message)
- [ ] `python manage.py test api.tests.ChatTests` reste vert
**Vérifié le :**

## Lot 4 — Spécification alignée sur le cadriciel   ·   statut : à faire
**Objectif :** toute spécification décrit une app que le moteur du lab sait créer et déployer, sans rien y contredire.
**Tâches :**
- [ ] Types d'app limités à ceux de `create_app` (`django`, `django-angular`, `angular`), `django-angular` par défaut ; une spec d'un autre type reste lisible mais n'est pas « prête »
- [ ] Nom de projet (slug) saisi et validé selon les règles de `check-app-name.sh`, distinct du titre
- [ ] `required_groups` obligatoire pour qu'une spec soit « prête »
- [ ] Type `file` remplacé par une référence à l'API `storage` ; email par `send_mail`
- [ ] Route publique (`auth_required: false`) : décision explicite, reportée dans la feuille de route générée
- [ ] Champ structuré pour les règles métier et contraintes (aujourd'hui seulement dans la conversation)
- [ ] Prompt IA mis à jour : moteur du lab, règles du gabarit, Foyer, plus de contradiction sur `file`
- [ ] Page « Infra » : ce que l'app occupera dans le lab (conteneurs, chemins `/<app>` et `/<app>-api`, client Keycloak et groupes, base, storage, email)
- [ ] Garder les colonnes lues par lab-admin (`test_tables_lues_par_lab_admin`)
**Tests à passer avant de clore le lot :**
- [ ] `python manage.py test api.tests.ConformiteCadricielTests` passe (type refusé hors liste, slug invalide refusé, spec sans groupe non « prête », champ `file` refusé)
- [ ] `python manage.py test api.tests.SpecificationTests.test_tables_lues_par_lab_admin` reste vert
**Vérifié le :**

## Lot 5 — Cahier des charges, feuille de route et remise au lab   ·   statut : à faire
**Objectif :** à partir d'une spec « prête », l'utilisateur obtient le cahier des charges et la `FEUILLE_DE_ROUTE.md` de son app au format du lab, et lab-admin peut les lire pour lancer la construction.
**Tâches :**
- [ ] Génération côté serveur du cahier des charges (Markdown) depuis la spec
- [ ] Génération de `FEUILLE_DE_ROUTE.md` : lot 1 du gabarit, puis lots métier découpés (modèles, API, pages, pipelines) avec tests nommés dérivés des endpoints et des rôles
- [ ] Paramètres de création rendus tels que `create_app` les attend (nom, type, groupes)
- [ ] Générateurs de code de l'aperçu corrigés ou retirés (vues sans filtre de propriétaire, rôles ignorés, `FileField`)
- [ ] API de remise réservée au lab : routes de lecture ouvertes au seul client `lab-admin` (`KEYCLOAK_TRUSTED_CLIENTS`, verrou 2 généralisé du cadriciel), limitées aux specs de l'appelant, jamais en écriture
- [ ] Prompt à lancer côté lab-admin (hors de ce dépôt) pour y brancher « Lancer la construction » : remis au développeur, pas commité ici
**Tests à passer avant de clore le lot :**
- [ ] `python manage.py test api.tests.FeuilleDeRouteGenereeTests` passe (le fichier généré satisfait l'expression de `validate-app.sh`, chaque lot a au moins un test nommé, une commande de test d'une ligne)
- [ ] `python manage.py test api.tests.CahierDesChargesTests` passe (groupes, règles métier, routes publiques et stockage y figurent ; export d'autrui impossible)
- [ ] `python manage.py test api.tests.RemiseAuLabTests` passe (jeton `lab-admin` accepté sur les seules routes de remise et refusé ailleurs, jeton d'un autre client refusé, specs d'autrui invisibles, aucune écriture)
**Vérifié le :**

## Lot 6 — Représentation graphique à toutes les échelles   ·   statut : à faire
**Objectif :** la personne qui commande l'app la voit du plus large (sa place dans le lab) au plus fin (une étape de pipeline), en naviguant d'une échelle à l'autre.
**Tâches :**
- [ ] Vue d'ensemble : groupes → Keycloak → frontend → API → base / storage
- [ ] Vue des lots de la feuille de route générée, reliée aux éléments de la spec
- [ ] Navigation continue entre vue d'ensemble, architecture, schéma de données et pipelines
- [ ] Identité Foyer respectée (tokens, 900 px, cibles de 44 px)
**Tests à passer avant de clore le lot :**
- [ ] `python manage.py test api.tests.VueEnsembleTests` passe (l'API rend le graphe d'une spec : nœuds et liens cohérents avec la spec)
- [ ] `npm run build` du frontend sans erreur ; aucune couleur en dur dans les composants ajoutés (`grep` sur les valeurs hexadécimales)
- [ ] Test de cloisonnement vert après déploiement
**Vérifié le :**
