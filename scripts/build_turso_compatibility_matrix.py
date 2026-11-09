#!/usr/bin/env python3
"""Build a reviewable SQLite-to-Turso compatibility matrix from V50.42 findings."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from audit_sqlite_usage import build_report

RULES = {
    "sqlite_connect": (
        "BLOQUANT AVANT BASCULE",
        "Le serveur doit utiliser une fabrique unique et un contrat de connexion abstrait.",
        "Test de démarrage sur SQLite puis staging Turso ; vérifier qu'aucune seconde base vide n'est ouverte.",
    ),
    "native_backup": (
        "BLOQUANT AVANT BASCULE",
        "Connection.backup est une API de fichier SQLite et n'est pas fournie par l'adaptateur libSQL.",
        "Export logique versionné, chiffré, restauré en base isolée puis comparé par empreintes.",
    ),
    "script_execution": (
        "À ADAPTER",
        "executescript n'est pas garanti par le pilote distant ; les scripts doivent être découpés en migrations explicites.",
        "Appliquer chaque migration sur une base Turso de staging vide puis rejouer pour vérifier l'idempotence.",
    ),
    "pragma": (
        "À ADAPTER",
        "Les PRAGMA ne sont pas tous pertinents ni disponibles à distance ; séparer réglages locaux, inspection et schéma.",
        "Classer chaque occurrence et tester uniquement les PRAGMA réellement nécessaires sur staging.",
    ),
    "row_factory": (
        "À ADAPTER",
        "Le code métier attend souvent des lignes indexables par nom comme sqlite3.Row.",
        "Tester les colonnes dupliquées, alias, casse, NULL et accès par index/nom avec le pilote réel.",
    ),
    "sqlite_type_or_exception": (
        "À ADAPTER",
        "Les tests isinstance et les catches sqlite3.* peuvent échouer avec les types/erreurs libSQL.",
        "Tester les erreurs de contrainte, syntaxe, timeout, connexion et type de connexion.",
    ),
    "cursor_metadata": (
        "À VÉRIFIER SUR STAGING",
        "lastrowid, rowcount et métadonnées peuvent varier selon pilote et opération.",
        "Tester INSERT, INSERT OR IGNORE, UPDATE, DELETE, executemany et SELECT à 0/1/N lignes.",
    ),
    "transaction_control": (
        "À VÉRIFIER SUR STAGING",
        "La présence de commit/rollback ne démontre pas l'atomicité distante ni la reprise après coupure.",
        "Écrire plusieurs effets liés puis injecter une panne avant commit ; vérifier zéro écriture partielle et reprise.",
    ),
    "replace_or_ignore": (
        "À VÉRIFIER SUR STAGING",
        "La syntaxe peut être reconnue par SQLite/libSQL, mais sa sémantique et ses effets de bord doivent être confirmés.",
        "Tester doublons, contraintes, triggers éventuels, clés étrangères et valeurs remplacées.",
    ),
    "sqlite_upsert": (
        "À VÉRIFIER SUR STAGING",
        "ON CONFLICT dépend de la cible, des contraintes et de la version du moteur.",
        "Exécuter chaque forme réelle d'UPSERT avec conflit et sans conflit.",
    ),
    "returning": (
        "À VÉRIFIER SUR STAGING",
        "RETURNING dépend du moteur et du pilote, notamment pour fetchone/fetchall.",
        "Vérifier les versions supportées et les lignes retournées sur INSERT/UPDATE/DELETE.",
    ),
    "json_functions": (
        "À VÉRIFIER SUR STAGING",
        "Les fonctions JSON et leurs chemins/types doivent avoir le même comportement attendu.",
        "Comparer objet, tableau, chaîne, nombre, booléen, NULL, JSON invalide et chemin absent.",
    ),
    "date_time_functions": (
        "À VÉRIFIER SUR STAGING",
        "Fuseau, précision, formats et valeurs NULL peuvent changer les résultats.",
        "Comparer dates UTC/Europe-Paris, limites de journée, fractions de seconde et dates invalides.",
    ),
    "sqlite_specific_functions": (
        "À VÉRIFIER SUR STAGING",
        "Les fonctions spécifiques au moteur peuvent être absentes ou exposer une sémantique différente.",
        "Tester chaque fonction réelle ou remplacer par une logique portable.",
    ),
    "fts_or_virtual_tables": (
        "BLOQUANT SI UTILISÉ EN PRODUCTION",
        "Les extensions virtuelles dépendent de la prise en charge et de la configuration du service distant.",
        "Créer et interroger chaque index virtuel sur staging ; sinon remplacer par une recherche portable.",
    ),
    "trigger_ddl": (
        "À VÉRIFIER SUR STAGING",
        "La syntaxe de trigger et son comportement transactionnel doivent être confirmés sur le service.",
        "Créer, déclencher, annuler et restaurer un trigger de test.",
    ),
    "index_ddl": (
        "À VÉRIFIER SUR STAGING",
        "Les index doivent être créés sans divergence et conservés après migration.",
        "Comparer noms, colonnes, unicité et plans/requêtes critiques.",
    ),
    "foreign_key_ddl": (
        "BLOQUANT SI NON VALIDÉ",
        "L'application dépend de l'intégrité relationnelle ; le réglage de contrainte doit être effectif à distance.",
        "Tester insert orphelin, suppression référencée, cascade et contrôle d'intégrité.",
    ),
    "check_constraints": (
        "À VÉRIFIER SUR STAGING",
        "Les contraintes CHECK peuvent être ignorées ou interprétées différemment selon migration/configuration.",
        "Tester valeurs valides, invalides et NULL sur chaque contrainte.",
    ),
    "autoincrement": (
        "À VÉRIFIER SUR STAGING",
        "La génération d'identifiants doit rester stable et sans collision après import/reprise.",
        "Importer des identifiants existants puis insérer plusieurs nouvelles lignes.",
    ),
    "connection_configuration": (
        "À ADAPTER",
        "Les réglages d'une connexion locale ne sont pas nécessairement exposés par le pilote distant.",
        "Séparer configuration SQLite locale et options documentées du pilote libSQL.",
    ),
    "custom_sql_functions": (
        "BLOQUANT SI UTILISÉ EN PRODUCTION",
        "Les fonctions définies dans le processus Python ne sont pas automatiquement disponibles sur le serveur distant.",
        "Remplacer par SQL portable ou calcul applicatif, puis tester les requêtes concernées.",
    ),
    "sqlite_specific_functions": (
        "À VÉRIFIER SUR STAGING",
        "Une fonction moteur n'est pas automatiquement portable.",
        "Vérifier chaque occurrence sur le pilote réel.",
    ),
    "parse_error": (
        "BLOQUANT",
        "Le scanner n'a pas pu analyser un fichier Python.",
        "Corriger la syntaxe avant de considérer l'inventaire complet.",
    ),
}

def build_matrix() -> dict:
    report = build_report()
    findings = report["findings"]
    grouped: dict[str, list[dict]] = {}
    for item in findings:
        grouped.setdefault(item["category"], []).append(item)

    rows = []
    for category in sorted(grouped):
        status, risk, test = RULES.get(
            category,
            ("REVUE MANUELLE REQUISE", "Motif non classé automatiquement.", "Analyser le code et ajouter un test ciblé."),
        )
        rows.append({
            "category": category,
            "classification": status,
            "occurrences": len(grouped[category]),
            "files": sorted({item["path"] for item in grouped[category]}),
            "risk": risk,
            "required_validation": test,
        })

    blockers = sum(row["classification"].startswith("BLOQUANT") for row in rows)
    unclassified = sum(row["classification"] == "REVUE MANUELLE REQUISE" for row in rows)
    return {
        "audit": "V50.43",
        "source_audit": report["audit"],
        "static_only": True,
        "database_connections_opened": 0,
        "secrets_read": False,
        "files_scanned": report["files_scanned"],
        "finding_count": report["finding_count"],
        "category_count": len(rows),
        "blocking_categories": blockers,
        "unclassified_categories": unclassified,
        "activation_allowed": False,
        "activation_reason": "Une matrice statique ne remplace pas les tests d'intégration Turso de staging, la migration contrôlée et les exercices de restauration.",
        "matrix": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = json.dumps(build_matrix(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
