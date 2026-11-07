# Chappie V50.1 — migration de schéma Turso (préparation)

**Statut :** préparation technique uniquement. Aucun accès en écriture à Turso de production et aucun basculement du stockage.

## État de départ audité

L'audit de production du 7 novembre 2026 a relevé 41 tables / 84 objets dans SQLite et 13 tables / 18 objets dans Turso. Turso présente 28 tables et 38 index manquants, ainsi qu'une colonne `skills.xp` absente. Les cinq lignes Turso présentes à l'audit se trouvent dans `emotional_state`, `journal`, `maintenance_state`, `relationships` et `voice_profiles`. Aucune ligne de conversation ou mémoire n'a été comptée dans Turso à cet instant.

## Ce que fait le lot V50.1

- Construit un plan depuis le schéma SQLite vers le schéma Turso.
- Ne lit aucun contenu métier de ligne pour construire le plan.
- Prévoit les tables manquantes, les index manquants et l'ajout explicitement autorisé de `skills.xp REAL NOT NULL DEFAULT 0.0`.
- Bloque les colonnes manquantes non prévues et les objets non pris en charge.
- N'inclut aucune copie, fusion, mise à jour ou suppression de données.
- N'exécute rien par défaut : `apply_migration_plan(...)` reste en mode simulation sauf si un appelant fournit explicitement `apply=True`.

## Garde-fous

1. La migration n'est pas raccordée au démarrage de l'application ni à une route HTTP.
2. La fabrique de stockage de production reste non activée ; SQLite demeure le stockage de l'application.
3. Le plan doit être exécuté et vérifié sur une copie isolée avant toute écriture distante.
4. Avant toute migration de production : sauvegarde Turso exportable et vérifiée, sauvegarde durable de la source SQLite, contrôle de schéma, validation des conflits et accord explicite.
5. Les cinq lignes Turso existantes doivent être préservées. Aucune copie automatique depuis SQLite n'est autorisée, en particulier lorsque la base source observée est vide.
6. La migration des données et le basculement applicatif constituent des étapes séparées nécessitant chacun une validation explicite.

## Tests attendus

- Le mode simulation ne modifie ni schéma ni lignes.
- L'application additive crée une table et un index manquants et ajoute `skills.xp`.
- Les lignes préexistantes restent identiques.
- Une seconde exécution ne planifie aucune opération supplémentaire.
- Une colonne inattendue bloque l'application.

## Limite importante

La préparation du code et les tests locaux ne constituent pas une sauvegarde de la base distante, ni une preuve qu'une migration de production est sûre. Aucun endpoint de migration distante n'est exposé dans cette version.
