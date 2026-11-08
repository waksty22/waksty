# V50.48 — Inventaire non destructif des données SQLite

## Objectif

Fournir un outil explicite qui permet de comparer l'état d'une base SQLite sans afficher les conversations, souvenirs, prompts, données émotionnelles ou valeurs de colonnes.

## Utilisation

Sur une copie ou un chemin de base SQLite identifié avec certitude :

```bash
python scripts/inspect_persistence_inventory.py --database /chemin/exact/chappie_v16.sqlite3
```

Pour enregistrer le rapport :

```bash
python scripts/inspect_persistence_inventory.py --database /chemin/exact/chappie_v16.sqlite3 --output /tmp/chappie-inventory.json
```

Le chemin est obligatoire : le script ne devine pas la base active, ne lit pas les variables d'environnement et ne se connecte pas à Turso.

## Garanties

- Ouverture SQLite avec `mode=ro`, puis `PRAGMA query_only=ON`.
- Une transaction de lecture cohérente pendant l'inventaire.
- Vérification `integrity_check`.
- Inventaire des objets de schéma et empreinte SHA-256 du schéma.
- Nombre de lignes par table et empreinte SHA-256 des contenus par table.
- Valeurs textuelles et données personnelles jamais écrites dans le rapport.
- Pour les BLOB, seule la longueur et une empreinte du contenu sont utilisées pour calculer l'empreinte de ligne.
- Aucune création de table, migration, écriture, suppression ou commande de réparation.

## Limites

- Cet outil inspecte un fichier SQLite local uniquement. Il ne vérifie pas la base distante Turso.
- Une empreinte ne permet pas de reconstituer les données ; elle permet seulement de comparer deux états.
- L'intégrité d'un fichier et la cohérence de ses contenus ne prouvent pas sa durabilité après perte d'une instance Render.
- Pour comparer la production et une sauvegarde, utiliser les mêmes versions de l'outil et des instantanés cohérents.
- Ne pas exécuter sur un chemin supposé : confirmer le chemin exact via le diagnostic read-only déjà disponible.
- Ne pas envoyer un rapport contenant des chemins internes ou métadonnées sensibles dans un dépôt public.

## Sécurité

Cette version ne contacte ni Render ni Turso, ne lit aucun secret, et ne modifie pas la configuration du service. L'inventaire d'une base de production doit rester une opération distincte et explicitement autorisée.
