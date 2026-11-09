# V50.43 — Matrice de compatibilité SQLite → Turso

## Résultat attendu

Cette version transforme l'inventaire V50.42 en matrice de décision lisible et reproductible. Chaque catégorie détectée indique :
- une classification de risque ;
- le nombre d'occurrences ;
- les fichiers concernés ;
- la raison technique ;
- la validation obligatoire avant bascule.

## Classes

- **BLOQUANT AVANT BASCULE** : l'application ne peut pas être activée sur Turso tant que ce point n'est pas remplacé ou isolé.
- **BLOQUANT SI UTILISÉ EN PRODUCTION** : activation interdite si le chemin concerné est utilisé sans équivalent testé.
- **À ADAPTER** : la couche applicative doit séparer les comportements locaux et distants.
- **À VÉRIFIER SUR STAGING** : aucune conclusion de compatibilité sans test sur un environnement Turso isolé.
- **REVUE MANUELLE REQUISE** : motif non classé par les règles automatiques.

## Points importants

- `sqlite3.connect`, le démarrage SQLite et les sauvegardes de fichiers restent des bloqueurs de bascule.
- `executescript` et les PRAGMA doivent être séparés selon le backend.
- `row_factory`, types d'erreurs, métadonnées de curseur et transactions doivent être validés avec le vrai pilote.
- Les DDL, clés étrangères, fonctions JSON/date, triggers, index et UPSERT doivent être testés sur staging.
- La matrice ne prétend pas que les syntaxes SQLite sont incompatibles par défaut ; elle impose une preuve ciblée pour les usages réellement trouvés.

## Sécurité et limites

Le rapport est statique : aucune connexion à une base, aucun secret lu, aucune donnée modifiée. Le scanner peut manquer le SQL construit dynamiquement. `activation_allowed` reste toujours `false` : seule une suite d'intégration distante et une procédure de migration/restauration validée pourront lever ce blocage, après approbation explicite.
