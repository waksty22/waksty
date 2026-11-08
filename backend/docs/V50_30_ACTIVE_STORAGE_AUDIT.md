# V50.30 — Audit du stockage réellement actif

**Statut : audit et garde-fous uniquement. Aucun changement de configuration, aucune écriture de production, aucun déploiement.**

## Conclusion confirmée dans le code

Au commit de départ de cette étape, `backend/server.py` définit :

- `BASE_DIR` à partir de `CHAPPIE_DATA_DIR`, avec le repli `./chappie_data` ;
- `DB_PATH = BASE_DIR / "chappie_v16.sqlite3"` ;
- `db_connection()` appelle directement `sqlite3.connect(DB_PATH)`.

La fabrique `backend/storage/connection_factory.py` sait ouvrir SQLite ou libSQL/Turso, mais le serveur ne l'utilise pas pour ses connexions métier. La présence de `TURSO_DATABASE_URL` et `TURSO_AUTH_TOKEN` ne prouve donc pas que Turso est le stockage actif.

## Résultats des exercices de restauration isolée

Les rapports fournis le 8 novembre 2026 confirment que les deux artefacts peuvent être déchiffrés, restaurés dans un nouveau fichier temporaire, fermés puis rouverts avec intégrité SQLite et empreintes identiques.

| Source | Tables | Lignes | Détail |
|---|---:|---:|---|
| Sauvegarde Render | 41 | 0 | Toutes les tables vides |
| Sauvegarde Turso | 13 | 5 | Une ligne dans `emotional_state`, `journal`, `maintenance_state`, `relationships`, `voice_profiles` |

Ces résultats valident le mécanisme de restauration des artefacts testés, **pas** la complétude des données, la synchronisation entre bases, ni la persistance du disque Render. Les sauvegardes ne contiennent actuellement aucune conversation, aucun souvenir et aucun apprentissage comptabilisé.

## Ce qui reste à vérifier sur l'instance active

1. Appeler le diagnostic authentifié du chemin SQLite réellement ouvert, sans exposer de secrets ni de contenu de mémoire.
2. Vérifier dans le tableau de bord Render le disque persistant réellement attaché au service, son point de montage et le chemin configuré. Le système de fichiers racine `overlay` observé précédemment n'est pas une preuve de persistance.
3. Comparer le chemin réellement ouvert par le serveur avec le chemin situé sous le point de montage du disque persistant.
4. Après autorisation d'un test contrôlé, écrire un marqueur non personnel dans une base de test isolée, fermer/réouvrir puis redémarrer le service et vérifier que le marqueur persiste. Ne pas effectuer ce test sur la base métier réelle.
5. Tant que le disque persistant n'est pas démontré, ne pas considérer SQLite local comme durable et ne pas lancer de migration.

## Garde-fous

- SQLite reste explicitement le backend actif jusqu'à une décision de bascule séparée.
- Ne pas activer `CHAPPIE_STORAGE_BACKEND=turso` à ce stade.
- Ne pas modifier `CHAPPIE_API_TOKEN` ni demander à l'utilisateur de communiquer un secret.
- Ne pas lancer de reset, de copie de données, de migration, de changement de variables Render ou de déploiement dans cette étape.
- Préserver les cinq lignes Turso existantes ; aucune table ni ligne ne doit être remplacée par une base vide.
- Une sauvegarde valide n'est considérée comme une sauvegarde utile que si elle contient les données attendues et si sa restauration a été testée.

## Critères de sortie V50.30

- [x] Confirmer dans le code le backend et la connexion utilisés par le serveur.
- [x] Ajouter un test de non-régression qui bloque un basculement implicite vers Turso.
- [x] Documenter les résultats réels des deux restaurations.
- [ ] Vérifier le disque persistant Render et l'alignement du chemin actif.
- [ ] Démontrer la persistance après redémarrage contrôlé sur un environnement de test.
- [ ] Concevoir ensuite seulement la migration complète et idempotente des données.
