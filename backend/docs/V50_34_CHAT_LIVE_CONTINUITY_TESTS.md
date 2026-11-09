# V50.34 — Tests isolés de continuité mémoire Chat ↔ Gemini Live

**Statut : tests automatisés sur SQLite temporaire. Aucun appel Gemini, aucun accès Render/Turso, aucune donnée de production.**

## Ce que les tests exécutent réellement

Le banc de test importe la vraie fonction de persistance du serveur et le vrai lecteur du cerveau partagé. Seule l'ouverture de la base est remplacée par un fichier SQLite temporaire, et l'identité utilisateur est neutralisée pour le test.

Scénarios :
1. un tour écrit (source=conversation) est ensuite retrouvé dans les épisodes autobiographiques du cerveau partagé ;
2. un tour Live (source=gemini_live) est retrouvé par le même lecteur partagé ;
3. les deux canaux alimentent une seule chronologie, puis les données restent lisibles après fermeture et réouverture des connexions ;
4. un tour vide/interrompu n'écrit rien si le pont Live ne finalise pas le tour ;
5. un contrat futur d'idempotence est présent comme test xfail strict : le code actuel ne possède pas d'identifiant stable de tour et duplique donc une retransmission. Le test ne masque pas ce défaut et deviendra une alerte si le comportement change sans mise à jour du contrat.

## Limites importantes

- Ce sont des tests du chemin de persistance commun, pas une simulation du protocole réseau Gemini Live.
- Les appels au fournisseur Gemini, les flux audio, les reconnexions WebSocket réelles et les erreurs de transport ne sont pas simulés.
- La continuité est démontrée dans un fichier SQLite temporaire uniquement. Cela ne prouve ni la persistance sur le système de fichiers éphémère Render, ni le fonctionnement du backend Turso/libSQL.
- Le code Live journalise actuellement une erreur de sauvegarde et peut poursuivre la session. Une confirmation de persistance côté client reste à concevoir.

## Critères de sortie

- [x] Lecture croisée des tours Chat et Live via le cerveau partagé.
- [x] Source du canal conservée dans le journal.
- [x] Réouverture des connexions SQLite et relecture des épisodes.
- [x] Tour vide ignoré.
- [ ] Idempotence des retransmissions (identifiant stable de tour requis).
- [ ] Tests WebSocket/Gemini Live simulés avec transport factice.
- [ ] Même suite sur un environnement Turso isolé.
- [ ] Validation sur stockage persistant et après redémarrage Render.

**Aucune migration, aucun déploiement, aucune écriture Turso et aucune modification des secrets dans V50.34.**
