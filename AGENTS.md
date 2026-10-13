# app-builder — règles de travail (pour toute IA, et tout humain)

Ce projet tourne dans un lab partagé et exposé sur Internet. Ces règles ne sont pas des conseils.

## Méthode — lot par lot

1. **Avant de coder, écris le lot** dans `FEUILLE_DE_ROUTE.md` : objectif, tâches, et les tests qui
   prouveront qu'il est fini. Pas de code sans lot écrit.
2. **Un seul lot « en cours » à la fois.** Termine-le avant d'ouvrir le suivant.
3. **Ne clos jamais un lot sans avoir lancé ses tests.** Note sous « Vérifié le » la date et ce que
   tu as réellement lancé, avec le résultat. « Devrait marcher » n'est pas une vérification.
4. **Un lot livré = un commit poussé** sur GitHub, avec la feuille de route à jour dans le même commit.
5. **Ne change pas le format de `FEUILLE_DE_ROUTE.md`** : une machine le lit. Titres de lot :
   `## Lot <N> — <titre>   ·   statut : à faire | en cours | livré`.

## Déployer

- **Par le moteur du lab uniquement** : outil MCP `deploy`, ou le bouton « Déployer » de lab-admin.
  Jamais de `docker`, jamais de script lancé à la main : tu n'y as pas accès, et c'est voulu.
- Seul un **commit poussé** est déployable. Le déploiement lance les tests backend (section
  « Commande de test » de la feuille de route) : **s'ils échouent, rien n'est mis en service** et
  l'ancienne version continue de tourner. Lis le journal, corrige, repousse.
- Après le déploiement, le test de cloisonnement est lancé et son résultat affiché dans l'état du projet.

## Règles du lab qui s'imposent à cette app

- **Cloisonnement à deux verrous, ne jamais en retirer un.** (1) Le flow Keycloak refuse à la
  connexion qui n'est pas du groupe requis. (2) L'API vérifie elle-même, dans
  `api/authentication.py`, que le jeton vient de ce client (`azp`) et que ses `groups` croisent
  `KEYCLOAK_REQUIRED_GROUPS`. Toute nouvelle route d'API reste derrière cette authentification ;
  une route publique est une décision à écrire dans la feuille de route, pas un oubli.
- **`frontend/e2e/cloisonnement.spec.ts` ne se modifie pas** et ne dépend d'aucun contenu de l'app.
  Pas d'autre fichier de test E2E.
- **Fichiers des utilisateurs : par l'API `storage` du lab.** Pas de volume média, pas de blob en base.
- **Base de données** : uniquement celle que désigne `.env` (`DB_NAME`, `DB_USER`, `DB_SCHEMA`).
  Ne les change pas ; tu n'as accès à aucune autre.
- **Interface : identité « Foyer ».** Aucune couleur en dur (tokens CSS de `src/styles.scss`),
  navigation verticale, rupture à 900 px, polices embarquées, cibles tactiles de 44 px minimum.
- **Pour envoyer un email : `send_mail(...)` de Django, rien d'autre.** Le compte SMTP se règle
  dans lab-admin (carte « Email » du projet), jamais dans le dépôt ni dans `settings.py`. Sans
  compte rattaché, les emails s'affichent dans le journal du conteneur.
- **Aucun secret dans le dépôt.** `.env` et `.keycloak-client-opts` sont ignorés par git et
  appartiennent au lab : ne les ajoute jamais (`git add -f` fait refuser le déploiement). Une clé
  d'API se règle par l'outil `env_set`, pas dans le code.
- **`docker-compose.yml`** : pas de `privileged`, pas de montage hors du dossier, pas d'autre réseau
  que `dev-net`/`sso-net`, pas d'autre port que ceux du projet, chemins Caddy `/app-builder` et
  `/app-builder-api` seulement. Le déploiement refuse le reste et dit pourquoi.

## En cas de blocage

Ne contourne pas une règle pour avancer. Écris ce qui bloque dans la feuille de route et ouvre un
ticket (`gh issue create` depuis le terminal du projet, ou le bouton « Ticket » de lab-admin).

## Propre à app-builder

Voir la section du même nom dans `CLAUDE.md` : service du cadriciel, tables lues par lab-admin,
patchs appliqués par le serveur, interface `/api/handoff/` figée, aucun appel réel à une IA en test.
