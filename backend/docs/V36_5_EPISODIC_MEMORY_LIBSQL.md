# V36.5 — Intégration réelle de la mémoire épisodique avec libSQL

## Périmètre

Cette étape valide le module existant `memory/episodic_memory.py` avec
l'adaptateur `storage/libsql_adapter.py`, sur une base libSQL locale
`:memory:`. Elle ne connecte pas Chappie à Turso distant.

## Scénarios couverts

- Initialisation du schéma et des index du module.
- Sauvegarde d'un souvenir avec catégorie, provenance, confiance et tags.
- Recherche insensible à la casse et conversion des lignes en dictionnaires.
- Mise à jour du compteur d'accès et lecture des statistiques.
- Mise à jour d'un souvenir existant sans diminuer son importance.
- Réinitialisation idempotente du schéma et isolation par utilisateur.

## Limites explicites

- Aucun changement du module de mémoire de production.
- Aucune modification de la fabrique de connexion de `server.py`.
- Aucun accès à `chappie-db` ou `chappie-memory` sur Turso.
- Aucun déploiement Render et aucune migration de données.

Le test doit passer avec le pilote libSQL réel dans GitHub Actions avant
d'étendre l'intégration à d'autres modules cognitifs.
