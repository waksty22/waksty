# V50.49 — Inventaire réel authentifié en lecture seule

## But
Permettre au propriétaire de consulter l'inventaire de la base SQLite active depuis l'interface Chappie, sans accès Render Shell et sans révéler le contenu privé.

## Utilisation
1. Ouvrir l'onglet **Rêves & Pensées / Mémoire** dans Chappie.
2. Vérifier que le champ du jeton API existant est renseigné.
3. Cliquer sur **Lancer l'inventaire**.
4. Lire le rapport dans le panneau dédié.

Aucun jeton n'est demandé à ChatGPT, affiché dans le rapport, transmis à un service tiers ou modifié par cette fonctionnalité. L'interface réutilise le champ d'authentification déjà présent dans la page.

## Sécurité
- Endpoint GET `/api/system/persistence-inventory`.
- Protégé par la dépendance existante `require_auth` et le Bearer token déjà configuré.
- Le chemin inspecté est strictement le `DB_PATH` actif du serveur ; aucun chemin fourni par le navigateur.
- Ouverture SQLite `mode=ro`, `PRAGMA query_only=ON`, transaction de lecture.
- Aucune migration, aucun INSERT/UPDATE/DELETE, aucun fichier de rapport écrit.
- Retour limité aux noms de tables, volumes, intégrité et empreintes SHA-256.
- Aucun texte de conversation, souvenir, prompt, valeur de colonne, secret, chemin absolu ou donnée émotionnelle détaillée.
- Le calcul SQLite s'exécute dans un thread de travail FastAPI, pas dans la boucle asynchrone.
- Erreur générique HTTP 503 si la base ne peut pas être inspectée.

## Limites
- Cette route inspecte le fichier SQLite local actif de Render ; elle ne lit pas Turso et ne prouve pas la durabilité du disque Render.
- Le diagnostic peut prendre du temps sur une base volumineuse, car il compte et empreinte toutes les lignes.
- Une empreinte permet de comparer des états, pas de récupérer des données.
- La présence d'un rapport correct ne signifie pas que les sauvegardes sont complètes.
- Aucun endpoint public ou accès sans authentification n'est créé.
