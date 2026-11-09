# V50.37 — Registre transactionnel des événements cognitifs

## Composant ajouté

`cognition.event_receipts` fournit une primitive commune :
`claim_cognitive_event(db, user_id, event_id, effect_kind)`.

Clé d'unicité :
`(user_id, event_id, effect_kind)`.

Cela permet à un même événement de protéger plusieurs effets indépendants (affect, vocabulaire, sensoriel) sans que l'un bloque l'autre. Un même effet du même événement ne peut être revendiqué qu'une fois pour un utilisateur.

## Propriété transactionnelle

Le module n'appelle jamais `commit()`. Le code appelant doit revendiquer le reçu et écrire l'effet secondaire sur la même connexion et dans la même transaction. Si l'effet échoue et que la transaction est annulée, le reçu est annulé lui aussi.

Un identifiant absent ou vide conserve explicitement le comportement historique (pas de déduplication). Le module valide le périmètre utilisateur et le type d'effet.

## Tests isolés

- Un couple événement/effet ne peut être revendiqué qu'une fois.
- Un événement peut protéger plusieurs types d'effets.
- Les utilisateurs restent isolés.
- L'absence d'identifiant garde le comportement historique.
- Un rollback annule reçu et effet ensemble.
- Les champs de portée obligatoires sont validés.

## Périmètre

Cette PR ajoute la primitive et ses tests, mais ne branche pas encore les fonctions affectives, lexicales ou sensorielles. Leur intégration nécessite de fournir de vrais identifiants stables à chaque événement, en particulier pour les transcriptions Live segmentées. Cette intégration sera traitée séparément et ne doit pas être simulée par un hash du texte seul.

Aucune connexion Render/Turso, aucune donnée de production, aucune migration de données, aucun déploiement, aucun reset et aucun changement de secret.
