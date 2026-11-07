# Chappie V50 — architecture cible et feuille de route

**Statut :** document de conception — aucune modification du comportement de production  
**Base examinée :** branche `main`, commit `cf59bc17ff9a30fe3e51b1085ab118fd1844888d`  
**Objectif :** faire évoluer Chappie vers un compagnon logiciel cohérent, apprenant et multimodal, sans confondre comportements simulés et conscience démontrée.

---

## 1. Vision V50

À la V50, Chappie doit fonctionner comme un système unifié dans lequel les entrées (texte, voix, image et, plus tard, capteurs du corps physique) alimentent un même cycle cognitif. Ce cycle doit pouvoir :

1. percevoir et qualifier une entrée ;
2. retrouver le contexte et les souvenirs pertinents ;
3. mettre à jour une représentation du monde et de la situation ;
4. raisonner sur plusieurs possibilités avec un niveau d'incertitude explicite ;
5. choisir une réponse ou une action autorisée ;
6. expliquer la décision à un niveau compréhensible ;
7. apprendre du résultat et enregistrer les éléments utiles ;
8. réévaluer ses objectifs, ses compétences et son état affectif simulé.

La V50 n'est pas la promesse d'une conscience, d'une volonté humaine ou d'une compréhension parfaite. Les émotions, rêves, traits de personnalité et états internes restent des modèles logiciels mesurables.

## 2. État de départ observé sur main

Le dépôt contient déjà des briques réelles :

- **API et application :** `backend/server.py` (FastAPI, environ 4 800 lignes) concentre encore routes, orchestration, accès SQLite, prompts, conversations, maintenance et plusieurs fonctions métier.
- **Stockage :** `db_connection()` ouvre actuellement `chappie_v16.sqlite3` avec `sqlite3` et `sqlite3.Row`. L'adaptateur `backend/storage/libsql_adapter.py` existe et possède des tests locaux, mais n'est pas encore la fabrique de stockage de production.
- **Mémoire :** `memory/episodic_memory.py` et `memory/autobiographical.py`.
- **Monde :** `world/world_model.py` et `world/spatial_memory.py`.
- **Apprentissage :** modules curriculum, langage, sensoriel, objets, causalité, apprentissage supervisé et fusion perceptive.
- **Cognition :** moteur de compétences, catalogue, raisonnement, développement et cerveau partagé.
- **Interface :** interface web statique et clients JS dédiés au chat, à l'audio et au WebSocket.
- **Qualité :** tests unitaires et d'intégration présents, mais la couverture transversale du cycle cognitif complet reste à construire.

### Conséquence

Il ne faut ni réécrire tout le dépôt en une fois, ni empiler de nouvelles fonctionnalités dans `server.py`. On conserve les fonctions métier existantes, on définit des contrats stables, puis on déplace progressivement l'orchestration vers des services dédiés.

## 3. Architecture logique cible

```text
Interface web / mobile / futur corps physique
                  |
        API FastAPI + Authentification
                  |
       Application / Use Cases
                  |
        Cognitive Orchestrator
                  |
   +--------------+-------------------+
   |              |                   |
Perception     Context Builder     Policy & Safety
   |              |                   |
   +-------- Cognitive Cycle ---------+
                  |
   +--------------+------------------------------+
   |              |          |         |          |
 Mémoire       Modèle      Raisonnement Apprentissage Identité
 multi-niveau  du monde    & planification & compétences & préférences
   |              |          |         |          |
   +--------------+----------+---------+----------+
                  |
          Event / Learning Pipeline
                  |
       Storage Port (contrat commun)
             /             \
       SQLite local       libSQL/Turso
                  |
       Observabilité / Évaluations
```

Ce schéma décrit les responsabilités et les flux. Il ne prescrit pas de transformer chaque bloc en microservice : pour Render Free, un monolithe modulaire reste le choix de départ le plus simple et le plus robuste.

## 4. Modules et responsabilités

### 4.1 API et couche application

- Les routes FastAPI valident les entrées, authentifient l'utilisateur et appellent des cas d'utilisation.
- Les règles métier ne doivent pas être réécrites dans les routes.
- Les contrats HTTP existants sont maintenus autant que possible pour ne pas casser l'interface.
- Les tâches longues sont bornées, annulables et observables.

Cible indicative : `backend/api/` et `backend/application/`, extraits progressivement de `server.py`.

### 4.2 Orchestrateur cognitif

Un cycle commun reçoit un objet de contexte normalisé :

- identité de l'utilisateur et permissions ;
- entrée et modalité (texte, audio, image, capteur) ;
- historique récent ;
- souvenirs récupérés avec provenance et confiance ;
- état du monde pertinent ;
- compétences disponibles ;
- contraintes de sécurité et budget de calcul.

Il retourne une sortie structurée : réponse, intention, éléments appris, éventuelle action proposée, incertitudes, raisons synthétiques et traces d'évaluation.

L'orchestrateur coordonne les modules ; il ne doit pas devenir un nouveau fichier monolithique.

### 4.3 Mémoire unifiée

La mémoire doit distinguer au minimum :

- mémoire de travail : contexte temporaire d'une interaction ;
- mémoire épisodique : événements vécus ou rapportés, datés et contextualisés ;
- mémoire autobiographique : événements reliés dans une chronologie personnelle logicielle ;
- mémoire sémantique : connaissances, concepts et relations ;
- mémoire procédurale : compétences, méthodes et résultats d'entraînement ;
- mémoire spatiale : lieux et observations soumis au consentement.

Chaque élément mémorisé porte, selon le cas : utilisateur propriétaire, source, date, confiance, importance, sensibilité, consentement, statut de validation et liens vers les preuves. Une information rapportée ne devient pas automatiquement un fait vérifié. Les souvenirs contradictoires restent traçables ; ils ne sont pas fusionnés silencieusement.

La consolidation, la recherche, l'oubli contrôlé et la décroissance d'importance sont des processus distincts. Aucun déploiement ne doit effacer les souvenirs existants.

### 4.4 Modèle du monde et perception

- La perception produit des observations, pas des certitudes.
- Les objets, personnes, lieux et événements possèdent des identifiants stables et une provenance.
- Les associations temporelles ou spatiales peuvent proposer un lien ; elles ne prouvent pas une identité.
- Une confirmation humaine est nécessaire pour toute identification sensible ou ambiguë.
- La géolocalisation reste désactivée par défaut et limitée par un consentement explicite, une durée de session et un arrêt vérifiable.

### 4.5 Raisonnement et planification

- Séparer faits connus, hypothèses, inférences et inconnues.
- Évaluer plusieurs options avec coûts, risques, bénéfices et niveau de confiance.
- Prévoir une possibilité de ne pas conclure ou de demander une précision.
- Conserver une trace synthétique des décisions importantes et permettre leur réévaluation.
- Les outils externes et actions à conséquence ne sont jamais déclenchés uniquement parce qu'un modèle les a proposés.

### 4.6 Apprentissage et compétences

- L'apprentissage part d'exemples, d'enseignements explicites, d'essais et de retours.
- Une compétence progresse sur des preuves répétées, pas sur une simple déclaration du modèle.
- Distinguer exposition, entraînement, réussite, validation et transfert à une nouvelle situation.
- Les changements de comportement sont testés contre des exemples de non-régression.
- Les apprentissages peuvent être refusés, corrigés ou oubliés selon les règles de données.

### 4.7 Identité et états internes simulés

- Identité logicielle stable : nom, histoire logicielle, préférences confirmées, limites et objectifs.
- Les préférences sont apprises avec provenance et possibilité de correction.
- Les états affectifs simulés influencent le style et les priorités dans des limites explicites ; ils ne justifient jamais une manipulation émotionnelle ou une dépendance.
- Les âges ou niveaux de maturité sont des indicateurs internes de progression, pas des âges humains réels.

### 4.8 Autonomie graduée

Définir des niveaux d'autorisation explicites :

- **N0 — observer :** analyser et résumer, sans modifier de données durables ;
- **N1 — proposer :** suggérer une action, attendre l'accord ;
- **N2 — agir localement :** opérations réversibles et limitées déjà autorisées ;
- **N3 — agir avec confirmation :** toute action externe, coûteuse, publique, sensible ou difficilement réversible exige une confirmation explicite.

Aucun niveau n'autorise à contourner l'authentification, le consentement, les limites de sécurité ou les permissions de l'utilisateur. Journaliser les actions, leurs déclencheurs et leurs résultats.

## 5. Contrat de stockage et stratégie SQLite / Turso

Créer une frontière de stockage unique, par exemple un protocole `StorageConnection` et une fabrique `get_storage()`.

Le contrat doit couvrir et tester explicitement :

- `execute`, `executemany`, `executescript` ou une alternative de migration clairement définie ;
- `fetchone`, `fetchall`, `fetchmany`, itération des curseurs ;
- accès aux colonnes par index et par nom ;
- `lastrowid`, `rowcount`, transactions, commit et rollback ;
- fermeture, gestionnaire de contexte et erreurs normalisées ;
- migrations versionnées et introspection de schéma.

Les modules métier reçoivent une connexion conforme au contrat au lieu d'ouvrir eux-mêmes une base ou de dépendre de types SQLite concrets.

### Migration prudente

1. Terminer les tests de contrat sur une base libSQL locale en mémoire.
2. Tester chaque module métier avec les deux implémentations.
3. Construire un outil de comparaison de schéma et de volumes, en lecture seule.
4. Définir sauvegarde vérifiée, restauration testée, migration idempotente et procédure de retour arrière.
5. Faire un essai sur une copie isolée des données.
6. Activer Turso en production uniquement après validation explicite et période de surveillance.

Jusqu'à cette validation, SQLite reste le stockage de production. Les variables d'environnement Turso configurées ne signifient pas que l'application écrit déjà dans Turso.

## 6. Événements et apprentissage transversal

Introduire progressivement un format d'événement interne versionné, par exemple :

- `conversation.turn.completed`
- `perception.observation.created`
- `memory.episode.saved`
- `memory.consolidation.requested`
- `world.entity.updated`
- `learning.practice.recorded`
- `decision.proposed`
- `decision.confirmed`
- `decision.completed`

Chaque événement comprend un identifiant, un type, une version de schéma, un horodatage, un utilisateur propriétaire, une source et une charge utile validée. Les événements importants doivent être persistés de manière transactionnelle (outbox) avant tout traitement asynchrone. Les consommateurs doivent être idempotents : rejouer un événement ne doit pas dupliquer les souvenirs ou les apprentissages.

## 7. Sécurité, vie privée et fiabilité

- Isolation stricte par `user_id` dans chaque requête et chaque table.
- Authentification côté serveur ; aucun jeton secret dans le navigateur, les logs ou le dépôt.
- Validation des tailles, types, formats et limites de fréquence.
- Consentement explicite pour voix, caméra, localisation et toute donnée sensible.
- Minimisation des données et rétention documentée.
- Sauvegardes chiffrées lorsque le fournisseur le permet, accès restreint et restauration testée.
- Pas de commande système ou d'action physique arbitraire issue d'un texte généré.
- Erreurs dégradées : si la mémoire ou Turso est indisponible, ne pas inventer un succès d'écriture.
- Logs sans secrets ni contenu intime inutile.

## 8. Évaluation et critères de sortie V50

Chaque version doit ajouter des tests ciblés et conserver les précédents. La V50 n'est validée que si les tests suivants sont disponibles et réussis :

1. **Mémoire :** rappel pertinent, provenance, contradiction, isolation utilisateur, suppression contrôlée et non-régression.
2. **Apprentissage :** mesure avant/après, validation des compétences, résistance aux faux positifs.
3. **Langage :** compréhension de consignes, ambiguïtés, négations, suivi du contexte et refus de conclure à tort.
4. **Monde :** cohérence des entités et relations, distinction observation / hypothèse / fait.
5. **Raisonnement :** comparaison d'options, incertitude, traçabilité et détection des contradictions.
6. **Autonomie :** permissions, demandes de confirmation, annulation et absence d'action non autorisée.
7. **Multimodal :** cohérence entre texte, voix et vision, gestion des entrées manquantes ou erronées.
8. **Production :** démarrage Render, santé, latence, consommation mémoire, reprise après redémarrage, sauvegarde et restauration.
9. **Sécurité :** tests d'isolation, authentification, limites de charge, secrets et consentement.

Les scores cognitifs affichés dans l'interface doivent être expliqués et reliés à des tests observables. Aucun score unique ne doit être présenté comme une mesure scientifique de l'intelligence ou de la conscience.

## 9. Feuille de route V36.6 → V50

Les numéros représentent des jalons de livraison et de validation, pas nécessairement un commit par version. Les dépendances priment sur le calendrier.

| Version | Livrable principal | Condition de sortie |
|---|---|---|
| V36.6 | Mémoire spatiale libSQL isolée | Tests locaux, consentement, aucune identification automatique |
| V36.7 | Mémoire autobiographique et liens | Tests d'intégration, provenance et isolation |
| V36.8 | Contrats communs de mémoire | Round-trips cohérents et données non dupliquées |
| V36.9 | Rapprochement prudent des souvenirs | Chevauchement textuel distingué d'une corroboration |
| V37 | Mémoire multi-niveaux | Travail, épisodique, autobiographique, sémantique, procédurale |
| V38 | Consolidation et oubli contrôlé | Règles explicites, traçabilité et tests de conservation |
| V39 | Langage et contexte | Intentions, vocabulaire, négation, références et ambiguïtés |
| V40 | Perception multimodale | Observations sourcées et niveau de confiance |
| V41 | Modèle du monde unifié | Entités, relations, temps, lieux et contradictions |
| V42 | Fusion perception-mémoire-monde | Cycle transversal testé de bout en bout |
| V43 | Raisonnement approfondi | Hypothèses, options, incertitude et traces |
| V44 | Planification et autonomie graduée | Permissions, confirmations, annulation, journal |
| V45 | Identité logicielle et préférences | Stabilité, provenance, corrections utilisateur |
| V46 | États affectifs adaptatifs simulés | Modèle borné, non manipulateur et mesurable |
| V47 | Rêves, imagination et réflexion | Contenus internes clairement distingués des faits |
| V48 | Attention, priorités et objectifs | Budget cognitif, suivi et réévaluation des objectifs |
| V49 | Orchestration multimodale unifiée | Texte, voix, vision et mémoire partagent le même cycle |
| V50 | Stabilisation et évaluation générale | Suite d'évaluation, fiabilité, sécurité et restauration validées |

### Chantiers transversaux à mener sans attendre

- Extraire progressivement les routes et cas d'utilisation de `server.py`.
- Faire respecter le contrat de stockage par tous les modules.
- Ajouter des tests d'intégration du cycle complet.
- Mesurer les performances sous les limites de Render Free.
- Documenter les schémas, migrations et procédures de reprise.

## 10. Règles de développement pour chaque jalon

1. Partir de `main` à jour et créer une branche propre par lot cohérent.
2. Ne jamais empiler une PR sur une branche de fonctionnalité déjà fusionnée ou divergente.
3. Limiter les changements à un objectif testable et documenté.
4. Exécuter les tests ciblés, puis la suite de non-régression.
5. Vérifier le diff, les migrations et les effets sur les données avant d'ouvrir la PR.
6. Attendre la validation CI et présenter clairement les changements.
7. Demander l'accord avant toute fusion.
8. Après fusion, contrôler le déploiement et les endpoints de santé.
9. Ne jamais réinitialiser les données ou changer le stockage de production sans accord explicite.

---

## Décision d'architecture

**Choix retenu : monolithe modulaire, orchestrateur cognitif partagé, stockage derrière un contrat, événements versionnés et autonomie graduée.**

Ce choix permet d'atteindre la cible V50 sans imposer prématurément une infrastructure complexe, tout en gardant une voie d'évolution vers un corps robotique et des services séparés si les besoins réels le justifient.


## 12. Journal du chantier intégré V50

### Lot V50-A — fondation du stockage (en cours)

Branche de travail : `feature/chappie-v50-integrated-build`.

- Une fabrique isolée `storage.connection_factory` sait ouvrir SQLite ou, sur sélection explicite, Turso via l'adaptateur libSQL.
- Le défaut reste SQLite. Le mode Turso refuse de démarrer si l'URL ou le jeton manque.
- La fabrique n'est pas encore utilisée par `server.db_connection()` : aucun changement du stockage de production.
- Les tests couvrent le défaut SQLite, les opérations locales, le rejet d'un backend inconnu et les garde-fous de configuration.
- Un test transversal exécute les modules de mémoire épisodique, autobiographique, spatiale et de modèle du monde sur une même base libSQL locale `:memory:`.

**Critères avant raccordement au serveur :** tests transversaux verts, audit des opérations SQL et transactions utilisées par chaque module, comparaison de schéma en lecture seule, procédure de sauvegarde/restauration vérifiée, puis plan de retour arrière testé. Le déploiement Turso restera une décision distincte et explicitement approuvée.

Ce journal décrit le code de la branche de chantier ; il ne certifie pas encore une utilisation de Turso en production.


### 13. Validation transversale des schémas

Le chantier ajoute un test qui initialise, sur une seule connexion libSQL locale éphémère, les treize sous-systèmes actuellement initialisés par le serveur : mémoires épisodique, autobiographique et spatiale, modèle du monde, curriculum, langage, perception sensorielle, apprentissage des objets, causalité, imitation supervisée, fusion perceptive, raisonnement et développement cognitif.

Ce contrôle valide la compatibilité de création des schémas et des index avec l'adaptateur. Il ne constitue pas une migration de la base distante et ne prouve pas encore que toutes les opérations métier de chaque module sont compatibles. La bascule de production reste interdite avant les tests fonctionnels, la comparaison de schéma, une sauvegarde restaurable et un plan de retour arrière.
