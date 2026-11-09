# V50.36 — Audit des effets secondaires cognitifs

## Conclusion

V50.35 protège l'écriture du tour conversationnel lorsqu'un identifiant stable est transmis. Il ne rend pas encore idempotents les autres écritures cognitives exécutées avant ou pendant la finalisation du tour.

## Chemins observés dans le code

### Chat classique
- `run_brain()` appelle `update_emotions_once()` avant la génération de réponse.
- Le texte utilisateur est envoyé à `record_explicit_word_teaching()` avant l'écriture finale du tour.
- `save_conversation_turn()` utilise désormais un reçu `turn_id`, mais ce reçu n'encapsule pas les écritures affectives ou lexicales précédentes.

### Gemini Live
- Chaque transcription reçue met à jour l'état affectif.
- Chaque transcription peut ajouter une ligne à `affective_history`.
- `record_heard_text()` incrémente `exposure_count` pour les mots déjà entendus.
- Chaque transcription crée une observation sensorielle avec un UUID aléatoire.
- À `turnComplete`, l'enseignement lexical explicite est enregistré séparément du reçu conversationnel.

## Défauts reproductibles confirmés sur SQLite temporaire

Les tests de cette version démontrent les comportements actuels suivants :
1. deux livraisons du même événement affectif créent deux lignes d'historique ;
2. deux livraisons de la même transcription augmentent deux fois l'exposition lexicale ;
3. deux enseignements explicites identiques augmentent deux fois l'exposition du mot ;
4. deux observations sensorielles identiques créent deux observations distinctes.

Ces tests sont des sondes d'audit, pas des objectifs fonctionnels. Ils devront être inversés lorsque l'idempotence événementielle sera implémentée.

## Architecture recommandée pour V50.37

- Introduire un identifiant d'événement stable, distinct du simple horodatage.
- Utiliser un registre de reçus événementiels unique par utilisateur, canal et événement.
- Transmettre le même identifiant aux écritures affectives, lexicales, sensorielles et autobiographiques.
- Éviter de dédupliquer sur le seul texte : deux occurrences identiques à des moments différents peuvent être deux expériences légitimes.
- Garantir que le reçu et l'effet secondaire correspondant sont écrits dans la même transaction.
- Pour les transcriptions segmentées, distinguer l'identifiant de segment et l'identifiant du tour complet.

## Limites et sécurité

- Tests limités à des bases SQLite temporaires et des données synthétiques.
- Aucun appel Gemini, aucune connexion Render/Turso, aucune donnée de production.
- Aucun déploiement, aucune migration de données, aucun reset et aucun changement de secret.
- La compatibilité libSQL/Turso et la continuité après redémarrage Render restent non démontrées.
