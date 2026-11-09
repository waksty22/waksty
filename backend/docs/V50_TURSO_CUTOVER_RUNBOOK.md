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


## Complément V50.54 — Audit structurel détaillé (lecture seule)

L'audit détaillé expose, pour chaque table présente des deux côtés :

- les colonnes absentes ou supplémentaires ;
- les différences de type, nullabilité, valeur par défaut et position de clé primaire ;
- les clés étrangères, y compris les colonnes liées et les actions ON UPDATE / ON DELETE ;
- les index, leur unicité, leur origine, leur caractère partiel et leurs colonnes ;
- les différences de définition SQL des tables, afin de repérer notamment les contraintes CHECK, UNIQUE et options de table ;
- les différences de définition des vues et déclencheurs.

Chaque écart est classé comme bloquant, important ou informatif. Les définitions SQL renvoyées sont des métadonnées de schéma ; aucun contenu de ligne métier n'est extrait. Les valeurs affichées dans le rapport sont bornées côté interface.

**Important :** « schéma prêt » ne signifie jamais « migration prête ». La migration des données reste explicitement « non évaluée » par cet audit. Les volumes de lignes et l'absence de violations de clés étrangères ne prouvent pas l'égalité des données ; une phase distincte devra vérifier les identifiants, les relations et des empreintes déterministes avant toute migration. Aucun SQL de modification (CREATE, ALTER, DROP, INSERT, UPDATE ou DELETE) n'est exécuté par cet audit.

L'endpoint existant `GET /api/storage/schema-audit` est étendu sans changement de mode : authentification obligatoire, connexions d'inspection fermées en fin de requête, aucune bascule de backend, aucune écriture SQLite/Turso. SQLite reste le stockage de production tant qu'une procédure de migration séparée n'a pas été approuvée et validée.


## Complément V50.55 — Migrateur contrôlé SQLite → Turso

La branche V50.55 ajoute un premier parcours complet, mais volontairement non automatique :

- `GET /api/storage/migration/preview` : audit de compatibilité et volumes uniquement ; aucun contenu de ligne n'est renvoyé.
- `GET /api/storage/migration/backup` : archive ZIP contenant deux sauvegardes logiques chiffrées AES-256-GCM, une de SQLite et une de Turso, chacune accompagnée de son SHA-256. Les deux restaurations temporaires sont vérifiées avant de fournir l'archive.
- `POST /api/storage/migration/apply` : copie idempotente des lignes, uniquement si `CHAPPIE_ALLOW_TURSO_MIGRATION=1`, si SQLite est encore le backend actif, si le corps confirme exactement `MIGRER VERS TURSO` et si l'utilisateur confirme avoir téléchargé l'archive de sauvegarde.

Le migrateur :
- applique dans la même transaction cible les changements de schéma approuvés et la copie des lignes ;
- conserve les identifiants et les lignes déjà présentes dans Turso ;
- compare chaque ligne relue et calcule des empreintes SHA-256 déterministes par table ;
- interrompt et annule la transaction en cas de collision de clé, contrainte unique, dépendance circulaire, différence de définition SQL ou violation de clé étrangère ;
- ne retourne jamais le contenu des souvenirs ou conversations.

**Limite assumée :** les différences de définition SQL des tables partagées sont bloquantes jusqu'à leur revue. Le migrateur ne tente pas de deviner si une différence de contrainte ou d'option est sans danger.

### Sélection du backend après migration

- SQLite reste le choix par défaut.
- `db_connection()` passe désormais par la fabrique de stockage ; la configuration SQLite conserve le chemin effectif `DB_PATH`.
- Si Turso est sélectionné, le démarrage est refusé tant que `CHAPPIE_TURSO_CUTOVER_READY=1` n'a pas été défini explicitement.
- Les endpoints de diagnostic du fichier SQLite et de sauvegarde physique SQLite refusent de présenter une connexion Turso comme un fichier local.
- L'audit SQLite/Turso continue d'ouvrir explicitement le fichier SQLite local en lecture seule.

**Important :** la PR ne modifie pas les variables Render, ne lance pas le transfert, ne bascule pas le backend et ne déploie pas l'application. Après migration, le rapport doit être contrôlé avant toute modification manuelle des variables Render.
