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

## Préparation des sauvegardes vérifiables

### SQLite local (sauvegarde prise en charge par le code)

Le dépôt contient déjà `storage.backup.create_verified_backup(source_path, backup_path)`. Cette fonction :
- utilise l'API de sauvegarde SQLite pour obtenir une copie cohérente ;
- vérifie `PRAGMA integrity_check` sur la copie ;
- calcule un SHA-256 et renvoie le chemin, la taille, le checksum et l'état d'intégrité ;
- refuse que la destination soit le fichier source.

La restauration vérifiée préserve également une copie de retour arrière avant le remplacement. Les tests `test_v50_backup_restore_rollback.py` couvrent sauvegarde, restauration, rollback et rejet d'une sauvegarde corrompue.

**Limite Render :** le fichier SQLite du conteneur peut être éphémère sur une instance sans disque persistant. Une sauvegarde stockée uniquement dans le même conteneur n'est pas une sauvegarde durable. Il faudra exporter le fichier vers un stockage externe contrôlé et vérifier son SHA-256 avant toute opération.

### Turso distant (export logique préparé, non exécuté)

Un exporteur logique portable est maintenant ajouté dans `storage.logical_backup`. Il accepte une connexion déjà ouverte, lit les tables et les objets de schéma, encode les BLOB, produit un fichier JSON et son SHA-256, puis restaure le fichier dans une SQLite temporaire pour vérifier l'intégrité, les clés étrangères et les compteurs. Il refuse d'écraser un fichier de sauvegarde existant.

Cet exporteur n'ouvre pas de connexion et ne lit aucun secret : il n'est pas raccordé au serveur, à une route HTTP ou au démarrage. Il n'a pas été exécuté sur la base de production.

La documentation officielle Turso décrit le dump SQL par la CLI :

```bash
turso db shell chappie-db .dump > chappie-db-backup.sql
sha256sum chappie-db-backup.sql
```

Pour vérifier la restauration sans toucher à la production, utiliser uniquement un fichier local neuf :

```bash
sqlite3 chappie-db-restore-test.sqlite < chappie-db-backup.sql
sqlite3 chappie-db-restore-test.sqlite "PRAGMA integrity_check;"
sqlite3 chappie-db-restore-test.sqlite ".tables"
```

Ne jamais exécuter la restauration contre `chappie-db` lui-même. Conserver le dump et son checksum dans un emplacement privé hors Render ; ne pas les ajouter au dépôt Git. La commande `.dump` est documentée dans le guide Turso de développement local.

Avant toute écriture Turso, il faudra donc :
1. obtenir un export/snapshot de la base `chappie-db` via un mécanisme Turso officiellement pris en charge ;
2. conserver l'artefact hors du service Render ;
3. calculer et archiver son SHA-256 ;
4. vérifier que l'artefact est lisible/restaurable dans une base de test isolée ;
5. relever les compteurs de lignes et l'inventaire de schéma avant/après.
   
Tant que cette sauvegarde distante n'est pas démontrée restaurable, la migration de production est bloquée. La base `chappie-memory` distincte n'est pas la cible.

## Garde-fous

1. La migration n'est pas raccordée au démarrage de l'application ni à une route HTTP.
2. La fabrique de stockage de production reste non activée ; SQLite demeure le stockage de l'application.
3. Le plan doit être exécuté et vérifié sur une copie isolée avant toute écriture distante.
4. Avant toute migration de production : sauvegarde Turso exportable et vérifiée, sauvegarde durable de la source SQLite, contrôle de schéma, validation des conflits et accord explicite.
5. Les cinq lignes Turso existantes doivent être préservées. Aucune copie automatique depuis SQLite n'est autorisée, en particulier lorsque la base source observée est vide.
6. La migration des données et le basculement applicatif constituent des étapes séparées nécessitant chacun une validation explicite.

## Tests attendus

- Le mode simulation ne modifie ni schéma ni lignes.
- L'export logique refuse l'écrasement, vérifie son SHA-256, restaure les données dans une SQLite isolée et compare les compteurs de lignes.
- L'application additive crée une table et un index manquants et ajoute `skills.xp`.
- Un test d'intégration lance les véritables initialisateurs de schéma de Chappie dans un fichier SQLite temporaire, reconstruit le schéma dans une cible mémoire vide et compare les inventaires.
- Les lignes préexistantes restent identiques.
- Une seconde exécution ne planifie aucune opération supplémentaire.
- Une colonne inattendue bloque l'application.

## Limite importante

La préparation du code et les tests locaux ne constituent pas une sauvegarde de la base distante, ni une preuve qu'une migration de production est sûre. Aucun endpoint de migration distante n'est exposé dans cette version.
