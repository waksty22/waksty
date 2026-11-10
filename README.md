# Chappie

Compagnon conversationnel expérimental avec apprentissage progressif et mémoire logicielle partagée entre le chat écrit et Gemini Live.

> Les émotions, les rêves et les états cognitifs affichés sont des simulations logicielles. Ils ne constituent pas une preuve de conscience.

## Architecture

Le backend FastAPI se trouve dans `backend/`. Les principaux domaines sont :

- `cognition/` : moteur cognitif, raisonnement, compétences et développement ;
- `memory/` : mémoire épisodique, autobiographique et connaissances acquises ;
- `learning/` : vocabulaire, perception, objets, causalité et imitation ;
- `world/` : modèle du monde et mémoire spatiale ;
- `storage/` : sélection du stockage, adaptateur libSQL, audits et migration ;
- `static/` : tableau de bord mobile/ordinateur et clients audio/vidéo.

Le chat et Gemini Live enregistrent les échanges dans le même stockage applicatif. Les tours Live interrompus sont conservés comme transcriptions partielles lorsqu'une transcription confirmée est disponible.

## Démarrage local

Python 3.11 est la version de référence (voir `.python-version`).

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
cd backend
uvicorn server:app --host 0.0.0.0 --port 8000
```

Configurer les secrets dans `backend/.env` ou dans l'environnement d'exécution, jamais dans Git :

- `CHAPPIE_API_TOKEN` : jeton d'accès fort et privé ;
- `GEMINI_API_KEY` : clé Google Gemini ;
- `CHAPPIE_OWNER_ID` : identifiant local autorisé ;
- `CHAPPIE_STORAGE_BACKEND` : `sqlite` par défaut ou `turso` après une migration vérifiée ;
- `TURSO_DATABASE_URL` et `TURSO_AUTH_TOKEN` : nécessaires seulement pour Turso ;
- `CHAPPIE_CORS_ORIGINS` : origines externes explicitement autorisées, séparées par des virgules. Par défaut, aucune origine externe n'est autorisée.

Le tableau de bord est servi par le même serveur ; l'accès same-origin ne nécessite pas CORS.

## Stockage et continuité

- SQLite reste le backend par défaut tant que le cutover Turso n'a pas été explicitement préparé et validé.
- Sur un hébergement à disque éphémère, SQLite ne garantit pas la conservation des données après redéploiement ou remplacement d'instance. Utiliser un stockage persistant ou terminer une migration Turso vérifiée avant de compter sur une mémoire durable.
- Ne jamais basculer le backend en changeant uniquement une variable d'environnement. Le marqueur de migration, la compatibilité du schéma, les sauvegardes et les contrôles de contenu doivent être validés.
- Les aperçus et audits de migration sont en lecture seule. Une prévisualisation prête ne déclenche pas la migration.
- Les sauvegardes doivent être téléchargées et conservées hors de l'instance d'hébergement.

## Sécurité

- Les routes API sont protégées par Bearer token.
- Le navigateur ne conserve plus le jeton dans `localStorage` ni dans une variable globale persistante ; il faut le ressaisir après rechargement.
- Les tickets WebSocket sont à usage unique et de courte durée ; la clé Gemini ne doit jamais être placée dans l'URL du navigateur.
- CORS est désactivé pour les origines externes par défaut. Configurer `CHAPPIE_CORS_ORIGINS` uniquement si un client externe est nécessaire.
- Les corps HTTP sont limités, y compris lorsqu'ils sont envoyés en plusieurs blocs sans `Content-Length`.
- Une réinitialisation exige une confirmation côté serveur et ne cible que le backend actuellement actif. L'autre base n'est pas modifiée.
- Les fichiers SQLite, WAL, SHM, bases locales, journaux et secrets ne doivent jamais être commités.

## Tests

Depuis la racine :

```bash
python -m compileall -q backend
python -m pytest backend/tests -q
```

GitHub Actions exécute la compilation Python, la vérification syntaxique JavaScript et les tests backend sur les pull requests vers `main`.

## Déploiement

La révision de durcissement V50.60 est livrée par une pull request et doit passer la CI avant toute fusion. Les numéros affichés par l'API et le tableau de bord sont centralisés.

Le service Render doit utiliser Python 3.11 et installer `backend/requirements.txt`. Les variables secrètes se configurent dans Render, pas dans les fichiers versionnés.

Avant toute mise en production, vérifier les journaux de démarrage, le backend réellement actif, les diagnostics de persistance et les sauvegardes. Une fusion GitHub ne prouve pas que la mémoire a été migrée ni que le nouveau backend est actif.
