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


## Limite importante : restauration Turso

**L'outil actuel ne restaure pas une sauvegarde vers Turso.** La vérification réalisée pendant la sauvegarde déchiffre l'artefact et reconstruit son contenu dans une base SQLite temporaire. Elle valide le format, le checksum, l'authenticité AES-GCM, l'intégrité SQLite et les nombres de lignes ; elle ne valide ni l'import distant, ni les contraintes et comportements propres à Turso.

Le module `backend/storage/backup.py` ne restaure que des fichiers SQLite locaux. Il ne doit jamais être présenté comme un outil de restauration Turso.

En conséquence, une sauvegarde marquée `verified` signifie **export local vérifié**, pas **restauration Turso éprouvée**. Ne pas lancer de commandes SQL d'import sur la base de production pour tester une restauration.

### Procédure obligatoire avant une restauration distante

1. Créer ou désigner une base Turso de test distincte de `chappie-db`, avec des identifiants dédiés et les droits minimaux nécessaires.
2. Vérifier l'identité de la base cible par son URL/nom non secret ; refuser explicitement toute cible correspondant à la base de production.
3. Télécharger l'artefact ZIP depuis GitHub Actions et vérifier qu'il contient exactement le fichier chiffré et son checksum.
4. Déchiffrer avec `BACKUP_ENCRYPTION_KEY` sans écrire de données en clair dans les journaux ou dans un artefact partagé.
5. Restaurer uniquement dans la base de test, en respectant l'ordre de création des tables, les index, vues et triggers, les contraintes de clés étrangères et les limites de taille/transaction de Turso.
6. Comparer les tables, colonnes, objets SQL et nombres de lignes restaurés à l'instantané ; exécuter les contrôles d'intégrité applicables.
7. Tester la lecture avec les chemins applicatifs et confirmer que les données sont cohérentes après fermeture/réouverture de connexion.
8. Conserver le rapport de test sans données personnelles, puis supprimer la base de test uniquement après validation et approbation explicite.

**État actuel :** les étapes 1 à 8 ne sont pas automatisées. Aucun script de restauration distante n'est livré. Tant qu'un importateur dédié, ses tests simulés et un exercice sur une base Turso jetable ne sont pas validés, la restauration Turso doit être considérée comme non vérifiée.

### Conditions de sécurité

- Jamais de restauration expérimentale vers `chappie-db` ou la base configurée pour Render.
- Aucun secret dans les arguments de commande, journaux, commits ou rapports.
- Pas de suppression, remplacement de schéma ou écriture distante sans validation explicite de la cible et autorisation de l'opérateur.
- Une restauration ne doit pas être déclarée réussie sur la seule base d'un checksum ou d'une reconstruction SQLite locale.
