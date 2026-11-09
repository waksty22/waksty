# V50.40 — Outbox durable de finalisation autobiographique

## Pourquoi

Après un commit de conversation, la synchronisation des épisodes autobiographiques et la consolidation des résumés sont des opérations secondaires. Si elles échouent, la conversation source est déjà enregistrée et une simple erreur de log ne suffit pas à garantir une reprise.

## Implémentation

- Nouvelle table additive conversation_finalization_outbox.
- Chaque tour ajoute un travail en attente dans la même transaction que ses messages, son journal et ses effets cognitifs.
- La clé unique utilisateur + curseur de conversation empêche les jobs identiques.
- Les tentatives en échec restent pending avec compteur, horodatage et message d'erreur borné.
- Le finaliseur exécute la synchronisation autobiographique idempotente, la consolidation si nécessaire, puis marque le travail completed.
- Si le processus tombe après la synchronisation mais avant le statut completed, le job sera rejoué ; la synchronisation repose sur des clés uniques et INSERT OR IGNORE.
- Au démarrage, après init_db, Chappie initialise la table puis recherche et traite les travaux pending.
- Les jobs sont aussi traités immédiatement après le commit d'un tour.

## Tests

- Enqueue idempotent et progression pending -> completed.
- Échec enregistré et job conservé pour retry.
- Rollback de l'outbox avec la transaction du tour.
- Intégration avec save_conversation_turn : job créé dans la connexion de l'appelant, sans finalisation prématurée.

## Limites

- La reprise démarre au lancement et après les prochains tours ; il n'y a pas encore de scheduler périodique dédié.
- La synchronisation est idempotente, mais la consolidation des résumés est une étape post-sync distincte.
- Les tests utilisent SQLite temporaire ; pas de preuve de persistance Render, de compatibilité Turso/libSQL ni de déploiement.
- La table outbox est additive et ne modifie ni ne migre les données existantes.

## Sécurité

Aucun accès aux données de production, aucun reset, aucune migration distante, aucun déploiement et aucun changement de secret.
