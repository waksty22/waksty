# V50.25 — Publication atomique des sauvegardes logiques

**Statut : proposition en revue — aucun déploiement, aucune écriture Turso et aucune modification de production.**

## Objectif

Éviter qu'une sauvegarde logique incomplète ou qu'un fichier de checksum préexistant soit remplacé silencieusement. Le couple fichier chiffré/non chiffré + checksum doit être publié sans écrasement et nettoyé si la vérification finale échoue.

## Modifications

- Refus de démarrer si le fichier de sauvegarde **ou** son sidecar SHA-256 existe déjà.
- Publication du fichier de données par lien dur atomique, qui échoue si une autre exécution a créé la destination entre-temps.
- Création du sidecar dans un fichier temporaire unique, puis publication atomique sans écrasement.
- Suppression des artefacts créés par cette exécution si la publication du checksum ou la vérification de restauration échoue.
- Fichiers temporaires uniques pour éviter les collisions entre exécutions concurrentes.

## Tests ajoutés

- Préservation d'un checksum préexistant et absence de création du fichier de données.
- Nettoyage du fichier et du sidecar si la vérification de restauration isolée échoue.
- Conservation des tests existants de schéma, données, BLOB, intégrité, chiffrement et détection d'altération.

## Limites et sécurité

- Tests locaux SQLite uniquement ; aucune validation réelle d'une base distante Turso n'est revendiquée.
- Le serveur reste verrouillé sur SQLite ; aucune bascule du backend.
- Aucun accès réseau, secret, donnée de production ou base distante modifié.
- Aucun merge ni déploiement Render.
