# V36.3 — Plan de compatibilité Turso

## État initial

La sonde V36.1 a confirmé que l'instance Turso répond aux requêtes en lecture, mais que le pilote `libsql` n'est pas une instance `sqlite3.Connection` et ne prend pas en charge l'affectation de `sqlite3.Row` comme fabrique de lignes.

Le backend de production reste actuellement SQLite local : `backend/server.py` crée ses connexions avec `sqlite3.connect(DB_PATH)`. La sonde Turso ne bascule donc pas le stockage.

## Audit du backend

Les modules mémoire, monde, apprentissage et cognition utilisent un contrat SQLite assez large :
- `execute`, `executemany`, `executescript` ;
- `fetchone`, `fetchall`, itération sur les curseurs ;
- accès aux lignes par index et par nom de colonne ;
- `lastrowid`, `rowcount`, `commit`, `rollback` ;
- context manager des connexions ;
- détection explicite de `sqlite3.Connection`, `sqlite3.Row` et `sqlite3.OperationalError` dans certains modules.

Une simple adaptation de `row_factory` ne suffirait donc pas.

## Plan de réalisation

1. Définir un contrat de stockage commun et un adaptateur libsql sans modifier le chemin SQLite existant.
2. Adapter les curseurs et lignes pour préserver les accès par index et par nom, sans prétendre être des objets sqlite3.
3. Inventorier et remplacer progressivement les contrôles de type SQLite par des contrats explicites, en conservant la gestion des erreurs.
4. Vérifier les transactions, les clés générées, les migrations de schéma, les clés étrangères et les requêtes réellement utilisées.
5. Ajouter des tests unitaires avec doubles de pilote, puis des tests d'intégration Turso isolés.
6. Garder SQLite comme stockage actif tant que toute la suite n'est pas validée.
7. Prévoir une activation explicite et réversible de Turso, sans copie destructive ni réinitialisation des données.

## Garde-fous

- Aucun changement de base ou migration distante pendant la phase d'adaptation.
- Aucun effacement ou reset de mémoire.
- La sonde de compatibilité reste strictement en lecture seule.
- Pas de bascule automatique au démarrage.
- Toute future migration de données devra être séparée, sauvegardée et vérifiée avant activation.

## Premier constat technique

Le premier chantier n'est pas de forcer les deux indicateurs de la sonde à passer au vert : il faut rendre explicite le contrat de connexion et de ligne attendu par les modules. La compatibilité devra être démontrée par les tests fonctionnels, pas seulement par des tests de forme.
