# V50.26 — Contrat de restauration avec checksum obligatoire

**Statut : proposition en revue. Aucun déploiement ni changement de base de production.**

## Objectif

Une base SQLite peut passer `PRAGMA integrity_check` tout en contenant des données modifiées. L'intégrité structurelle ne prouve donc pas que le fichier est celui qui avait été sauvegardé. V50.26 lie chaque sauvegarde à un checksum SHA-256 persistant et vérifie ce checksum avant toute opération de restauration.

## Modifications

- `create_verified_backup` crée une sauvegarde locale SQLite, vérifie son intégrité et publie un sidecar `.sha256`.
- La publication de la sauvegarde et du sidecar refuse tout écrasement préexistant et utilise des liens durs atomiques dans le même répertoire.
- `restore_verified_backup` exige le sidecar, vérifie son nom et son SHA-256, puis contrôle l'intégrité SQLite **avant** de créer le rollback ou de toucher à la cible.
- La copie de rollback est accompagnée de son propre sidecar vérifiable et reste disponible après une restauration réussie.
- Si la préparation échoue avant le remplacement atomique, les artefacts de rollback temporaires créés par cette tentative sont nettoyés.
- Les tests couvrent une base SQLite modifiée mais structurellement valide, un checksum absent, le refus d'écrasement et la restauration du rollback.

## Compatibilité

Les anciennes sauvegardes créées sans sidecar SHA-256 ne sont volontairement plus considérées comme fiables par cette fonction. Elles doivent être vérifiées et réexportées selon un processus contrôlé avant d'être restaurables par ce contrat. Ne pas fabriquer un checksum après coup pour une sauvegarde dont la provenance n'est pas établie.

## Limites et sécurité

- Périmètre strictement local SQLite ; aucune validation de restauration distante Turso n'est revendiquée.
- Aucun endpoint de production, secret, donnée Render ou base Turso n'a été modifié.
- Pas de merge ni de déploiement Render.
