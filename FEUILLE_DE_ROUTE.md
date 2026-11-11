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

---

Lots ajoutés par l'analyse du 2026-10-31 (vue d'ensemble : `to_do_global.md` à la racine du dépôt
du lab). [C] constaté, [D] déduit.

## Lot 7 — Robustesse du chat IA   ·   statut : livré
**Objectif :** une entrée mal formée ou une erreur de fournisseur ne fait plus de 500 ni de fuite.
**Constat [C] :**
- `PATCH /api/apps/<id>/chat/ {"chat_history": null}` donne 500 (`views.py:824`, colonne `NOT NULL`).
- `AIChatView` renvoie au client `str(exc)` du fournisseur (`views.py:736`).
- Des `print` écrivent jusqu'à 300 caractères de la sortie brute de l'IA (`views.py:145,702`).
- 2026-11-08 (relecture, code inchangé) : `chat_history` est toujours pris tel quel (`views.py:884`) ;
  il reste un seul extrait brut, `views.py:148` (`[PATCH] Extrait brut`).
**Tâches :**
- [x] `chat_history` validé : une liste, sinon 400 (chantier app-builder-v2) ; plus aucun `print` (journal par `logging`, sans contenu utilisateur)
- [x] Message générique au client (502) ; `logging` du seul type d'exception — fait avec le lot 8 (le texte d'une exception du fournisseur pouvait citer la requête). Les `print` d'extraits bruts restent
**Tests à passer avant de clore le lot :**
- [x] `null` → 400 ; une exception du fournisseur donne un corps sans détail ; `bash chantiers/tests/essai.sh app-builder` vert
**Vérifié le :** 2026-11-11 — `api.tests.ia.OperationsVuesTests.test_chat_history_doit_etre_une_liste` et `ChatGardeFousTests` (pannes 502/504 à message fixe) ; suite complète 253 OK par `essai.sh`, puis `scripts/app-test.sh app-builder` vert sur l'image du commit `b6f7d10`. **Mis en service le 2026-11-11** (image du commit `6a6318d`, voir lot 11).

## Lot 8 — Clés IA hors de `localStorage`   ·   statut : en cours
**Objectif :** une XSS sur le domaine commun du lab ne suffit plus à lire les clés Claude et Mistral.
**Constat [C] :** les clés sont gardées en clair dans `localStorage`
(`shared/ai-chat/ai-chat.component.ts:107-109`) et envoyées à chaque appel.
**Tâches :**
- [x] Coffre côté serveur chiffré (décision du propriétaire, chantier « failles », I3) : table `ai_key_vault` (migration `0010`), une ligne par compte (`owner_email`), `EncryptedTextField` sous `VAULT_ENCRYPTION_KEY` (jamais `SECRET_KEY` ; valeur indéchiffrable traitée comme absente)
- [x] `GET /api/ai-keys/` → `{"claude_key_configured", "mistral_key_configured"}` seulement ; `PUT /api/ai-keys/` `{"claude_key"|"mistral_key": "…"}` → 204, chaîne vide ⇒ suppression
- [x] `/api/chat/` lit la clé au coffre de l'appelant ; un `api_key` du corps est ignoré ; sans clé : 400 `key_not_configured`, aucun appel
- [x] Front : saisie envoyée au coffre puis effacée, état « enregistrée » lu sur l'API ; anciennes entrées `ai_claude_key` / `ai_mistral_key` effacées de `localStorage` à l'ouverture, sans être envoyées
**Tests à passer avant de clore le lot :**
- [x] `python manage.py test api.tests.CoffreClesTests` passe (configured seul, chiffré en base, survit à un changement de `SECRET_KEY`, clé d'autrui ni lue ni utilisée, autre `azp` refusé, fournisseur simulé recevant la clé du coffre, réponse sans la clé)
- [ ] Après une conversation, aucune clé dans `localStorage` (navigateur réel) ; la clé n'apparaît jamais dans une réponse
**Vérifié le :** 2026-11-01 — `bash chantiers/tests/essai.sh app-builder` vert (CoffreClesTests, ChatTests, BudgetContexteTests compris) ; `npx ng build` sans erreur. Non déployé ; navigateur réel à faire après déploiement.

## Lot 9 — Documentation et modèles à jour   ·   statut : à faire
**Objectif :** un README qui décrit l'app et l'API de remise à lab-admin, et une liste de modèles IA juste.
**Tâches :**
- [ ] `README.md` : but, pages, API de l'éditeur, API de remise `/api/handoff/…` (codes 401/403/404/409, `KEYCLOAK_HANDOFF_CLIENTS`), tests. Aujourd'hui cette API n'est décrite que dans `chantiers/app-builder-lab/CONTRAT.md`, non versionné.
- [ ] Table des modèles de `budget.py:37-52` à mettre à jour (fenêtres Mistral posées « de mémoire »)
- [ ] Renommer `/preview` (page « Livrables ») en `/livrables`, avec redirection ; retirer de `TYPE_LABELS` les types Spring, qui ne sont plus « prêts »
- [ ] Supprimer la branche fusionnée `worktree-agent-a92726caa5e3e0dce` (toujours là le 2026-11-08) ; réduire les budgets de style dépassés (cinq feuilles)
**Tests à passer avant de clore le lot :**
- [ ] `npm run build` sans avertissement de budget ; `/livrables` et l'ancien `/preview` s'ouvrent ; `BudgetContexteTests` vert
**Vérifié le :**

## Lot 10 — Parcours réel et gabarit front   ·   statut : en cours
**Objectif :** prouver la remise jusqu'au déploiement, et aligner le front sur le gabarit (T3).
**Tâches :**
- [ ] Ⓟ Avec un compte GitHub humain : spécification → « Lancer la construction » → projet créé avec `FEUILLE_DE_ROUTE.md` et `CAHIER_DES_CHARGES.md` greffés → déployé
- [x] `tokenBases()` (API d'App Builder seule, `core/env.ts`) et `core/token-scope.ts` dans l'intercepteur ; `pkceMethod: 'S256'` ; `redirect-uri.ts` aligné sur lab-admin ; ports liés à `${LAB_BIND_ADDR:-127.0.0.1}` (chantier « failles », I1/I2)
- [ ] Thème sombre vérifié
**Tests à passer avant de clore le lot :**
- [ ] Le projet créé passe `validate-app.sh --quality-only` et se déploie
**Vérifié le :** 2026-11-01 — gabarit front : `npx ng build` sans erreur — non déployé (PKCE côté Keycloak posé par l'architecte après déploiement). Mis en service le 2026-11-01 (section suivante).

## Lot 11 — App Builder v2 : forme universelle, outils IA, Claude Code, vues   ·   statut : en cours
**Objectif :** toute app constructible sur le cadriciel se décrit dans la spécification (qui voit quoi, rôles, cycles de vie, tâches de fond, intégrations du lab), l'IA la construit par des outils plutôt que par du JSON en texte — avec Mistral, une clé Claude, ou Claude Code / Vibe de l'utilisateur —, et la personne la voit du global au détail. Contrat et études : `chantiers/app-builder-v2/` à la racine du lab.
**Tâches :**
- [x] Métamodèle additif (migrations `0011`, `0012`) : `roles`, `jobs`, `integrations`, `external_apis`, `extensions`, règles métier typées ; par modèle `kind`, `access`, `states`, `constraints` ; types de champ `date email url enum secret geo_point geometry` ; `Endpoint.auth` ; `Page.public`/`public_reason`/`required_roles` ; composants, interactions et étapes élargis
- [x] Opérations atomiques (`patching.essayer_operations`, `appliquer_operations`, `version_de`, `resume_operations`) : essai à blanc par le sérialiseur, refus en bloc avec erreurs indexées, version (409), historique et annulation
- [x] Lecture compacte pour l'IA (`api/lecture.py` : index de la spec, lecture d'éléments à la demande) ; `conformite.verifier` (blocages + avertissements de qualité)
- [x] Chat par outils (`api/ia/`) commun Claude et Mistral : boucle bornée, propositions appliquées par l'utilisateur (`POST /api/apps/<id>/operations/`), repli en sortie structurée, prompt unique réécrit, cache Anthropic, table des modèles à jour ; protocole `PATCH_READY`/`CHOICES_*` retiré ; spec lue en base
- [x] Jeton d'abonnement Claude (`sk-ant-oat…`) refusé au coffre (conditions d'Anthropic) ; Claude Code et Vibe passent par le serveur MCP (`POST /api/mcp/`, jetons personnels `abt_…`, page `/connexion-ia`)
- [x] Graphe v2 (`ref`, `edit`, `issues`, matrices CRUD et sécurité, séquences, nouvelles échelles) ; vue d'ensemble avec inspecteur, ER, API, sécurité, plan du site, cycles de vie, tâches ; éditeurs des nouvelles structures ; `schema-canvas` retiré
- [x] Remise : cahier sans troncature, empreinte `sha256` (liste, détail, kit, ligne du cahier), tests de lot dérivés des règles d'accès et des transitions
- [x] Mise en service et parcours en navigateur réel (2026-11-11, compte `e2edev`)
- [ ] Ⓟ Un vrai appel Claude et Mistral avec outils depuis le chat (clé au coffre du propriétaire)
- [ ] Claude Code relié par MCP depuis un espace de travail (`claude mcp add …` de `/connexion-ia`), un tour lecture + application
**Tests à passer avant de clore le lot :**
- [x] `python manage.py test api.tests.MetamodeleSerialiseurTests api.tests.MetamodelePatchTests api.tests.VerifierTests api.tests.MigrationMetamodeleV2Tests` (forme v2, migration sans perte)
- [x] `python manage.py test api.tests.OperationsTests api.tests.OperationsEnregistrementTests api.tests.LectureTests`
- [x] `python manage.py test api.tests.ChatOutilsClaudeTests api.tests.ChatOutilsMistralTests api.tests.ChatGardeFousTests api.tests.PromptTests api.tests.OperationsVuesTests`
- [x] `python manage.py test api.tests.McpJetonsTests api.tests.McpProtocoleTests api.tests.McpCloisonnementTests` (jeton expiré, révoqué, d'autrui, portée, `abt_` refusé hors `/api/mcp/`, jeton Keycloak refusé sur `/api/mcp/`)
- [x] `python manage.py test api.tests.VueEnsembleTests api.tests.FeuilleDeRouteGenereeTests api.tests.CahierDesChargesTests api.tests.RemiseAuLabTests`
- [x] `npm run build` du frontend sans erreur ; aucune couleur en dur dans les fichiers touchés
- [x] Test de cloisonnement vert après mise en service (3/3, 2026-11-11)
**Vérifié le :** 2026-11-11 — `bash chantiers/tests/essai.sh app-builder` : 253 tests OK ; image du commit `b6f7d10` construite pendant que l'ancienne tournait, `scripts/app-test.sh app-builder` : 253 tests OK sur cette image ; `npx ng build` sans erreur (avertissements de budget de style). **Mis en service le 2026-11-11** (fusion `6a6318d`, mêmes images, `up -d --no-build`) : migrations `0011`/`0012` jouées, les deux specs existantes identiques avant/après (comptes de lignes comparés à l'instantané) ; cloisonnement `lab-runner` 3/3. Navigateur réel (`e2edev`) : jeton créé sur `/connexion-ia`, puis par le MCP public `initialize`, `tools/list` (10 outils), `creer_spec`, `appliquer_operations` (18 opérations en un bloc), `lire_index`, `verifier_spec`, `lire_livrables`, et `version_perimee` refusé ; vues Données (ER), Sécurité (matrice, une case « à revoir » expliquée), Cycles de vie, API, sans erreur console ni réponse d'API en échec ; la spec apparaît « prête » dans lab-admin avec l'aperçu des lots. Restent : un vrai appel Claude et Mistral avec outils (aucune clé du compte d'essai), Claude Code réel relié par MCP. Défaut vu : dans le schéma des cycles de vie, la pointe de la flèche « en_cours → rendu » se lit mal (la liste dessous est juste).

## Lot 12 — Fournisseurs d'IA génériques, et Albert de la DINUM   ·   statut : en cours
**Objectif :** le chat sait parler à tout fournisseur compatible OpenAI, en plus de Claude ; Albert (API de la DINUM, https://albert.api.etalab.gouv.fr/v1) est le troisième, avec ses modèles lus en direct.
**Tâches :**
- [x] Registre des fournisseurs dans `budget.py` (protocole `anthropic` ou `openai`, adresse, champ du coffre) ; plus aucun « tout ce qui n'est pas Mistral est Claude »
- [x] Adaptateur unique `openai` (Mistral et Albert) dans `api/ia/fournisseurs.py` ; outils au format `function` ; `tool_choice: "auto"` explicite (exigé par DeepSeek V4 sur Albert)
- [x] Coffre : colonne `albert_key` (migration), même chiffrement ; `GET/PUT /api/ai-keys/` gagne `albert_key`
- [x] Modèles d'Albert lus par `GET /v1/models` avec la clé de l'utilisateur (type `text-generation`, `max_context_length`), mis en cache ; à défaut, table prudente d'après la doc (alias `openweight-*`)
- [x] Messages d'erreur qui renvoient à la page « Intelligence artificielle » (plus au ⚙)
**Tests à passer avant de clore le lot :**
- [x] `python manage.py test api.tests.AlbertTests` : boucle d'outils complète contre un Albert simulé (adresse, en-tête, `tool_choice`), clé lue au coffre, catalogue dynamique (filtre de type, fenêtre, panne ⇒ table prudente), clé refusée/quota ⇒ message fixe
- [x] Suites `ChatOutilsMistralTests`, `ChatOutilsClaudeTests`, `CoffreClesTests`, `BudgetContexteTests` vertes
- [ ] Ⓟ Un vrai échange avec outils sur Albert, avec la clé du propriétaire
**Vérifié le :** 2026-11-11 — `bash chantiers/tests/essai.sh app-builder` : 264 tests OK, dont `AlbertTests` (11 : adresse, en-tête, `tool_choice` explicite, boucle complète, contenu vide de Gemma, clé du seul appelant, erreurs 401/404/429 à message fixe, catalogue filtré et mis en cache, panne ⇒ table prudente). Le chat ne propose Albert qu'avec le lot 13 (interface) ; l'essai réel attend la clé du propriétaire.

## Lot 13 — Une page « Intelligence artificielle » unique   ·   statut : livré
**Objectif :** un seul endroit pour régler l'IA (fournisseurs, clés, modèles, Claude Code et Vibe) ; le chat de l'accueil n'en garde qu'un sélecteur rapide, et les choix sont gardés sur le serveur.
**Tâches :**
- [x] `GET/PUT /api/ai-settings/` : fournisseurs (clé configurée ou non, modèles, modèle par défaut) et préférences de l'appelant (fournisseur et modèle par fournisseur), gardées en base
- [x] Page `/ia` (l'ancienne `/connexion-ia` y redirige) : fournisseurs (clé, état, modèle par défaut), fournisseur par défaut du chat, puis Claude Code et Vibe
- [x] ⚙ du chat : sélecteur fournisseur + modèle, limité aux fournisseurs qui ont une clé, et lien vers `/ia` ; plus de saisie de clé dans le chat ; plus de préférence dans `localStorage`
**Tests à passer avant de clore le lot :**
- [x] `python manage.py test api.tests.PreferencesIATests` (préférences de l'appelant seulement, fournisseur ou modèle inconnu refusé, jamais de clé rendue)
- [x] `npx ng build` sans erreur ; navigateur réel : la page montre l'état des clés, le chat ne propose que les fournisseurs configurés
**Vérifié le :** 2026-11-11 — suite 271 OK (`PreferencesIATests` 5) ; mis en service (image construite pendant que l'ancienne tournait, `app-test.sh` vert, migrations `0013`/`0014`, cloisonnement 3/3). Navigateur réel (`e2edev`) : `/connexion-ia` redirige vers `/ia` ; une clé Albert déposée passe « clé enregistrée » et « utilisée par le chat » ; le ⚙ de l'accueil ne propose qu'Albert, avec ses modèles ; un message part vers le vrai serveur d'Albert, qui refuse la fausse clé : message fixe, sans la clé ; « Retirer » efface la clé. Défaut vu et corrigé : le ⚙ et l'en-tête débordaient du panneau étroit.

## Lot 14 — Claude Code des utilisateurs, par le MCP, fiabilisé   ·   statut : livré
**Objectif :** un utilisateur relie son propre Claude Code (son abonnement, sur son poste ou dans son espace de travail du lab) à App Builder sans tâtonner, et Claude Code y travaille avec les mêmes garde-fous que le chat.
**Tâches :**
- [x] Configuration prête : `.mcp.json` de projet sans secret (`${APP_BUILDER_MCP_TOKEN}`), en plus de la commande `claude mcp add`
- [x] Consignes du lab servies en invites MCP (`prompts/list`, `prompts/get`) : `/mcp__app-builder__concevoir`, `…__verifier`
- [x] La page montre la dernière connexion de chaque jeton (« Claude Code s'est connecté le … »)
**Tests à passer avant de clore le lot :**
- [x] `python manage.py test api.tests.McpProtocoleTests` (invites comprises)
- [x] Un vrai Claude Code relié par `--mcp-config` lit une spec et y applique une opération
**Vérifié le :** 2026-11-11 — Claude Code 2.1.322 de l'hôte (abonnement du propriétaire, avec son accord), `--mcp-config` sur le `.mcp.json` proposé par la page (jeton lu dans `APP_BUILDER_MCP_TOKEN`), `--strict-mcp-config`, jeton d'essai d'`e2edev` limité à la spec 22 puis révoqué : `lire_index` puis `appliquer_operations` → « 1 champ ajouté à Livre », visible dans `patch_applications` (mode `ops`) ; `/mcp__app-builder__verifier 22` : relecture complète, corrections vérifiées par `essayer_operations`, rien d'appliqué sans accord. Il a relevé que les consignes ne décrivaient pas `query_params` : ligne ajoutée au prompt, mise en service.

## Lot 15 — Claude Code ouvert depuis App Builder, dans le lab   ·   statut : à faire
**Objectif :** un bouton « Concevoir avec Claude Code » ouvre une conversation avec le Claude Code de l'utilisateur, dans le lab, déjà reliée à sa spec.
**Tâches :**
- [ ] Chantier moteur (régime chantier) : espace de travail sans projet, pose du jeton MCP d'App Builder avec l'accord de l'utilisateur — à cadrer après le lot 14
**Tests à passer avant de clore le lot :**
- [ ] Contrat du chantier écrit ; parcours réel bout en bout
**Vérifié le :**

## Mise en service — chantier « failles » (2026-11-01)
Les mentions « non déployé » ci-dessus datent d'avant cette mise en service. Image construite pendant
que l'ancienne tournait, `scripts/app-test.sh` : 167 tests OK, puis `up -d --no-build` ; ports
publiés sur `127.0.0.1` ; client Keycloak passé en PKCE S256 exigé, URI de retour réduites à celles de
l'app (`create-app-client.sh --pkce --prune-uris`) ; cloisonnement `lab-runner` 3/3 avant et après le durcissement du client, puis de nouveau 3/3 sur Keycloak 26.8.1.
Restent les vérifications en navigateur réel notées dans les lots (images, coffres de clés, envois).
