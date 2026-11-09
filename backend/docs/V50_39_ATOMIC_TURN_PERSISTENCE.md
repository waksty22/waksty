# V50.39 — Atomicité de la persistance des tours

## Objectif

Éviter qu'un tour de conversation soit enregistré sans ses effets cognitifs, ou inversement, lorsqu'une opération échoue avant validation de la transaction.

## Changements

- save_conversation_turn accepte désormais une connexion SQLite fournie par l'appelant. Dans ce mode, il n'ouvre ni ne valide sa propre transaction et ne lance pas de consolidation prématurée.
- finalize_conversation_turn effectue la synchronisation autobiographique et la consolidation uniquement après le commit.
- analyze_user_intent et update_emotions_once acceptent une connexion externe ; leurs écritures rejoignent la transaction du tour sans commit interne.
- Chat classique : les effets affectifs, l'intention, l'enseignement explicite, le reçu de tour, les messages et le journal sont désormais écrits dans une transaction SQLite unique après obtention de la réponse.
- Gemini Live : reçu/conversation et effets affectifs, exposition lexicale, observation audio et enseignement sont écrits dans une transaction unique au tour terminé.
- Une erreur avant commit annule ensemble les reçus, messages et effets cognitifs.
- La consolidation autobiographique reste volontairement post-commit : elle est dérivée de la conversation déjà validée et ne doit pas maintenir la transaction principale ouverte.

## Tests

Quatre tests SQLite temporaires couvrent rollback global, commit groupé, rejeu idempotent et deux tours distincts avec contenu identique.

## Limites

- Atomicité garantie pour la transaction SQLite locale qui reçoit la connexion ; ce n'est pas une preuve de transaction distribuée Turso/libSQL.
- Les effets produits pendant la génération (outils cognitifs éventuels, traces annexes) ne sont pas tous intégrés à cette transaction et nécessitent un audit distinct.
- La synchronisation autobiographique et la consolidation de résumés restent post-commit. En cas d'échec, elles sont journalisées mais leur reprise automatique devra être traitée séparément.
- Le request_id côté Chat doit être réutilisé par le client pour rendre les retries inter-requêtes idempotents.
- Aucun test WebSocket Gemini réel, aucun test Render/Turso en production.

## Sécurité

SQLite temporaire et données synthétiques uniquement. Aucun accès aux données de production, aucune migration, aucun déploiement, aucun reset et aucun changement de secret.
