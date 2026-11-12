# Chappie V50.79 — adoption prudente d'un schéma Turso existant

## But

Cette procédure permet de reprendre une base Turso qui contient déjà le schéma applicatif Chappie, mais aucun marqueur de stockage. Elle ne prétend pas qu'une migration SQLite a eu lieu.

## Garde-fous

L'adoption exige explicitement :

- `CHAPPIE_STORAGE_BACKEND=turso`
- `CHAPPIE_TURSO_CUTOVER_READY=1`
- `CHAPPIE_TURSO_ADOPT_EXISTING_SCHEMA=1`
- `TURSO_DATABASE_URL` et `TURSO_AUTH_TOKEN`

Le mode bootstrap neuf (`CHAPPIE_TURSO_FRESH_START=1`) et le mode adoption sont mutuellement exclusifs.

Avant toute initialisation, Chappie vérifie en lecture seule la présence des 13 tables principales et de leurs colonnes indispensables. Une table absente ou une colonne requise manquante bloque le démarrage. La colonne historique `skills.xp` reste facultative.

Après réussite des initialiseurs de schéma, Chappie écrit le marqueur distinct `turso-existing-schema-adoption-v1`. Il n'écrit jamais `sqlite-to-turso-v50.65` et ne modifie pas le marqueur de migration SQLite.

Les initialiseurs utilisent les créations idempotentes du schéma applicatif. Aucun ordre de suppression, vidage ou réinitialisation n'est exécuté par cette procédure. Les lignes déjà présentes dans les tables métier sont conservées.

## Activation contrôlée

Ne définir la variable d'adoption qu'après revue et fusion de la PR, validation des tests CI, confirmation de la sauvegarde chiffrée et accord explicite du propriétaire de l'instance.

Activer d'abord les variables sur un environnement de test si possible. En production, changer les variables Render uniquement après confirmation explicite et vérifier les journaux de démarrage. Ne pas activer simultanément le mode bootstrap neuf.

## Marqueurs

- `sqlite-to-turso-v50.65` : migration réelle des données SQLite vers Turso.
- `turso-fresh-bootstrap-v1` : initialisation d'une base Turso vide, sans migration SQLite.
- `turso-existing-schema-adoption-v1` : adoption d'un schéma Chappie préexistant et compatible, sans migration SQLite.

Ces marqueurs sont volontairement distincts.
