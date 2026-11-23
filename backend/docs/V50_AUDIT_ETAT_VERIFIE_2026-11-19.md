# Chappie V50 — registre d'audit vérifié

**Date de référence : 19 novembre 2026**  
**Branche :** `feat/safe-logical-restore-core`  
**PR de consolidation :** [#133](https://github.com/waksty22/waksty/pull/133)  
**Périmètre :** audit du code et tests automatisés. Aucune opération sur la production.

## 1. Règle de comptage des audits

Les audits numérotés **51 à 137 inclus** ont été examinés, soit 87 éléments. En revanche, aucun registre canonique retrouvé dans le dépôt ne donne, ligne par ligne, le résultat de chaque audit : corrigé, testé, validé, partiel ou restant.

Par conséquent, le chiffre historique « 137/200 » ne signifie pas que 137 corrections sont toutes validées. Il reste un compteur de progression historique, pas une preuve d'acceptation. Ce document sert de base vérifiable pour éviter de perdre les chantiers ; il devra être enrichi avec un identifiant et un test d'acceptation par défaut.

## 2. Corrections désormais présentes dans la PR #133

Les changements ci-dessous ont été poussés sur la branche de consolidation et validés par CI sur le commit de référence `ab746a37feb62f727caa54d6d8e63565585d7e52`.

- **Rappel autobiographique exact :** recherche par tokens complets plutôt que sous-chaînes ; évite qu'une recherche « art » rappelle « partageons ».
- **Rappel épisodique exact :** mêmes limites de tokens et correspondance de phrase sur une séquence de tokens.
- **Apprentissage lexical Live :** fusion du texte d'un tour, puis enregistrement de l'exposition une seule fois à la fin du tour confirmé ; l'enseignement explicite reste distinct d'une simple exposition.
- **Validation audio/vision :** candidats de rapprochement confirmables ou rejetables avec preuve, décision irréversible et aucune promotion automatique en connaissance du monde ; interface ajoutée au tableau de bord et validation JSON côté serveur.
- **Connexions DB :** fermeture effective des connexions SQLite/libSQL à la sortie des blocs de contexte, avec préservation du commit/rollback et de l'exception d'origine.
- **Persistance après redémarrage :** tests de processus indépendants pour les conversations Chat/Live et les apprentissages multimodaux du cerveau partagé.
- **Pensées :** l'API expose maintenant les ruminations stockées dans `thoughts` ainsi que les traces de `cognitive_traces`, au lieu de masquer les ruminations.
- **Fraîcheur Live :** consigne système demandant au modèle de relire `get_shared_brain_state` lorsque sa réponse dépend d'un apprentissage ou souvenir susceptible d'avoir changé pendant la session.
- **Restauration Turso :** documentation explicite de la différence entre vérification locale de l'archive quotidienne et E2E de restauration sur base de test isolée.

Des corrections antérieures déjà présentes dans la branche protègent aussi les propriétés d'objets confirmées, empêchent l'écrasement d'un état du monde plus fiable par une observation faible, conservent provenance/confiance dans les comparaisons, et évitent une double évaluation causale.

## 3. Vérifications automatisées observées

Sur le commit `ab746a37feb62f727caa54d6d8e63565585d7e52` :

- Qualité : **774 tests réussis**.
- Tests de sécurité du stockage : réussite.
- E2E sauvegarde/restauration Turso schéma complet sur cible isolée : réussite.

La sauvegarde quotidienne observée le 19 novembre a exporté 42 tables et 81 lignes dans une archive chiffrée ; sa vérification après empaquetage a réussi. L'artefact GitHub Actions observé expirait le 17 février 2027.

Le test E2E Turso utilise son propre jeu de données synthétiques et sa propre archive sur une base de test isolée. Il ne restaure pas l'artefact quotidien réel et n'écrit pas dans la base de production.

## 4. État fonctionnel constaté dans le code

- Le constructeur commun `get_identity_context` rassemble profil cognitif, compétences validées, émotions simulées, objectifs, mémoire et contexte du cerveau partagé.
- Le Chat reconstruit ce contexte à chaque requête.
- Gemini Live charge un instantané au démarrage de session ; l'outil `get_shared_brain_state` permet une actualisation pendant la session. La consigne système demande maintenant son utilisation quand le contexte initial peut être périmé, mais l'actualisation n'est pas encore imposée côté serveur à chaque tour.
- Le cerveau partagé contient des données de vocabulaire, mémoire, autobiographie, observations sensorielles, associations mot-image, objets, relations et candidats de fusion audio/vision.
- Le moteur cognitif calcule le profil à partir des évaluations de compétences supervisées ; les anciens XP agrégés ne prouvent pas une maîtrise.
- Les rêves et ruminations existent, sont persistés et sont explicitement simulés. Leur contenu est actuellement généré par des modèles textuels à partir de souvenirs et d'états, pas par un cycle de raisonnement autonome complet.
- Le serveur principal reste monolithique : `backend/server.py` compte 7 348 lignes à la date de référence.

## 5. Travaux encore incomplets ou non vérifiés

### Architecture cognitive

- Définir et tester un cycle cognitif explicite par tour qui orchestre perception, mémoire, apprentissage, raisonnement, décision, action et consolidation.
- Réduire la dépendance au monolithe `server.py` en séparant les responsabilités et en conservant un seul cerveau partagé.
- Rendre l'actualisation du contexte Live déterministe côté serveur, pas seulement dépendante d'un appel d'outil du modèle.
- Décider quelles réponses doivent créer une trace cognitive et quand lancer un audit métacognitif automatique. Aujourd'hui, l'enregistrement de traces et l'audit métacognitif ne sont pas exécutés automatiquement après chaque réponse.
- Distinguer davantage les rêves/ruminations simulés d'une réflexion autonome fondée sur des traces vérifiables.

### Multimodalité

- Tester manuellement les flux microphone, haut-parleur et caméra sur de vrais appareils.
- Vérifier et concevoir la persistance des observations visuelles reçues directement comme images vidéo dans Gemini Live ; la capture visuelle via l'API dédiée persiste déjà des observations, mais cela ne prouve pas que chaque frame Live est mémorisée.
- Vérifier le cycle complet : observation brute, provenance, description, rapprochement, validation humaine, apprentissage et réutilisation ultérieure.

### Stockage et reprise

- Le backend sélectionne SQLite par défaut si `CHAPPIE_STORAGE_BACKEND` n'est pas configuré. Le dépôt ne permet pas à lui seul de confirmer le backend réellement actif dans Render ; les variables de production n'ont pas été inspectées.
- Un garde-fou fail-closed exige désormais sur Render `CHAPPIE_SQLITE_PERSISTENCE_ACK=1` pour accepter SQLite, et `CHAPPIE_SQLITE_FRESH_START=1` uniquement pour une initialisation volontaire d'un fichier absent/vide. Cette seconde variable doit être retirée après le bootstrap. Le garde-fou ne remplace pas un disque réellement persistant ; il oblige l'opérateur à l'attester.
- La migration/coupure vers Turso et son rollback opérationnel ne sont pas considérés comme terminés.
- Une restauration E2E de test isolée existe, mais elle utilise un instantané synthétique. Il reste à restaurer **un artefact quotidien réel** dans une base Turso de récupération distincte et à comparer schéma, volumes, contraintes et empreintes.
- Aucun outil opérationnel général de restauration de production n'est livré. Le plan détaillé est dans `docs/operations/turso-logical-restore-design.md`.
- L'artefact GitHub observé a une rétention de 90 jours ; une seconde copie indépendante et durable n'est pas démontrée dans le dépôt.

### Exploitation et robot

- La boucle de maintenance est attachée au cycle de vie du serveur web ; elle ne constitue pas un worker indépendant garanti actif en permanence.
- Les performances, coûts Gemini, charge, comportement sous plusieurs instances et reprise après arrêt prolongé restent à mesurer.
- La construction du robot physique, ses actionneurs, sa sécurité électrique/mécanique et ses tests matériels ne sont pas commencés dans ce dépôt.

## 6. Garde-fous de livraison

- PR #133 reste ouverte et non fusionnée.
- Aucun déploiement Render n'a été effectué pendant cet audit.
- Aucune base Turso de production n'a été modifiée, réinitialisée ou utilisée comme cible de test.
- Les anciens PRs qui se recoupent ne doivent pas être fusionnés aveuglément : comparer chaque diff à la branche #133 avant de décider de les fermer ou de les intégrer.

## 7. Prochaine définition de « 100 % cerveau »

Le cerveau logiciel ne sera déclaré terminé que lorsque les critères suivants seront vérifiés par des tests automatisés et des essais manuels :
1. un seul cycle cognitif cohérent pour Chat, Live, vision et audition ;
2. mémoire durable, provenance, apprentissage progressif et rappel exact après redémarrage ;
3. fusion multimodale traçable, avec validation humaine avant promotion ;
4. raisonnement, doute, décisions et métacognition réellement reliés au cycle de réponse ;
5. rêves, objectifs, énergie et maintenance testés dans la durée ;
6. backend Turso opérationnel et procédure de sauvegarde/restauration de l'artefact réel démontrée ;
7. essais réels microphone/caméra, charge, coûts, erreurs et reprises ;
8. aucune régression dans l'ensemble de la suite de tests.

La partie robotique reste une étape distincte après ces critères.


## 8. Revalidation GitHub — 20 novembre 2026

Cette section complète le relevé historique ci-dessus sans effacer ses observations antérieures.

### Référence Git vérifiée

- Dépôt : `waksty22/waksty`.
- PR #133 : ouverte, non fusionnée, base `main`.
- Branche : `feat/safe-logical-restore-core`.
- Tête vérifiée : `637d9a888e725f0da42648ea4b14bc7daf5d56fa` (`Fail closed on ephemeral Render SQLite and honor configured DB path`).
- Le commit de référence `ab746a37...` cité dans les sections historiques n'est plus la tête actuelle.
- La PR affiche 409 commits et 77 fichiers modifiés au moment de cette vérification.

### CI observée sur la tête actuelle

Exécutions GitHub Actions du 19 novembre 2026, associées à la tête `637d9a888e725f0da42648ea4b14bc7daf5d56fa` :

- `quality` : **777 tests réussis** (`python -m pytest backend/tests -q`).
- `storage-tests` : **190 tests réussis**, un avertissement.
- `full-schema-e2e` : **réussi** ; cible isolée `chappie-test-isolated`, 41 tables, 45 lignes, archive chiffrée et vérifiée, reconnexion distante, clés étrangères et empreinte SHA-256 validées.

L'E2E a utilisé des données synthétiques sur une base de test dédiée. Il ne constitue pas une restauration d'une archive quotidienne réelle et ne prouve pas la persistance effective du service Render. Aucun accès en écriture à la base Turso de production n'est impliqué dans ces tests.

### Audit ciblé Chat / Live / perception

Inspection du code de la tête actuelle :

- Le chat reconstruit le contexte cognitif partagé via `get_identity_context` et `get_shared_brain_snapshot` à chaque requête.
- Gemini Live reçoit ce contexte au démarrage de session et partage les mêmes outils serveur ainsi que les mêmes fonctions de persistance des conversations et apprentissages lexicaux.
- L'actualisation Live en cours de session dépend encore de l'appel modèle à `get_shared_brain_state` ; elle n'est pas imposée par le serveur à chaque tour.
- Les transcriptions audio Live confirmées sont enregistrées comme observations sensorielles et contribuent au rapprochement temporel.
- Les images `video_frame` sont relayées à Gemini Live, mais ce parcours ne crée pas actuellement d'observation visuelle persistante équivalente. La continuité multimodale depuis les images Live n'est donc pas démontrée.
- Le constructeur `get_shared_brain_snapshot` agrège plusieurs systèmes persistés en une projection commune. Il ne constitue pas encore, à lui seul, un orchestrateur transactionnel unique du cycle perception → mémoire → apprentissage → raisonnement → décision → action → consolidation.
- `log_cognitive_trace` est utilisé dans des cas ciblés du chat ; `run_metacognitive_audit` reste déclenché par l'API dédiée et n'est pas exécuté automatiquement après chaque tour Chat ou Live.
- `backend/server.py` compte 7 393 lignes sur cette tête ; le monolithe reste un risque de maintenabilité et de couplage.

### Garde-fous et limites opérationnelles

- Le dernier commit ajoute un refus de démarrage SQLite sur Render sans acquittement explicite `CHAPPIE_SQLITE_PERSISTENCE_ACK=1`, et refuse un fichier absent/vide sauf bootstrap explicitement autorisé par `CHAPPIE_SQLITE_FRESH_START=1`.
- Ce garde-fou est une attestation opérateur : il ne prouve pas à lui seul qu'un disque persistant est réellement monté. Les variables et le backend actifs dans Render n'ont pas été inspectés dans cet audit.
- La migration/coupure Turso, le test d'une véritable archive quotidienne dans une base de récupération distincte, les essais réels microphone/caméra, les mesures de charge/coûts et la reprise opérationnelle restent à démontrer.
- La construction et la validation du robot physique ne sont pas commencées.

### Priorités d'acceptation restantes

1. Imposer côté serveur une actualisation cohérente du contexte partagé pour chaque tour Live, avec tests de non-obsolescence et de concurrence.
2. Persister les observations visuelles Live avec provenance, horodatage, référence de session et politique de rétention ; relier les observations audio/vidéo sans transformer une coïncidence en fait.
3. Définir un cycle cognitif commun explicite, idempotent et traçable pour Chat, Live, vision et audition.
4. Déclencher et tester la consolidation et la métacognition selon des règles explicites, sans créer de traces artificielles.
5. Ajouter des tests d'intégration multi-tour et multi-session, puis des tests de redémarrage indépendant pour les parcours audio/vidéo.
6. Restaurer une archive quotidienne réelle dans une base de récupération distincte et vérifier schéma, volumes, contraintes et empreintes.
7. Vérifier la persistance effective et les sauvegardes de l'environnement Render/Turso sans toucher à la production.
8. Effectuer les essais matériels et d'exploitation avant de déclarer le cerveau logiciel terminé.

**Conclusion de revalidation :** les trois workflows CI sont verts sur la tête actuelle. Cela valide les tests présents, pas l'achèvement de l'architecture cognitive. La PR reste non fusionnée ; aucun déploiement Render, aucune fusion et aucune modification de la mémoire de production n'ont été effectués pendant cette revalidation.
