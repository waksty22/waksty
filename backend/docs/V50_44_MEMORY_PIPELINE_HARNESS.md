# V50.44 — Banc de test du pipeline mémoire

**Statut : tests isolés uniquement. Aucun accès à Render, Turso, Gemini ou à la production.**

## Objectif

Tester le trajet des données persistantes de Chappie avec les fonctions réelles du dépôt, sur des bases SQLite temporaires :

- conversation écrite et tour Gemini Live dans le même historique ;
- outbox de finalisation transactionnelle ;
- indexation autobiographique après commit ;
- reprise des travaux en attente après fermeture/réouverture ;
- idempotence des tours et des événements d'apprentissage ;
- progression lexicale graduelle et conservation après réouverture ;
- cloisonnement des données par utilisateur.

## Tests ajoutés

`backend/tests/test_v50_memory_pipeline_harness.py` vérifie six scénarios :
1. chat + Live, fermeture/réouverture, récupération de l'outbox et lecture via le cerveau partagé ;
2. rollback de la conversation, du journal et de l'outbox comme une seule transaction ;
3. échec temporaire d'indexation, maintien en attente, puis reprise après redémarrage simulé ;
4. finalisation répétée sans duplication des épisodes ;
5. reçu d'événement lexical, exposition unique et progression d'état sans saut ;
6. séparation stricte des souvenirs entre deux identifiants utilisateur.

Le test de l'adaptateur libSQL est également corrigé : `lastrowid` est exposé pour les instructions INSERT/REPLACE simples, jamais repris d'un curseur natif périmé après SELECT/UPDATE. `executemany` n'annonce pas de nouvel identifiant.

## Ce que cela prouve

Si la CI passe, les fonctions réelles testées conservent ces invariants sur SQLite local temporaire, y compris fermeture/réouverture de fichier et reprise de l'outbox.

## Ce que cela ne prouve pas

- Cela ne prouve pas encore le comportement du pilote distant Turso.
- Cela ne prouve pas la conservation sur un redémarrage Render réel.
- Cela ne remplit pas les tables vides actuellement constatées dans les sauvegardes.
- Cela ne réalise aucune migration ni bascule de backend.

La matrice V50.43 reste informative ; Turso demeure désactivé dans la fabrique applicative. Une validation distante nécessite un environnement Turso de staging isolé et autorisé, puis un parcours d'écriture/lecture/fermeture/réouverture/restauration avant toute décision de bascule.
