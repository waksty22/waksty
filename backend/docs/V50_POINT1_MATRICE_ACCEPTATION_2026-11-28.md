# Point 1 — Matrice d'acceptation des fondations cognitives

**Référence :** 28 novembre 2026  
**Périmètre :** code de la branche `main` inspecté en lecture seule.  
**But :** remplacer le pourcentage historique par des critères de fin vérifiables.  
**Sécurité :** cet audit ne lit ni n'écrit les données de production, n'appelle pas Gemini et ne déclenche aucun déploiement.

## Légende

- **Présent** : mécanisme repéré dans le code.
- **Partiel** : mécanisme présent, mais la propriété complète n'est pas démontrée.
- **À construire / démontrer** : capacité ou preuve d'acceptation absente du parcours vérifié.

## État observé

| Domaine | État | Éléments vérifiés | Condition de clôture |
|---|---|---|---|
| Cerveau partagé Chat / Live | Présent, borné | `backend/cognition/shared_brain.py` construit un snapshot versionné V35, limité par utilisateur et par volume. | Tests d'intégration garantissant la cohérence des données partagées et l'absence de fuite inter-utilisateur. |
| Contexte Chat | Présent | Le contexte cognitif partagé est chargé côté serveur pour les requêtes Chat. | Parcours multi-tour prouvant qu'un apprentissage confirmé est rappelé au tour suivant et après redémarrage. |
| Contexte Live initial | Présent | `websocket_endpoint` envoie l'identité, le vocabulaire validé et un snapshot initial après `setupComplete`. | Test d'intégration du contenu exact reçu par le fournisseur et de l'isolation utilisateur. |
| Actualisation Live après un tour | Présent | Après `turnComplete`, le serveur relit le snapshot et le vocabulaire ; les entrées sont suspendues jusqu'à la fin du rafraîchissement. | Tests de concurrence, d'échec de rafraîchissement et de reprise sans contexte périmé. |
| Rappel Live avant texte | Présent | Pour l'action `text`, le serveur construit un rappel pertinent à partir du texte fusionné avant de transmettre le texte au modèle. | Tests de non-régression multi-tour et de cohérence avec le snapshot complet. |
| Rappel Live avant audio | Partiel | Les trames audio sont transmises directement ; leur transcription n'est connue du serveur qu'après traitement fournisseur. Le snapshot initial et le rafraîchissement après tour existent, mais le rappel lexical ciblé ne précède pas l'audio courant. | Définir et tester une stratégie compatible avec le streaming audio, sans bloquer le flux ni envoyer un snapshot à chaque chunk. |
| Persistance audio confirmée | Présent | À la fin du tour Live, la transcription confirmée est enregistrée comme observation sensorielle et reliée temporellement. | Essai réel micro + redémarrage + rappel exact ; les tests automatisés ne remplacent pas l'essai matériel. |
| Réception vidéo Live | Partiel | `live_visual_observation.py` et `server.py` enregistrent une preuve de réception, session et séquence ; l'image brute n'est pas persistée et la réception n'est pas une compréhension. | Politique explicite de rétention/consentement avant toute persistance d'image ; test caméra réel. |
| Analyse visuelle Live | Partiel | Une réponse à une question visuelle explicite peut être persistée comme observation générée par modèle, non vérifiée, avec provenance session/trame et revue humaine requise. | Essais caméra réels, rattachement fiable à la trame analysée et validation humaine avant promotion en connaissance. |
| Rapprochement audio / vision | Présent, supervisé | Les observations peuvent être rapprochées temporellement ; la promotion sémantique exige une confirmation humaine. PR #377 rend la promotion atomique. | Tests bout-en-bout multi-session et vérification qu'une coïncidence temporelle ne devient jamais une identité sans validation. |
| Vocabulaire progressif | Présent, supervisé | Les états lexicaux et les preuves sont séparés ; la progression est contrôlée par l'API d'enseignement et les règles de validation. | Parcours complet Chat + Live + redémarrage, avec preuve que l'exposition seule ne signifie ni compréhension ni maîtrise. |
| Raisonnement causal | Présent, expérimental/supervisé | Observations, hypothèses, expériences approuvées et résultats sont stockés séparément ; les résultats contradictoires ou non concluants conservent l'incertitude. | Tests multi-expériences et multi-sessions ; aucune expérience réelle ou action physique automatique. |
| Décisions et résultats | Présent, protégé | Le journal de décision est partagé ; les évaluations sont protégées contre l'écrasement et les mises à jour concurrentes. | Parcours décision → résultat → réutilisation dans une réponse ultérieure, après redémarrage. |
| Métacognition | Partiel | Les doutes mémoire Chat/Live sont tracés après un tour terminé ; un audit périodique est déclenché sur quatre traces ciblées et ses recommandations sont exposées comme hypothèses. | Démontrer que l'audit améliore effectivement le contrôle des réponses, mesurer faux positifs/négatifs et tester le cycle complet sans fabriquer de traces. |
| Cycle cognitif unifié explicite | À construire / démontrer | Le snapshot commun rassemble des systèmes persistés, mais il ne prouve pas à lui seul un orchestrateur transactionnel unique perception → mémoire → apprentissage → raisonnement → décision → action → consolidation. | Définir un contrat de cycle, ses états, ses erreurs, son idempotence et ses frontières transactionnelles ; l'utiliser dans Chat et Live avec tests d'intégration. |
| Continuité après redémarrage | Partiel | Des tests de persistance indépendants existent pour certains parcours ; le registre historique ne démontre pas encore tous les domaines du point 1. | Suite de tests de processus indépendants couvrant mémoire, vocabulaire, perception, décisions, causalité et contexte Chat/Live. |
| Essais matériels et exploitation | À démontrer | Les tests automatisés ne prouvent pas le comportement réel micro/caméra, la charge, les coûts ou la reprise après interruption. | Procès-verbal d'essais réels, mesures de latence/coût/ressources et scénario de reprise. |

## Ordre de réalisation

1. **Contrat du cycle cognitif** : définir une unité de traitement commune, les entrées/sorties, les identifiants de corrélation, les états et les erreurs récupérables.
2. **Intégration Chat / Live** : faire passer les tours terminés par ce contrat sans dupliquer l'apprentissage ni enregistrer les tours interrompus comme faits confirmés.
3. **Perception multimodale** : assurer la provenance et le rattachement session/trame ; conserver la séparation observation, interprétation, validation et connaissance.
4. **Rappel et consolidation** : prouver le rappel des apprentissages confirmés au tour suivant et après redémarrage.
5. **Évaluation** : ajouter des scénarios de bout en bout, puis des essais réels micro/caméra et exploitation.

## Règles de clôture du point 1

Le point 1 ne passe à 100 % que si chaque ligne est soit validée par un test automatisé pertinent, soit couverte par un essai réel documenté lorsque le matériel ou le fournisseur est indispensable. Les mécanismes « présents » ne suffisent pas à eux seuls. Les éléments « partiels » ou « à construire » restent bloquants.

Aucun pourcentage n'est recalculé par ce document. Aucun changement de schéma, de mémoire de production, de configuration Render ou de service externe n'est autorisé par cette matrice.
