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

Le 19 novembre 2026, le workflow de sauvegarde a terminé avec succès : 42 tables et 81 lignes ont été exportées dans l'archive chiffrée, puis la vérification après empaquetage a réussi. L'artefact GitHub Actions observé était conservé jusqu'au 17 février 2027. Cette réussite ne change pas les limites de restauration décrites ci-dessus.
