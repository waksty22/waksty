# Chappie V50 — Procédure de migration SQLite vers Turso

## État vérifié dans le dépôt (branche main au 8 novembre 2026)

- Le stockage réellement utilisé par l'application reste SQLite : `backend/server.py` définit `db_connection()` avec `sqlite3.connect(DB_PATH)`.
- `backend/storage/connection_factory.py` sait ouvrir SQLite ou Turso selon `CHAPPIE_STORAGE_BACKEND`, mais son en-tête précise qu'il n'est pas encore raccordé à `server.db_connection()`.
- `backend/storage/libsql_adapter.py` fournit une compatibilité DB-API partielle et des tests isolés ; cela ne prouve pas encore la compatibilité de tout le backend.
- `backend/storage/schema_migration.py` prépare/applique des changements de schéma. Il ne copie aucune ligne métier.
- `backend/storage/logical_backup.py` sait exporter une base Turso en archive logique chiffrée et vérifier l'intégrité de la restauration temporaire.
- Les diagnostics de schéma/inventaire sont conçus pour exposer des métadonnées et des volumes, pas le contenu des souvenirs.

**Conclusion :** Turso ne doit pas encore être considéré comme le stockage mémoire actif de Chappie. La présence d'une base Turso et d'une sauvegarde ne signifie pas que les conversations, souvenirs, apprentissages et événements y sont synchronisés.

## Règles non négociables

1. Aucun basculement automatique ou implicite du backend.
2. Aucun reset, `DROP`, remplacement de base ou écrasement de tables pendant la préparation.
3. Ne jamais copier les données tant qu'une sauvegarde vérifiée de la source et une sauvegarde vérifiée de la cible ne sont pas disponibles.
4. Ne jamais considérer des nombres de lignes identiques comme une preuve suffisante : vérifier aussi les identifiants, les relations, les contraintes et une empreinte déterministe des données.
5. Pas de double écriture SQLite/Turso improvisée : elle pourrait créer des divergences silencieuses.
6. Le retour arrière doit être préparé et testé avant le cutover.
7. Les secrets restent dans les variables d'environnement Render ; ne jamais les placer dans Git, les journaux ou les réponses d'API.

## Phase A — Audit en lecture seule

- Relever le chemin réel de `DB_PATH`, le volume persistant Render et les variables de configuration actives sans afficher leurs valeurs secrètes.
- Obtenir un inventaire SQLite et Turso : tables, colonnes, types, valeurs par défaut, clés primaires, index, contraintes UNIQUE/CHECK, clés étrangères, triggers et vues.
- Relever les nombres de lignes par table et les violations de clés étrangères. Ne pas extraire le texte des souvenirs dans les rapports.
- Comparer les schémas et classer chaque écart : table absente, colonne absente, contrainte différente, index manquant, objet non pris en charge.
- Arrêter l'audit de migration si une table source n'est pas comprise ou si une différence ne peut pas être expliquée.

Livrable : rapport daté, sans contenu personnel, avec écarts et décision explicite « prêt / bloqué ».

## Complément V50.20 — Diagnostic du fichier SQLite réellement ouvert

L'endpoint authentifié `GET /api/storage/path-diagnostics` réutilise `db_connection()`, donc inspecte la même base SQLite que l'application. Il expose uniquement les chemins de configuration et du fichier ouvert, les tailles des fichiers SQLite/WAL/SHM, le mode journal, le point de montage Linux le plus spécifique et le résultat de `PRAGMA integrity_check`. Il ne lit ni ne retourne les lignes métier et n'ouvre aucune base alternative.

Le point de montage observé est une information système, pas une preuve contractuelle de persistance Render. Il faut le comparer au chemin de montage du disque configuré dans le tableau de bord Render. L'absence de `CHAPPIE_DATA_DIR` signifie que le code utilise son chemin par défaut ; elle ne permet pas, à elle seule, de conclure que le disque est absent.

**Sécurité :** cet endpoint reste protégé par l'authentification existante. Il n'effectue aucune écriture SQLite/Turso, aucun checkpoint WAL et aucune création de fichier de base supplémentaire.

## Phase B — Préparation de la cible

- Produire une sauvegarde SQLite cohérente et vérifiée depuis le volume actif.
- Produire une sauvegarde logique Turso chiffrée et vérifiée avant toute modification de la cible.
- Corriger uniquement les écarts de schéma approuvés, d'abord sur une cible de test ; préserver les données déjà présentes dans Turso.
- Refaire l'audit jusqu'à obtenir une compatibilité de schéma complète, y compris les index et contraintes.
- Tester les fonctions réellement utilisées par le backend avec le pilote libsql : transactions, curseurs, `lastrowid`, `rowcount`, paramètres, context managers, PRAGMA et erreurs.

Aucune copie de données ne fait partie de la simple préparation de schéma.

## Phase C — Migration des données (à développer et tester séparément)

Le migrateur de données devra être idempotent et traçable :

- Établir un instantané cohérent de la source ; interrompre ou mettre en pause les écritures pendant la copie finale.
- Copier les tables dans un ordre respectant les dépendances, en conservant les clés primaires et les horodatages.
- Préserver les valeurs NULL, les chaînes Unicode, les blobs, les valeurs numériques et les identifiants de propriétaire.
- Ne jamais fusionner silencieusement deux lignes ayant le même identifiant mais un contenu différent.
- Utiliser des lots bornés et des transactions ; enregistrer un checkpoint de progression sans exposer les contenus.
- Comparer, table par table, le nombre de lignes et une empreinte canonique déterministe calculée sur les lignes ordonnées par clé primaire.
- Vérifier les clés étrangères, l'intégrité de la cible et des échantillons de lecture par identifiant.
- Si Turso contient déjà des lignes, les préserver et signaler explicitement les collisions ; ne pas remplacer la cible par une copie brute.

Un échec de vérification bloque la migration et impose de conserver SQLite comme source active.

## Phase D — Validation applicative avant bascule

Sur un environnement de test isolé, exécuter au minimum :

- démarrage et initialisation sans création accidentelle d'une base vide ;
- lecture et écriture d'une conversation ;
- rappel des souvenirs et des événements autobiographiques ;
- apprentissage d'un mot/objet et persistance de la preuve ;
- état émotionnel, compétences, objectifs et mémoire spatiale ;
- même souvenir consultable depuis le chat écrit et Gemini Live ;
- redémarrage complet du service puis vérification de la persistance ;
- sauvegarde chiffrée, restauration dans une base temporaire et vérification des empreintes ;
- test du retour arrière vers SQLite.

Les tests doivent vérifier les données après fermeture/réouverture de connexion, pas seulement dans la connexion ayant écrit.

## Phase E — Cutover contrôlé (autorisation distincte obligatoire)

Seulement après validation des phases précédentes :

1. prendre une dernière sauvegarde vérifiée de SQLite et de Turso ;
2. suspendre les écritures et faire la synchronisation finale ;
3. vérifier une dernière fois les empreintes ;
4. changer explicitement la configuration de stockage ;
5. démarrer une seule instance et effectuer des tests de lecture/écriture contrôlés ;
6. surveiller erreurs, latence, écritures et cohérence ;
7. garder SQLite intacte et disponible pour retour arrière jusqu'à validation formelle.

Le changement de configuration Render et toute écriture sur la base réelle nécessitent une autorisation explicite distincte. Cette procédure ne les autorise pas à elle seule.

## Critères de retour arrière

Revenir à SQLite si le démarrage échoue, si une table manque, si une écriture n'est pas relue, si les empreintes divergent, si les appels Live et chat ne partagent pas la même mémoire, ou si les erreurs/latences deviennent anormales. Après le cutover, ne pas recopier automatiquement Turso vers SQLite : sauvegarder et analyser les écritures intervenues depuis le basculement avant toute restauration.

## Statut

- [x] Sauvegarde logique Turso chiffrée avec vérification locale.
- [x] Outil de comparaison de schéma et de plan de migration non destructif présent.
- [x] Fabrique de connexions et adaptateur libsql présents, isolés du stockage actif.
- [x] Diagnostic en lecture seule du chemin SQLite réellement ouvert (V50.20, code/tests prêts ; exécution sur Render à faire après déploiement approuvé).
- [ ] Audit réel des deux bases et rapport de compatibilité.
- [ ] Compatibilité complète du backend avec libsql.
- [ ] Migrateur de données idempotent avec contrôle d'empreintes.
- [ ] Répétition de migration/restauration sur environnement isolé.
- [ ] Cutover et test de retour arrière autorisés séparément.
