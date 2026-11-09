# V50.32 — Plan de migration SQLite vers Turso

**Statut : conception uniquement. Aucun accès distant, aucune écriture, aucune migration, aucun changement Render.**

## Décision de sécurité

SQLite reste le stockage actif tant que le contrat applicatif complet n'est pas validé. Cette version ne réalise aucune migration et ne modifie aucune variable d'environnement. Elle définit un protocole vérifiable, reprenable et réversible pour une future migration explicitement approuvée.

Les cinq lignes actuellement observées dans l'artefact Turso sont des données d'état/configuration, pas un historique complet. Elles ne doivent jamais être prises comme cible de référence ni écrasées par une base vide.

## Sources et périmètre

Avant toute migration, il faudra sélectionner explicitement :
- une sauvegarde source SQLite dont le contenu attendu est connu et dont le checksum est vérifié ;
- une destination Turso identifiée, inspectée en lecture seule et sauvegardée indépendamment ;
- une version de schéma cible documentée ;
- une fenêtre de maintenance empêchant les écritures concurrentes pendant le transfert final.

Aucun secret ne doit être copié dans les rapports, journaux ou artefacts.

## Inventaire préalable obligatoire

L'inventaire doit couvrir, pour chaque base :
1. tables, colonnes, types, valeurs par défaut et contraintes ;
2. clés primaires, clés étrangères et index uniques/non uniques ;
3. vues et triggers ;
4. versions de schéma et migrations appliquées ;
5. nombre de lignes par table ;
6. empreintes de contenu par table, calculées de façon canonique sans exporter les données personnelles dans le rapport.

Les différences doivent être classées en trois catégories : compatibles, transformables par une règle versionnée, bloquantes. Toute différence non classée bloque la migration.

## Protocole proposé

### Phase A — Dry-run local, sans écriture distante

- Déchiffrer une sauvegarde SQLite vérifiée dans un répertoire temporaire isolé.
- Construire l'inventaire source et l'inventaire cible depuis un instantané/export de lecture seule.
- Comparer schéma, contraintes, index, compteurs et empreintes.
- Produire un rapport de différences sans valeurs de souvenirs, conversations, jetons ou secrets.
- Refuser de poursuivre si une table source est absente, si un compte est inexpliqué, si une empreinte diffère sans règle de transformation ou si l'intégrité échoue.

### Phase B — Préparation d'une destination isolée

- Créer une destination de test distincte de la base métier.
- Appliquer le schéma cible avec des migrations versionnées et idempotentes.
- Vérifier chaque étape et enregistrer sa version.
- Importer par lots avec clés stables et stratégie anti-doublons.
- Rejouer le contrôle des compteurs, contraintes et empreintes.
- Tester lecture, mise à jour et transaction/rollback sur des données synthétiques uniquement.

### Phase C — Répétition et reprise

- Interrompre volontairement un import de test à plusieurs points.
- Reprendre sans dupliquer les lignes déjà importées.
- Vérifier qu'une seconde exécution ne change pas le résultat.
- Restaurer la destination isolée depuis sa sauvegarde et refaire les contrôles.
- Tester l'accès simultané chat écrit et Gemini Live sur le même stockage de test.

### Phase D — Bascule future, séparément autorisée

Cette phase ne sera pas exécutée dans V50.32. Elle nécessitera une approbation explicite distincte après revue des rapports :
1. geler les écritures sur la source ;
2. créer et vérifier une dernière sauvegarde chiffrée ;
3. exécuter l'import final idempotent ;
4. comparer les inventaires complets ;
5. vérifier les parcours chat et Gemini Live ;
6. basculer le serveur avec une procédure documentée ;
7. vérifier après redémarrage Render ;
8. conserver la source intacte et le plan de retour arrière jusqu'à validation.

## Critères de blocage absolus

- Source ou destination non identifiée sans ambiguïté.
- Sauvegarde sans checksum valide ou restauration non vérifiée.
- Schéma incomplet ou différences non expliquées.
- Compteurs ou empreintes différents.
- Clés étrangères invalides ou index/contraintes manquants.
- Import non idempotent ou reprise non démontrée.
- Tests chat/Live divergents.
- Absence de retour arrière vérifié.

## Critères de sortie V50.32

- [x] Protocole dry-run, migration, reprise et retour arrière documenté.
- [x] Rapports conçus pour ne pas révéler les données personnelles.
- [x] Aucune opération distante ou de production dans cette version.
- [ ] Implémentation d'un inventaire local de snapshots vérifiés.
- [ ] Validation sur fixtures synthétiques complètes.
- [ ] Revue et approbation explicite avant tout accès en écriture à Turso.
