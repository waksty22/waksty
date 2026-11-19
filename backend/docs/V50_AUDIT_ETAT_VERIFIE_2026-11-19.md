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
