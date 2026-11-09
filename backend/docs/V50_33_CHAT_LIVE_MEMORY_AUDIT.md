# V50.33 — Audit de continuité mémoire entre Chat et Gemini Live

**Statut : audit statique et contrat de tests. Aucune modification du comportement en production.**

## Constat vérifié dans le code

### Points déjà mutualisés

- Le chat HTTP `/api/chat` délègue à `run_brain(user_id, message)`.
- Le pont WebSocket Gemini Live utilise le même `db_connection()` que les routes HTTP.
- Le chat construit son contexte cognitif avec `get_shared_brain_snapshot()` et `format_shared_brain_context()`.
- Le pont Live utilise le même système de vocabulaire validé, lit les mots répétables et enregistre les mots entendus.
- À la fin d'un tour Live, le serveur appelle `save_conversation_turn(..., source="gemini_live")`.
- Les transcriptions Live sont accumulées dans un état de tour temporaire avec `merge_live_transcript()`, puis le tour est envoyé au stockage commun.

### Ce qui n'est pas encore démontré

Le partage d'un module, d'une base ou d'une fonction ne prouve pas à lui seul l'équivalence cognitive des deux canaux. Il reste à vérifier par tests d'intégration :

1. qu'un message écrit est immédiatement récupérable par le contexte du tour Live suivant ;
2. qu'un tour Live est récupérable par le chat écrit suivant ;
3. que les deux canaux lisent et mettent à jour le même état affectif, vocabulaire, souvenirs, résumé et modèle du monde ;
4. que les tours incomplets ou interrompus ne sont pas enregistrés comme conversations complètes ;
5. que les erreurs de persistance sont visibles et ne sont pas masquées par une réponse utilisateur présentée comme sauvegardée ;
6. que les écritures concurrentes restent cohérentes et qu'aucun doublon n'est créé lors d'une reconnexion.

Le code actuel journalise un échec de sauvegarde Live sans interrompre nécessairement la session. Il faudra définir une confirmation de persistance explicite côté client avant d'affirmer qu'un tour est durable.

## Contrat cible

Un seul service de mémoire partagé doit fournir des opérations explicites et testables :
- charger le contexte commun borné par utilisateur ;
- enregistrer un tour complet avec canal source et identifiant idempotent ;
- enregistrer une observation/transcription avec provenance ;
- récupérer les souvenirs, résumés, vocabulaire, émotions et connaissances pertinentes ;
- consolider les conversations sans dupliquer les épisodes ;
- signaler séparément succès du modèle et succès de persistance.

Le stockage sous-jacent doit être injecté au service, et non choisi implicitement par chaque module. Les deux canaux doivent utiliser le même contrat et le même identifiant utilisateur normalisé.

## Plan de validation

Sur une base SQLite temporaire et des données synthétiques uniquement :
1. écrire un tour via le chemin chat, puis lire son contenu via le chemin Live ;
2. écrire un tour Live, puis le relire via le chemin chat ;
3. vérifier les souvenirs et le vocabulaire acquis depuis chaque canal ;
4. simuler une interruption avant la fin du tour ;
5. rejouer le même identifiant de tour pour prouver l'idempotence ;
6. lancer des écritures concurrentes et vérifier les comptes/empreintes ;
7. fermer/réouvrir la base et répéter les lectures.

Ensuite, refaire exactement ces tests sur un environnement Turso isolé, après validation complète du contrat libSQL. Ne pas utiliser la base Turso métier actuelle pour ces tests.

## Blocages

- Pas de bascule Turso tant que V50.31 et le protocole V50.32 ne sont pas validés.
- Pas de déploiement tant que les tests d'intégration chat ↔ Live ne sont pas concluants.
- Pas de suppression, fusion destructive ou réinitialisation de l'historique.
- Aucune promesse de mémoire durable sur la seule base d'un test local SQLite.

## Critères de sortie

- [x] Audit statique des chemins chat et Live.
- [x] Contrat cible et scénarios d'intégration documentés.
- [ ] Service de mémoire partagé extrait et injecté.
- [ ] Tests bidirectionnels chat ↔ Live sur SQLite isolé.
- [ ] Tests d'idempotence, interruption et concurrence.
- [ ] Répétition complète sur Turso isolé.
- [ ] Validation après redémarrage du serveur.
