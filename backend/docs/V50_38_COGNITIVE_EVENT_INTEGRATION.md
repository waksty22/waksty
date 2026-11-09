# V50.38 — Intégration des reçus cognitifs dans Chat et Gemini Live

## Modifications

### Chat classique
- Un identifiant d'événement cognitif est dérivé du `request_id` transmis au cerveau ; à défaut, un identifiant de traitement est généré.
- Mise à jour de l'état émotionnel et snapshot affectif protégés par des reçus distincts.
- Enseignement lexical explicite protégé par un reçu dédié.

### Gemini Live
- Les effets cognitifs ne sont plus enregistrés à chaque fragment de transcription.
- Les fragments sont agrégés dans le texte du tour, puis les effets sont enregistrés à `turnComplete` sous le même `turn_id`.
- Affect, exposition lexicale, observation audio et enseignement explicite sont chacun dédupliqués par type d'effet.
- L'observation audio utilise un identifiant déterministe dérivé de l'utilisateur, du tour et de la modalité. Le même tour retrouve la même observation ; un tour distinct crée une nouvelle observation même si le texte est identique.
- L'enregistrement des effets (hors mise à jour d'état émotionnel, qui possède sa propre transaction interne) partage une transaction SQLite afin que reçu et effet soient annulés ensemble.

## Tests ajoutés

- Snapshot affectif une seule fois par événement.
- Exposition lexicale une seule fois par événement, mais comptée à nouveau sur un tour distinct.
- Enseignement explicite une seule fois.
- Observation sensorielle stable et non dupliquée.
- Deux événements distincts avec texte identique restent deux expériences.
- Rollback du reçu et de l'effet lexical ensemble.

## Limites connues

- L'idempotence inter-reconnexion nécessite que le client fournisse et réutilise le même identifiant de requête/tour. Un identifiant généré côté serveur protège seulement les reprises dans la même exécution.
- Les événements émotionnels du chat peuvent encore avoir des effets secondaires annexes dans l'analyse d'intention, qui doivent être audités séparément.
- La mise à jour d'état émotionnel et les autres effets sont des transactions séparées ; l'atomicité globale du tour n'est pas garantie.
- Les flux WebSocket Gemini réels ne sont pas simulés dans cette PR.
- Le backend cible encore le SQLite actif ; aucune preuve Turso/libSQL ou de persistance après redémarrage Render.

## Sécurité

Tests sur SQLite temporaire et données synthétiques uniquement. Aucun accès Render/Turso, aucune migration, aucun déploiement, aucun reset et aucun changement de secret.
