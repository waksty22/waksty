# V50.35 — Idempotence des tours de conversation

## Changement

Chaque tour peut désormais porter un identifiant stable facultatif `turn_id`. Une table additive `conversation_turn_receipts` possède une clé primaire composée de `(user_id, turn_id)`.

L'écriture du reçu, des messages utilisateur/assistant et de l'entrée de journal se fait dans la même transaction SQLite. En cas de rejeu du même identifiant pour le même utilisateur, la fonction retourne `False` sans ajouter de messages ni d'entrée de journal. Un identifiant identique appartenant à un autre utilisateur reste indépendant.

## Intégrations

- **Chat HTTP** : `ChatRequest.request_id` est facultatif, validé et transmis à `run_brain`, puis au writer. Le client peut réutiliser le même identifiant lors d'une reprise/retransmission de requête.
- **Gemini Live** : un identifiant aléatoire est créé à l'ouverture de chaque tour et renouvelé après `turnComplete`. Il est réutilisé pour toute tentative de sauvegarde du même tour pendant cette session.
- Les appels internes historiques qui ne fournissent pas d'identifiant gardent le comportement antérieur. L'idempotence est garantie uniquement lorsque le même identifiant est transmis.

## Compatibilité et limites

- La table est créée avec `CREATE TABLE IF NOT EXISTS` au moment de l'écriture : changement additif, sans effacer ni reconstruire les tables existantes.
- Cela cible le backend SQLite actuellement utilisé. Ce n'est pas une preuve de compatibilité libSQL/Turso.
- Un client Chat qui ne transmet pas `request_id` ne bénéficie pas de la déduplication entre requêtes HTTP distinctes.
- L'identifiant Live est stable pendant la vie du tour en mémoire, mais n'est pas conservé par un client lors d'une reconnexion complète du WebSocket.
- Les effets secondaires effectués avant la sauvegarde (par exemple snapshots affectifs ou enseignement lexical) ne sont pas tous dédupliqués par le reçu conversationnel. Ils devront être traités dans un audit de cohérence séparé.

## Tests

- Rejeu du même tour : une seule paire de messages et un seul reçu/journal.
- Même identifiant entre utilisateurs : isolation respectée.
- Texte identique avec identifiants différents : les deux tours sont conservés.
- Les tests V50.34 de lecture croisée Chat/Live et de réouverture SQLite restent présents.

## Sécurité

Tests sur SQLite temporaire uniquement. Aucun appel Gemini réel, aucune connexion Render/Turso, aucune écriture de production, aucun déploiement, aucune migration de données et aucun changement de secret.
