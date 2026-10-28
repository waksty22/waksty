# backend/cognition/engine.py

"""
Moteur de calcul cognitif, asymétrique et de mise en cache pour Chappie V19.3.
Conçu pour fonctionner de manière asynchrone sans perturber Gemini Live.
"""

import time
from typing import Dict, Any, Optional
# CORRECTION : Utilisation de l'import relatif direct depuis le dossier courant
from cognition.catalog import COGNITIVE_CATALOG

class CognitiveEngine:
    def __init__(self):
        # Cache intelligent en mémoire pour éviter les requêtes SQLite répétées
        self._profile_cache: Optional[Dict[str, Any]] = None
        self._cache_timestamp: float = 0.0
        self._cache_ttl: float = 60.0  # Durée de vie du cache en secondes

    def invalidate_cache(self):
        """Invalide le cache lorsqu'une compétence ou une preuve est validée."""
        self._profile_cache = None
        self._cache_timestamp = 0.0

    def compute_cognitive_profile(self, db_skills_data: Dict[str, Any], force_recompute: bool = False) -> Dict[str, Any]:
        """
        Calcule le profil cognitif complet, les niveaux des 12 systèmes, 
        et les tendances comportementales asymétriques.
        """
        current_time = time.time()
        if not force_recompute and self._profile_cache and (current_time - self._cache_timestamp < self._cache_ttl):
            return self._profile_cache

        systems_profile = {}
        total_mastery = 0.0
        total_sub_count = 0

        for sys_key, sys_info in COGNITIVE_CATALOG.items():
            sub_branches_scores = {}
            sys_total_score = 0.0
            
            for sub_key in sys_info["sub_branches"].keys():
                # Récupère les données depuis la DB (niveau, maîtrise, confiance) ou valeurs par défaut (Niveau 1)
                sub_data = db_skills_data.get(sys_key, {}).get(sub_key, {
                    "level": 1,
                    "mastery": 0.0,
                    "confidence": 0.5,
                    "xp": 0
                })
                
                sub_branches_scores[sub_key] = sub_data
                sys_total_score += sub_data.get("level", 1)
                total_mastery += sub_data.get("level", 1)
                total_sub_count += 1

            # Moyenne du système
            avg_sys_level = sys_total_score / len(sys_info["sub_branches"]) if sys_info["sub_branches"] else 1.0
            
            systems_profile[sys_key] = {
                "name": sys_info["name"],
                "average_level": round(avg_sys_level, 2),
                "sub_branches": sub_branches_scores
            }

        # Calcul global de maturité cognitive
        global_maturity_score = total_mastery / total_sub_count if total_sub_count > 0 else 1.0

        # Détermination des comportements dynamiques (Asymétrie savant/novice)
        behavior_traits = self._derive_behavioral_traits(systems_profile)

        profile = {
            "version": "19.3",
            "global_maturity": round(global_maturity_score, 2),
            "systems": systems_profile,
            "behavior": behavior_traits,
            "updated_at": current_time
        }

        # Mise en cache
        self._profile_cache = profile
        self._cache_timestamp = current_time

        return profile

    def _derive_behavioral_traits(self, systems: Dict[str, Any]) -> Dict[str, Any]:
        """
        Traduit les niveaux granulaires en consignes comportementales concrètes 
        pour influencer le prompt de Chappie (ex: gestion de l'humour, de l'incertitude).
        """
        tete_lvl = systems.get("tete", {}).get("average_level", 1.0)
        mots_lvl = systems.get("mots", {}).get("average_level", 1.0)
        lien_lvl = systems.get("lien", {}).get("average_level", 1.0)
        
        # Exemple d'asymétrie : Extraction de sous-branches spécifiques
        humour_lvl = systems.get("mots", {}).get("sub_branches", {}).get("humour_ironie", {}).get("level", 1)
        incertitude_lvl = systems.get("tete", {}).get("sub_branches", {}).get("gestion_incertitude", {}).get("level", 1)

        return {
            "response_complexity": "expert" if tete_lvl > 6 else ("intermediate" if tete_lvl > 3 else "simple"),
            "vocabulary_richness": "high" if mots_lvl > 6 else ("moderate" if mots_lvl > 3 else "basic"),
            "humor_enabled": humour_lvl >= 4,
            "humor_description": "Capable de comprendre l'ironie et de plaisanter." if humour_lvl >= 4 else "Prend tout au premier degré et ne comprend pas l'ironie.",
            "uncertainty_handling": "Admet ouvertement ses lacunes et pose des questions." if incertitude_lvl >= 5 else "A tendance à extrapoler ou à masquer son incertitude.",
            "empathy_depth": "Fine lecture des intentions et soutien adapté." if lien_lvl > 5 else "Relation directe et factuelle."
        }

# Instance globale du moteur
cognitive_engine = CognitiveEngine()
