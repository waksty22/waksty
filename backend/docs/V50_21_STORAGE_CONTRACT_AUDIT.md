# V50.21 — Audit du contrat de stockage

**Statut : audit statique uniquement — aucune bascule, migration ou écriture distante.**

## Objectif

Garantir que toutes les conversations, souvenirs autobiographiques, connaissances apprises, observations et états cognitifs utilisent une seule source de persistance durable, partagée entre le chat écrit et Gemini Live. La priorité est la conservation des nouvelles expériences après redémarrage ou redéploiement de Render.

## Constat confirmé sur `main`

Révision examinée : branche `main` au moment de l'audit V50.21.

### 1. Le serveur utilise toujours SQLite directement

Dans `backend/server.py` :

- `db_connection()` appelle directement `sqlite3.connect(DB_PATH)`.
- Le `row_factory` est défini sur `sqlite3.Row`.
- Les PRAGMA `foreign_keys` et `busy_timeout` sont appliqués à chaque connexion.
- `init_db()` exécute `PRAGMA journal_mode=WAL`, puis un grand `executescript()` et initialise les modules cognitifs.
- La fabrique `storage.connection_factory.open_storage_connection()` n'est pas utilisée par `db_connection()`.

Conséquence : la configuration `CHAPPIE_STORAGE_BACKEND=turso` ne suffit pas à déplacer le stockage applicatif vers Turso.

### 2. Deux configurations SQLite doivent être unifiées

Le serveur définit `DB_PATH` à partir de `CHAPPIE_DATA_DIR` (défaut `./chappie_data`).

La fabrique définit séparément son chemin via `CHAPPIE_SQLITE_PATH` (défaut `./chappie_data/chappie_v16.sqlite3`).

Avant tout branchement, il faut une seule résolution de chemin, avec un comportement explicite si les deux variables sont présentes. L'objectif est d'éviter qu'un changement de fabrique ouvre une base SQLite vide différente de celle actuellement utilisée.

### 3. L'adaptateur libSQL couvre un sous-ensemble DB-API

`backend/storage/libsql_adapter.py` fournit notamment :

- `execute`, `executemany`, `executescript`
- curseurs, accès aux colonnes par nom et index
- `lastrowid`, `rowcount`, `fetchone`, `fetchall`, `fetchmany`
- `commit`, `rollback`, `close`
- gestionnaire de contexte avec commit/rollback

Les tests existants couvrent ces comportements sur le pilote libSQL local en mémoire. Ils ne prouvent pas à eux seuls le bon fonctionnement de toutes les routes de production ni de la connexion distante Turso.

### 4. La sauvegarde locale actuelle est spécifique à SQLite

La route de sauvegarde SQLite dans `backend/server.py` utilise `source.backup(destination)`. Cette méthode n'est pas exposée par `LibSQLConnectionAdapter`.

Un export logique compatible libSQL existe déjà dans `backend/storage/logical_backup.py`. Il utilise un instantané de lecture avec SAVEPOINT, exporte le schéma et les lignes, vérifie le fichier par restauration dans une base SQLite temporaire et propose également un format chiffré. Les tests du pilote libSQL local couvrent déjà cet export.

Il faut donc choisir explicitement le mécanisme de sauvegarde selon le backend, ou fournir une abstraction de sauvegarde commune. Il ne faut pas appeler l'API SQLite `backup()` sur une connexion Turso.

### 5. L'initialisation du schéma doit être séparée du choix du moteur

L'initialisation actuelle applique WAL et utilise `executescript()`. Le WAL est une configuration SQLite locale et ne doit pas être exécuté aveuglément sur Turso.

Les initialisateurs des modules cognitifs ont déjà été testés ensemble sur une connexion libSQL locale. L'initialisation complète du schéma applicatif, des index et des migrations doit néanmoins être vérifiée dans un parcours de démarrage dédié, sans écrire dans la base distante de production.

### 6. Les diagnostics de chemin sont SQLite-spécifiques

`storage.path_diagnostics` inspecte `PRAGMA database_list`, le fichier de base, les fichiers WAL/SHM, le montage et `integrity_check`. Ces informations ne sont pas pertinentes pour une base distante Turso.

Le diagnostic devra identifier le backend actif et fournir des indicateurs adaptés à chacun, sans exposer les secrets ni le contenu des souvenirs.

## Tests déjà présents à préserver

Les tests V50 existants couvrent notamment :

- l'adaptateur libSQL et son contrat DB-API ;
- l'ouverture SQLite par défaut et les validations de configuration Turso ;
- l'initialisation conjointe de 13 systèmes cognitifs sur une base libSQL locale ;
- des parcours transversaux mémoire épisodique, mémoire autobiographique, spatialisation et modèle du monde ;
- des parcours vocabulaire, perception, apprentissage d'objets, imitation ;
- des parcours raisonnement, décisions, préférences, compétences, causalité et fusion multimodale ;
- l'export logique et la vérification locale d'une sauvegarde libSQL.

Ces tests utilisent des bases locales temporaires. Ils ne constituent pas une validation de la persistance distante après redémarrage Render.

## Contrat cible à valider avant activation de Turso

1. **Une seule fabrique** pour toutes les connexions du serveur, sans chemins SQLite concurrents.
2. **Sélection explicite** du backend ; SQLite reste le défaut tant que le cutover n'est pas approuvé.
3. **Initialisation différenciée** : WAL uniquement pour SQLite local ; initialisation distante Turso contrôlée et idempotente.
4. **Transactions documentées** : commit/rollback, erreurs, gestionnaire de contexte et concurrence testés sur les deux moteurs.
5. **Sauvegardes adaptées** : SQLite Backup API pour SQLite ; export logique vérifié et chiffré pour libSQL/Turso.
6. **Diagnostics adaptés** au backend actif, sans afficher URL complète, jeton ou contenu privé.
7. **Parcours de mémoire partagé** : un souvenir écrit en chat doit être immédiatement relisible dans le chat et dans Gemini Live, et inversement.
8. **Migration séparée** du code de connexion : inventaire source/cible, copie de données, validation des nombres de lignes, contraintes, index et clés étrangères.
9. **Test de persistance** : écrire un souvenir de test, fermer la connexion, rouvrir depuis une nouvelle instance, puis vérifier sa présence.
10. **Test de reprise** : restaurer une sauvegarde chiffrée dans une base isolée et comparer les inventaires avant toute bascule réelle.

## Ordre de réalisation proposé

- **V50.22** : unifier la configuration et le cycle de vie des connexions, en conservant SQLite par défaut.
- **V50.23** : isoler l'initialisation SQLite/Turso et ajouter des tests de démarrage sur libSQL local.
- **V50.24** : adapter sauvegardes et diagnostics au backend actif ; conserver une voie de restauration testée.
- **V50.25** : préparer la migration des données avec inventaires, compteurs par table et contrôles d'intégrité ; dry-run par défaut.
- **V50.26** : tests bout-en-bout chat écrit + Gemini Live + fermeture/réouverture sur backend isolé.
- **Cutover ultérieur** : uniquement après sauvegarde vérifiée, revue des résultats, approbation explicite et plan de retour arrière.

## Garde-fous

- Aucun accès en écriture à Turso dans cet audit.
- Aucun reset, DROP, remplacement ou écrasement de données.
- Aucun changement de secret ou de jeton.
- Aucun déploiement Render et aucune bascule automatique.
- Ne jamais annoncer la mémoire comme durable avant le test réel de fermeture/réouverture et la validation de restauration.
