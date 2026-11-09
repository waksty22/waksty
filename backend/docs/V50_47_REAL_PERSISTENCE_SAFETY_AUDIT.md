# V50.47 — Audit de la persistance réelle Render / Turso

Date de l'audit : 2026-11-08  
Périmètre : lecture du code de la branche V50.46, diagnostics d'exploitation déjà fournis et drills de restauration isolés.  
Nature : audit en lecture seule. Aucun accès de production, aucune écriture distante, migration, fusion ou livraison.

## Conclusion exécutive

**La continuité cognitive fonctionne sur un même fichier SQLite lors d'une fermeture/réouverture contrôlée, mais la durabilité de ce fichier en production n'est pas garantie.** Le diagnostic Render fourni montre que la base active se trouve sur le système de fichiers racine de type overlay, et non sur un volume persistant monté. Le backend applicatif reste SQLite. Turso n'est pas activé pour les connexions applicatives.

Il ne faut donc pas présenter Chappie comme ayant déjà une mémoire durable garantie après redéploiement ou remplacement de l'instance.

## 1. Chemin réellement utilisé par l'application

Constats dans le code :

- backend/server.py construit BASE_DIR depuis CHAPPIE_DATA_DIR, avec ./chappie_data comme valeur par défaut.
- DB_PATH est BASE_DIR / chappie_v16.sqlite3.
- db_connection() réutilise ce chemin canonique et appelle open_sqlite_application_connection().
- open_sqlite_application_connection() refuse explicitement tout backend autre que SQLite.
- Le serveur ne passe donc pas directement par le connecteur générique open_storage_connection().

Diagnostic d'exploitation communiqué le 8 novembre 2026 :

| Indicateur | Valeur observée |
|---|---|
| Répertoire configuré | /opt/render/project/src/backend/chappie_data |
| Fichier ouvert | /opt/render/project/src/backend/chappie_data/chappie_v16.sqlite3 |
| CHAPPIE_DATA_DIR défini | Non |
| Point de montage | / |
| Système de fichiers | overlay |
| Système racine | Oui |
| Sous /var/data | Non |
| Mode SQLite | wal |
| Vérification d'intégrité | OK |

**Interprétation :** le fichier actif est dans le système de fichiers de l'instance Render. Le mode WAL et un integrity_check réussi prouvent que SQLite peut lire une base cohérente à cet instant ; ils ne prouvent pas que le fichier survivra à un redéploiement, à un remplacement d'instance ou à une perte du système de fichiers.

Le dépôt inspecté ne contient pas de manifeste Render de montage de disque à vérifier. La configuration effective du service Render reste une configuration externe au dépôt.

## 2. Turso : prêt pour expérimentation, pas pour bascule

Constats dans le code :

- Le connecteur libSQL et son adaptateur existent.
- Le serveur de production reste volontairement bloqué sur SQLite.
- L'adaptateur libSQL ne constitue pas à lui seul une preuve de compatibilité de l'ensemble du backend.
- Le démarrage applicatif utilise des constructions SQLite, dont PRAGMA journal_mode=WAL et executescript.
- Les sauvegardes locales backend/storage/backup.py utilisent les API de fichiers SQLite ; elles ne sauvegardent pas directement une base distante Turso.
- Les diagnostics de chemin, WAL/SHM et points de montage sont spécifiques au stockage local.

Les contrats et matrices V50.41–V50.43 ont déjà identifié les différences DB-API, les métadonnées de curseur, les transactions, les instructions SQL et les migrations à valider. Tant que le test de bout en bout sur une base Turso isolée ne couvre pas toutes les opérations réelles, la bascule doit rester interdite.

## 3. Outbox et mémoire après redémarrage

La table conversation_finalization_outbox est créée dans la même base que les conversations. Elle protège les travaux de finalisation après validation d'un tour et permet une reprise au démarrage.

C'est une bonne garantie transactionnelle **à l'intérieur du stockage sélectionné**. Elle ne protège pas contre la disparition du fichier SQLite qui contient simultanément les conversations, les apprentissages et l'outbox.

Les tests V50.46 vérifient une fermeture/réouverture d'un fichier temporaire SQLite. Ils ne simulent pas la perte du disque Render ni une reprise depuis Turso.

## 4. État des sauvegardes et drills observés

Les drills isolés ont réussi techniquement (déchiffrement, restauration vers une nouvelle base temporaire, fermeture/réouverture, intégrité et clés étrangères). Mais les contenus examinés étaient incomplets :

- Sauvegarde Render inspectée : 41 tables, 0 ligne.
- Sauvegarde Turso inspectée : 13 tables, 5 lignes au total ; les tables de conversations, mémoires, rêves, événements d'humeur, objectifs et compétences étaient vides.

**Un drill réussi prouve que le mécanisme sait restaurer l'artefact testé. Il ne prouve pas que cet artefact contient les souvenirs attendus.** Il faut d'abord alimenter la source réelle et vérifier les empreintes/contenus avant de considérer une sauvegarde comme protectrice de l'histoire de Chappie.

## 5. Bloqueurs avant toute affirmation de mémoire durable

| Priorité | Bloqueur | Preuve nécessaire |
|---|---|---|
| Critique | Base active sur overlay | Stockage persistant réellement monté, ou bascule Turso complète validée |
| Critique | Sauvegardes examinées presque vides | Conversations et apprentissages réels présents dans l'artefact, nombres et empreintes concordants |
| Critique | Turso non activé dans le serveur | Suite complète sur base distante isolée : schéma, transactions, SQL, erreurs, concurrence, redémarrage |
| Haute | Absence de preuve après remplacement d'instance | Test contrôlé de redéploiement/remplacement, puis comparaison des données |
| Haute | Restauration pas encore éprouvée sur un jeu de données représentatif | Restauration isolée, vérification des contenus, reprise Chat et Live |

## 6. Plan de validation sans risque

1. Conserver SQLite en production tant que le stockage durable cible n'a pas passé les tests.
2. Faire un inventaire non destructif des données réelles dans la source active et dans Turso : schéma, tables, lignes et empreintes par table.
3. Préparer une base Turso de staging distincte ; ne pas utiliser la base de production comme banc d'essai.
4. Compléter l'adaptateur et exécuter toute la suite backend contre cette base isolée.
5. Tester export, restauration, répétition d'import, interruption/reprise et cohérence des transactions.
6. Effectuer un test de redémarrage/redéploiement avec données synthétiques et comparer les empreintes avant/après.
7. Préparer une procédure de bascule et de retour arrière, puis demander une approbation explicite avant toute opération de production.

## 7. Garde-fous de cette version

- Aucun changement de code runtime.
- Aucun changement de variable Render ou de secret.
- Aucun accès en écriture à Turso.
- Aucune migration, réinitialisation, fusion ou livraison.
- Tests statiques destinés à empêcher une activation accidentelle de Turso et à garder les limites visibles.

## Verdict

**V50.47 est un audit de sécurité de persistance, pas une activation de mémoire distante.** Le prochain vrai jalon est de prouver que les données réelles de Chappie sont présentes dans une source durable et qu'elles survivent à une restauration et à un redémarrage contrôlé.
