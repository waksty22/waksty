# V36.8 — mémoire autobiographique dans le cerveau cognitif partagé

## Objectif

Vérifier que le module `cognition/shared_brain.py` peut lire les événements
autobiographiques créés par `memory/autobiographical.py` via l'adaptateur
libSQL, puis les présenter au contexte commun en conservant leur provenance.

## Vérifications

- Lecture des événements depuis libSQL et conversion des lignes en dictionnaires.
- Conservation de l'acteur et de l'identifiant de conversation source.
- Inclusion dans le contexte cognitif avec l'étiquette « épisodes autobiographiques sourcés ».
- Isolation stricte par utilisateur.
- Comportement tolérant si les tables autobiographiques ne sont pas encore créées.

## Garanties et limites

- Tests sur une base libSQL locale éphémère `:memory:`.
- Données conversationnelles fictives créées dans les tests.
- Aucune modification de la logique de production du cerveau partagé ou de la mémoire.
- Aucune connexion à Turso distant, aucun changement de données persistées et aucun déploiement Render.
- Les épisodes restent des traces sourcées ; leur présence dans le contexte ne les transforme pas en faits vérifiés ni en preuve de conscience.
