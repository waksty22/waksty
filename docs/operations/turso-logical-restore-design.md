# Plan de restauration logique Turso sécurisée

## Statut

Conception uniquement. Ce document n'autorise aucune écriture, ne change aucun réglage de déploiement et ne se connecte pas à une base de production.

## Briques existantes

- `storage.logical_backup.verify_encrypted_logical_backup()` authentifie l'archive AES-256-GCM, vérifie son sidecar SHA-256, déchiffre dans un répertoire temporaire privé et reconstruit l'instantané dans une base SQLite isolée.
- Le format logique est versionné (`chappie-turso-logical-backup`, version 1) et transporte définitions de tables, lignes, index, vues, triggers et résumés de comptage.
- `storage.hrana_http.HranaHttpTransaction` est volontairement en lecture seule : requêtes `SELECT` simples et contrôle de transaction uniquement. Ce client doit rester en lecture seule.
- `storage.data_migration.migrate_sqlite_rows_to_turso()` est un chemin séparé de migration SQLite vers Turso. Il possède une barrière explicite `apply=True`, un plan de schéma, des contrôles de collision, une vérification des lignes, des contrôles de clés étrangères et un marqueur de migration. Ce n'est pas une API de restauration portable : ses hypothèses de source et ses marqueurs décrivent une migration, pas une restauration depuis une archive.
- `backend/scripts/test_chappie_full_schema_turso_e2e.py` teste une restauration complète sur une base Turso de test isolée, à partir de ses propres données synthétiques et de sa propre archive. Ce test ne restaure pas l'artefact quotidien réel et n'écrit jamais dans la base de production.

## Architecture de restauration proposée

Créer un chemin de restauration distinct, explicitement autorisé en écriture. Ne pas affaiblir ni réutiliser le transport de sauvegarde en lecture seule.

1. **Prévalidation hors ligne de l'artefact :** accepter un chemin d'archive explicite et une clé fournie par l'opérateur ; rejeter traversal de chemins, entrées ZIP dupliquées, fichiers inattendus, archives trop volumineuses, sidecars de checksum invalides, versions non prises en charge, identifiants invalides et ordre SQL invalide. Authentifier et vérifier l'archive avant toute connexion à une cible.
2. **Staging isolé :** déchiffrer uniquement dans un répertoire temporaire privé ; reconstruire dans une base SQLite temporaire ; exécuter `integrity_check`, `foreign_key_check`, inventaire exact des tables/objets et vérification des nombres de lignes. Ne jamais journaliser les valeurs de lignes, identifiants secrets ou clés de chiffrement.
3. **Identité explicite de la cible :** exiger une URL et un jeton de cible fournis séparément. Ne jamais lire implicitement la cible de production depuis l'environnement par défaut de l'application. Exiger une confirmation opérateur de l'identité de la cible ; n'afficher qu'un nom/hôte sûr, jamais de jeton.
4. **Prévalidation fail-closed :** inspecter les métadonnées et les volumes de la cible. Par défaut, accepter uniquement une cible de restauration dédiée et vide. Rejeter toute table utilisateur ou ligne existante. Ne pas créer automatiquement de base et ne pas modifier les paramètres du fournisseur.
5. **Application du schéma et des données :** utiliser un transport Hrana dédié aux écritures, avec insertions paramétrées et liste stricte de commandes de transaction autorisées. Créer les objets dans un ordre respectant les dépendances ; insérer les lignes par lots ; reconstruire index/vues/triggers lorsque nécessaire. Gérer explicitement les dépendances de clés étrangères ; ne jamais désactiver les contrôles pour forcer une restauration.
6. **Atomicité et résultat incertain :** effectuer toutes les modifications de cible dans une transaction lorsque le fournisseur le permet. Si le transport perd son baton ou si la réponse de commit est ambiguë, arrêter et marquer le résultat comme inconnu ; ne jamais relancer aveuglément. Fournir une commande de réconciliation en lecture seule pour inspecter les comptes et le marqueur de restauration avant toute nouvelle tentative.
7. **Vérification après restauration :** comparer inventaires exacts des tables/objets, nombres de lignes par table, empreintes de contenu stables par table, `integrity_check` et `foreign_key_check`. Ne valider le commit qu'après réussite de tous les contrôles. Ne rapporter que des nombres et des empreintes, jamais le contenu des lignes.
8. **Traçabilité :** enregistrer un identifiant de restauration, le SHA-256 de l'artefact source, une empreinte d'identité de cible, la version de format, les volumes, les horodatages et le résultat de vérification. Ne jamais stocker identifiants ou clés de chiffrement dans la base ou les journaux.

## Tests obligatoires avant de considérer l'implémentation terminée

- archive chiffrée valide ; mauvaise clé ; ciphertext altéré ; sidecar absent/incohérent ; JSON malformé ; version de format inconnue ;
- traversal ZIP, entrées dupliquées, fichiers inattendus, limites de taille ;
- cible vide acceptée ; cible non vide rejetée sans écriture ;
- incompatibilité de schéma et objets virtuels/générés non pris en charge rejetés ;
- BLOB, NULL, entier, flottant, Unicode et doublons préservés ;
- échec pendant création de schéma, insertion par lots, contrôle FK ou vérification pré-commit entraînant le rollback de toutes les modifications ;
- perte simulée de connexion pendant COMMIT produisant un résultat explicitement inconnu et aucune relance automatique ;
- restauration réussie réouvrable via une nouvelle connexion et conforme aux inventaires, volumes et empreintes source ;
- tous les tests d'intégration utilisent SQLite temporaire ou une base Turso jetable dédiée, jamais la production.

## Barrières opérateur

1. Fusionner le design et son implémentation uniquement après revue et CI.
2. Créer manuellement une base Turso jetable dédiée ; ne jamais utiliser `chappie-db` comme cible de test.
3. Configurer les identifiants via le gestionnaire de secrets approuvé ; ne jamais coller de secrets dans le chat ou le dépôt.
4. Exécuter une prévalidation à blanc et vérifier l'identité de la cible.
5. Restaurer et vérifier une sauvegarde dans cette base isolée.
6. Documenter une procédure de reprise approuvée par un humain avant toute restauration de production.

## Exclusions explicites

- Aucune restauration, migration, réinitialisation, suppression, troncature ou modification de schéma en production.
- Aucun provisionnement automatique de base, création de secret ou changement d'environnement Render/GitHub.
- Aucun changement du client de sauvegarde existant en lecture seule.
- Aucune affirmation de préparation à la reprise après sinistre tant qu'une restauration isolée de l'artefact réel n'a pas réussi de bout en bout.
