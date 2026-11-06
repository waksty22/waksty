# V36.6 — intégration libSQL de la mémoire spatiale

## Module ciblé
`world/spatial_memory.py`

## Couverture réelle sur libSQL local en mémoire
- Consentement explicite avant ouverture d'une session de localisation.
- Enregistrement d'échantillons GPS, déduplication par horodatage et arrêt de session.
- Isolation stricte des données par utilisateur.
- Validation des coordonnées et rejet d'une précision GPS insuffisante.
- Enregistrement d'observations visuelles, rapprochement en candidat et confirmation humaine explicite.
- Lecture de la carte et des statistiques via les lignes normalisées par l'adaptateur.

## Confidentialité et sécurité
Tous les tests utilisent `:memory:` et des coordonnées fictives. Aucun suivi réel, aucune géolocalisation de l'utilisateur, aucun accès Turso distant. Le module et la fabrique de connexion de production ne sont pas modifiés. Aucun déploiement Render.
