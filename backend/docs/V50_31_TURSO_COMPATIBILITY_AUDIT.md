# V50.31 — Audit de compatibilité Turso avant raccordement

**Statut : audit statique et tests de garde-fou. Aucun accès distant, aucune écriture, aucune migration et aucun déploiement.**

## Décision

Turso ne peut pas encore devenir le stockage métier de Chappie. La fabrique générique sait ouvrir une connexion libSQL, mais le serveur reste volontairement verrouillé sur SQLite via `open_sqlite_application_connection()`. Cette séparation doit rester en place.

## Écarts techniques confirmés

1. **Contrat de connexion incomplet.** L'application utilise le contrat `sqlite3.Connection` et des comportements `sqlite3.Row`. L'adaptateur libSQL reproduit un sous-ensemble DB-API, pas toute l'API SQLite.
2. **Initialisation non portable telle quelle.** `init_db()` applique `PRAGMA journal_mode=WAL` et exécute un script SQL massif. WAL est propre au fichier SQLite local et ne doit pas être envoyé à Turso.
3. **Sauvegarde différente selon le moteur.** Le chemin SQLite utilise l'API `Connection.backup()`; l'adaptateur libSQL ne l'expose pas. L'export logique constitue la voie candidate pour Turso, mais doit être validé sur une vraie connexion distante.
4. **Diagnostics différents.** Les chemins de fichiers, WAL/SHM, montage et `integrity_check` décrivent SQLite local, pas la disponibilité ni la durabilité d'une base distante.
5. **Schéma distant incomplet.** L'exercice de restauration Turso observé contient 13 tables et 5 lignes, contre 41 tables et 0 ligne dans l'artefact Render. Cela ne permet pas de basculer l'application.
6. **Compatibilité SQL non démontrée de bout en bout.** Les tests de l'adaptateur local ne prouvent pas que chaque requête, transaction, index, contrainte, migration et route fonctionne sur le service Turso réel.

## Garde-fous de code

- Le backend par défaut reste SQLite.
- Le serveur utilise le helper SQLite-only qui refuse explicitement `backend="turso"`.
- La présence de variables Turso ne sélectionne pas automatiquement Turso.
- Aucune sonde distante n'est exécutée dans cette étape.
- Ne jamais créer ou modifier des tables distantes pour « tester » la connexion.
- Ne jamais considérer un simple `SELECT 1` comme une preuve de compatibilité métier.

## Conditions minimales avant V50.32 / migration

- Inventaire exhaustif des tables, colonnes, index, vues, triggers et clés étrangères côté source et cible.
- Plan de migration idempotent, versionné et reprenable, sans DROP ni remplacement silencieux.
- Tests des requêtes métier réelles et de leurs paramètres sur un environnement Turso isolé.
- Tests des transactions, erreurs de contraintes, curseurs, `lastrowid`, `rowcount`, BLOB, dates et valeurs NULL.
- Initialisation distante distincte de l'initialisation SQLite, sans PRAGMA local non supporté.
- Export logique chiffré, restauration isolée, comparaison des empreintes de contenu.
- Test écrit en chat puis lu en chat et Gemini Live, et inversement, après fermeture/réouverture.
- Plan de retour arrière vérifié et sauvegarde complète non vide.

## Tests ajoutés dans cette version

Les tests vérifient statiquement que le serveur continue d'utiliser le helper SQLite-only, que la sélection Turso échoue fermée dans ce helper, et que la sonde de compatibilité distante reste une sonde SELECT/PRAGMA en lecture seule. Ils ne prétendent pas valider un vrai déploiement Turso.

## Actions expressément exclues

Aucun secret lu ou affiché, aucune variable Render modifiée, aucune écriture Turso, aucun changement de base, aucune migration, aucun reset, aucun merge et aucun déploiement.
