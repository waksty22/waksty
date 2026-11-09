# V50.41 — Contrat de compatibilité Turso/libSQL

## Décision

Turso reste bloqué à la frontière de l'application. Cette version formalise les capacités et les incompatibilités observées sans se connecter à Turso et sans toucher à Render.

## Capacités déjà présentes

- Fabrique de connexion libSQL distincte de la connexion applicative SQLite.
- Adaptateur DB-API avec lignes nommées/positionnelles, curseurs, fetchone/fetchall/fetchmany, exécution paramétrée, commit/rollback et context manager.
- Traduction partielle des erreurs libSQL vers les exceptions sqlite3.
- Garde-fou de la fabrique applicative qui refuse explicitement le backend Turso.

## Blocages confirmés dans le serveur

1. **Initialisation** : init_db envoie PRAGMA journal_mode=WAL et un gros executescript. WAL est une propriété du fichier SQLite local ; la stratégie d'initialisation distante doit être séparée.
2. **Sauvegarde** : le backup SQLite natif Connection.backup n'existe pas dans LibSQLConnectionAdapter. Turso doit disposer d'un export logique cohérent et restaurable, distinct du snapshot de fichier.
3. **Diagnostics** : PRAGMA database_list, fichiers WAL/SHM, mountinfo et integrity_check de fichier ne décrivent pas une base distante. Il faut un diagnostic backend-neutral avec identité de backend, ping, schéma, contraintes et état du service.
4. **Contrat de curseur** : lastrowid et rowcount sont simplement relayés depuis le pilote natif ; leur comportement doit être vérifié pour INSERT, INSERT OR IGNORE, executemany et opérations distantes.
5. **Transactions** : le context manager de l'adaptateur reproduit commit/rollback DB-API, mais ne prouve pas l'atomicité distante, les limites de transaction ni le comportement après timeout/réseau interrompu.
6. **SQL** : chaque migration, PRAGMA, script multi-instructions, contrainte, index, trigger, fonction date/JSON et requête métier doit être exécuté contre une base Turso de test dédiée avant activation.
7. **Sonde actuelle** : inspect_turso_driver vérifie si la connexion native est une sqlite3.Connection. Ce test décrit le type natif, pas l'aptitude de l'adaptateur ; il ne doit pas être utilisé seul comme verdict de compatibilité de l'application.

## Contrat requis avant activation

- Séparer init_sqlite_schema et init_turso_schema ; ne jamais envoyer WAL/SHM ou diagnostics de fichiers au backend distant.
- Remplacer toute dépendance à Connection.backup par un export logique versionné, cohérent et chiffré, avec restauration isolée.
- Formaliser les méthodes de connexion réellement utilisées : execute, executemany, executescript ou équivalent, commit, rollback, close, context manager, cursor metadata, lastrowid, rowcount, row factories et erreurs.
- Vérifier les transactions multi-écritures avec panne simulée et reconnexion.
- Inventorier les requêtes SQL de tous les modules cognitifs et les classer par compatibilité, pas uniquement tester SELECT 1.
- Comparer schema, contraintes, index, triggers, row counts et empreintes de contenu avant/après import.
- Tests d'intégration sur une base Turso de staging isolée, jamais sur chappie-db de production.
- Tester une session Chat puis Live et inversement, redémarrage, backup, restauration et rollback avant toute bascule.
- Ne jamais activer le backend distant si un contrôle est inconnu ou en échec.

## Données actuelles connues

Les dernières inspections de récupération indiquent 41 tables et 0 ligne dans le backup Render, contre 13 tables et 5 lignes dans le backup Turso. Ces artefacts prouvent la capacité de restauration, pas une mémoire vécue sauvegardée. La migration ne peut donc pas être considérée comme une simple bascule technique.

## Tests V50.41

Les tests utilisent un faux pilote natif en mémoire et SQLite temporaire. Ils vérifient les contrats de ligne/curseur, le context manager, le comportement fermé après close, l'absence de backup natif, le refus d'activation Turso et les bloqueurs de démarrage/sauvegarde du serveur.

## Exclusions de sécurité

- Aucun appel distant à Turso.
- Aucun accès à Render.
- Aucune lecture ou modification de secret.
- Aucune migration, écriture, création de table ou modification de données distantes.
- Aucun merge, reset ou déploiement.
