# V36.7 — Intégration réelle de la mémoire autobiographique avec libSQL

## Périmètre

Cette étape exerce le module existant `memory/autobiographical.py` avec
l'adaptateur `storage/libsql_adapter.py`, sur une base libSQL locale
`:memory:`. La table `conversations` utilisée comme source est minimale et
créée uniquement dans le test.

## Scénarios couverts

- Création du schéma autobiographique et de ses index.
- Synchronisation des conversations en événements autobiographiques.
- Idempotence de la synchronisation et de l'initialisation du schéma.
- Création des liens entre messages utilisateur/assistant partageant le même horodatage.
- Recherche insensible à la casse et échappement littéral des jokers SQL.
- Pagination, statistiques et isolation par utilisateur.
- Ignorer les rôles non pris en charge et les contenus vides.

## Limites explicites

- Aucun changement du module autobiographique de production.
- Aucune modification de la fabrique de connexion de `server.py`.
- Aucun accès à Turso distant (`chappie-db` ou `chappie-memory`).
- Aucun déploiement Render et aucune migration de données.

Les tests utilisent exclusivement le pilote libSQL avec une base locale
éphémère. Cette étape valide le comportement du module, pas encore une
bascule de stockage en production.
