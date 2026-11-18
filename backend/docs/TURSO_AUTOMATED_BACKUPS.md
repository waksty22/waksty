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
