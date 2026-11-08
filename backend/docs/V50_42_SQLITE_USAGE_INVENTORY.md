# V50.42 — Inventaire statique SQL et dépendances SQLite

## Objectif

Recenser automatiquement les usages SQL et les appels DB-API susceptibles de différer entre sqlite3 local et libSQL/Turso. L'audit est statique : aucune base n'est ouverte, aucun secret n'est lu et aucune donnée n'est modifiée.

## Livrables

- `scripts/audit_sqlite_usage.py` : scanner AST Python, rapport JSON déterministe.
- Tests synthétiques couvrant `sqlite3.connect`, `executescript`, `Connection.backup`, PRAGMA, `lastrowid` et AUTOINCREMENT.
- Tests qui confirment la présence des points d'attention dans `server.py`.

## Catégories recensées

- API natives SQLite : connect, executescript, backup, row_factory, métadonnées de curseur, configuration de connexion, fonctions/collations personnalisées, commit/rollback.
- SQL : PRAGMA, INSERT OR IGNORE/REPLACE, ON CONFLICT, RETURNING, fonctions JSON/date, fonctions spécifiques SQLite, tables virtuelles/FTS, triggers, index, clés étrangères, CHECK, AUTOINCREMENT.
- Chaque occurrence est associée à son chemin et numéro de ligne. Le rapport ne contient pas les valeurs de variables d'environnement ni les secrets.

## Interprétation

Le scanner signale des candidats à examiner, pas des incompatibilités certaines. Par exemple, une requête PRAGMA peut être locale-only ou avoir un équivalent distant ; ON CONFLICT peut être supporté mais doit être vérifié selon le pilote et la version. Une validation réelle nécessite ensuite des tests d'intégration sur une base Turso de staging isolée.

## Ordre de validation recommandé

1. Résoudre les appels natifs SQLite dans les chemins de démarrage, mémoire, sauvegarde et diagnostic.
2. Vérifier les SQL DDL/DML avec contraintes, index, triggers et fonctions.
3. Tester curseurs, rowcount/lastrowid, executemany et transactions.
4. Tester interruption réseau, reprise, idempotence, restauration et cohérence Chat/Live.
5. Seulement après succès, proposer un plan de staging distant distinct. La base `chappie-db` de production reste exclue.

## Limites

Un scan statique peut manquer le SQL construit dynamiquement ou les appels indirects. Il ne certifie ni le dialecte complet, ni la sémantique des transactions, ni la durabilité d'une base distante.
