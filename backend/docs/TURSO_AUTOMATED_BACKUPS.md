# Chappie — sauvegardes automatiques Turso

## Fonctionnement

Le workflow GitHub Actions `.github/workflows/chappie-turso-backup.yml` lance une sauvegarde quotidienne à 03:17 UTC. Une exécution manuelle est également disponible depuis l'onglet Actions.

Le script `backend/scripts/backup_turso.py` utilise Hrana HTTP v2 (flux transactionnel sérialisé), comme le chemin de sauvegarde de migration ; il n'utilise pas l'ancien transport WebSocket libsql. Il :

1. ouvre une connexion Turso en lecture seule sur les données ;
2. exporte le schéma et les lignes dans un instantané logique cohérent ;
3. chiffre l'archive avec AES-256-GCM et PBKDF2-HMAC-SHA256 (600 000 itérations) ;
4. vérifie le checksum, le déchiffrement et la restauration logique dans une base SQLite temporaire ;
5. crée un ZIP contenant uniquement le fichier chiffré et son sidecar SHA-256 ;
6. extrait et revérifie l'archive finale avant de la remettre à GitHub Actions.

Aucun contenu en clair n'est envoyé dans l'artefact ou les journaux. Les journaux ne contiennent que des compteurs et des métadonnées de sauvegarde.

## Secrets GitHub requis

Dans le dépôt GitHub : **Settings → Secrets and variables → Actions**, ajouter les trois secrets suivants en reprenant les valeurs déjà configurées dans Render, sans les placer dans le dépôt :

- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`
- `BACKUP_ENCRYPTION_KEY`

La clé de chiffrement doit être conservée dans un gestionnaire de mots de passe sécurisé. Sans cette clé, les sauvegardes ne pourront pas être déchiffrées.

## Rétention

Les artefacts GitHub Actions sont conservés pendant 90 jours. Cette solution fournit un historique glissant ; elle ne remplace pas une seconde copie indépendante à long terme (par exemple un stockage objet séparé).

## Contrôle

Après fusion sur `main` et ajout des secrets :

1. lancer manuellement **Chappie Turso encrypted backup** ;
2. vérifier que l'exécution se termine avec succès ;
3. télécharger l'artefact ZIP et le conserver hors du dépôt ;
4. contrôler les compteurs, la taille et le SHA-256 affichés dans les journaux ;
5. réaliser périodiquement un exercice de restauration sur une base de test isolée.

Le workflow ne modifie jamais les tables Turso : il effectue uniquement des lectures et produit un artefact chiffré.



## Limites de restauration vérifiées

La sauvegarde quotidienne et la restauration distante sont deux contrôles distincts :

- Le workflow quotidien chiffre l'instantané, vérifie son checksum et son authenticité, puis reconstruit les données dans une base SQLite temporaire. Cela valide l'archive et sa reconstruction locale, pas un import dans Turso.
- Le workflow `.github/workflows/chappie-full-schema-isolated-e2e.yml` exécute un test séparé sur une base Turso de test explicitement autorisée. Il crée son propre jeu de données de test et son propre instantané chiffré ; il vérifie le refus d'une cible déjà remplie, la restauration dans la cible de test vide, les lignes, les clés étrangères, la reconnexion distante et l'adaptateur libSQL.
- Ce test E2E **ne restaure pas l'artefact quotidien réel** et n'écrit jamais dans la base configurée pour la production. L'URL de production ne sert qu'à vérifier que la cible de test est différente.

### Ce qui reste à faire avant de parler de restauration opérationnelle

Il n'existe pas encore de procédure/outil général validé pour restaurer l'artefact quotidien réel vers une base Turso de récupération. Il faudra :
1. télécharger un artefact quotidien précis et vérifier son checksum ;
2. le restaurer dans une base Turso de récupération distincte ;
3. vérifier le schéma, toutes les lignes, les contraintes et la lecture via les chemins applicatifs ;
4. documenter le rapport et les limites avant toute décision de restauration de production.

**Ne jamais utiliser `chappie-db` comme cible d'essai.** Une restauration de production reste une opération séparée, avec validation explicite de la cible et autorisation de l'opérateur.

### Dernière sauvegarde observée

Le 24 novembre 2026, l'exécution observée du workflow de sauvegarde a terminé avec succès : 42 tables et 108 lignes ont été exportées dans une archive chiffrée de 57 093 octets. La vérification après empaquetage a réussi et l'artefact était annoncé comme conservé jusqu'au 22 février 2027. Cette réussite ne change pas les limites de restauration décrites ci-dessus.


## Procédure opérateur de restauration vers une base de récupération

Cette procédure est un **exercice de reprise**, pas une autorisation de restaurer la production. Elle ne doit être exécutée qu'après préparation d'une base Turso de récupération indépendante.

### 1. Préparer une cible distincte

- Créer une nouvelle base Turso dédiée à la récupération, vide et indépendante.
- Relever son hostname exact depuis Turso ; ne pas le déduire du nom de la base.
- Vérifier que ce hostname est différent de celui de production `chappie-db` et de celui de la base de test E2E isolée.
- Préparer un jeton d'accès limité à cette base de récupération.
- Ne jamais réutiliser le jeton de production comme identifiant de connexion de destination.
- Conserver l'URL de production uniquement comme valeur de comparaison d'identité, sans ouvrir de transaction d'écriture dessus.

**Arrêt immédiat** si la cible n'est pas vide, si son hostname est ambigu, si elle correspond à la production ou si les secrets de récupération ne sont pas dédiés.

### 2. Sélectionner et contrôler l'artefact

- Choisir un run GitHub Actions précis et noter son identifiant.
- Télécharger l'artefact `chappie-turso-backup-<run_id>` depuis ce run, pas depuis un artefact au nom similaire.
- Vérifier que le ZIP contient exactement le fichier chiffré et son sidecar `.sha256`.
- Vérifier le checksum du fichier chiffré, puis son authentification AES-GCM et son déchiffrement avec `BACKUP_ENCRYPTION_KEY`.
- Exécuter la vérification logique locale avant toute connexion à la base de récupération.
- Ne jamais afficher ni transmettre la clé de chiffrement dans les journaux ou dans une demande d'assistance.

### 3. Restaurer uniquement dans la cible de récupération

Le point d'entrée de restauration est `restore_encrypted_logical_backup` dans `backend/storage/logical_backup.py`, avec une transaction ouverte via le transport Hrana et l'adaptateur `HranaRestoreConnection`.

Les trois identités doivent être renseignées explicitement :
- `target_identity` : hostname réellement obtenu de la connexion de récupération ;
- `expected_target_identity` : hostname exact confirmé par l'opérateur avant l'opération ;
- `production_identity` : hostname de production utilisé uniquement pour refuser toute égalité avec la cible.

Les deux premières identités doivent être strictement égales ; la cible doit être différente de la production. La fonction refuse aussi toute base cible contenant déjà des objets applicatifs. L'opération doit rester dans une seule transaction ; en cas d'erreur, effectuer un rollback et ne pas recommencer sur une cible dont l'état n'a pas été inspecté.

### 4. Vérifier après restauration

Conserver un rapport horodaté comprenant au minimum :
- identifiant du run et nom de l'artefact ;
- SHA-256 du fichier chiffré ;
- hostname de la base de récupération (jamais de jeton) ;
- résultat de l'authentification et de la vérification logique ;
- nombre de tables et nombre total de lignes restaurées ;
- vérification des clés étrangères ;
- résultats des lectures applicatives en lecture seule sur les tables essentielles ;
- résultat du rollback si une étape échoue.

Comparer les compteurs restaurés au résumé de l'archive. Contrôler les contraintes et les lectures applicatives avec les outils de diagnostic en mode lecture seule. Une restauration réussie techniquement ne signifie pas que l'application doit être basculée vers cette base.

### 5. Conditions avant toute automatisation

Aucun workflow automatisé de restauration distante de l'artefact quotidien n'est encore déclaré opérationnel. Avant d'en créer un, il faudra disposer de secrets dédiés à la base de récupération, d'un hostname attendu obligatoire, d'une confirmation explicite de l'opérateur, d'un précontrôle de base vide et d'une protection empêchant toute destination de production. Le workflow de test E2E existant ne remplace pas cet exercice réel.

**Interdictions permanentes pour les exercices :** ne pas utiliser `chappie-db` comme cible ; ne pas lancer de reset ; ne pas restaurer dans la base de test partagée sans autorisation spécifique ; ne pas basculer l'application vers la base de récupération automatiquement.
