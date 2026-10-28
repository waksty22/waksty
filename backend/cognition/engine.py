# backend/cognition/engine.py

"""
Moteur de calcul cognitif, asymétrique et de mise en cache pour Chappie V19.3.
Conçu pour fonctionner de manière asynchrone sans perturber Gemini Live.
Intègre la pondération des sous-branches et l'isolation par utilisateur.
"""

import time
from typing import Dict, Any, Optional
# CORRECTION : Utilisation de l'import relatif direct depuis le dossier courant
from cognition.catalog import COGNITIVE_CATALOG

class CognitiveEngine:
    def __init__(self):
        # Cache intelligent en mémoire isolé par utilisateur pour éviter les conflits
        # Structure : { user_id: { "profile": {...}, "timestamp": 0.0 } }
        self._user_caches: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl: float = 60.0  # Durée de vie du cache en secondes

    def invalidate_cache(self, user_id: Optional[str] = None):
        """Invalide le cache pour un utilisateur spécifique ou pour tout le monde."""
        if user_id and user_id in self._user_caches:
            del self._user_caches[user_id]
        else:
            self._user_caches.clear()

    def compute_cognitive_profile(self, user_id: str, db_skills_data: Dict[str, Any], force_recompute: bool = False) -> Dict[str, Any]:
        """
        Calcule le profil cognitif complet, les niveaux pondérés des 12 systèmes, 
        et les tendances comportementales asymétriques pour un utilisateur donné.
        """
        current_time = time.time()
        
        # Vérification du cache par utilisateur
        if not force_recompute and user_id in self._user_caches:
            cached = self._user_caches[user_id]
            if current_time - cached["timestamp"] < self._cache_ttl:
                return cached["profile"]

        systems_profile = {}
        total_weighted_mastery = 0.0
        total_weights_sum = 0.0

        for sys_key, sys_info in COGNITIVE_CATALOG.items():
            sub_branches_scores = {}
            sys_weighted_sum = 0.0
            sys_weight_total = 0.0
            
            for sub_key, sub_meta in sys_info["sub_branches"].items():
                weight = sub_meta.get("weight", 1.0)
                
                # Récupère les données depuis la DB (niveau, maîtrise, confiance) ou valeurs par défaut (Niveau 1)
                sub_data = db_skills_data.get(sys_key, {}).get(sub_key, {
                    "level": 1,
                    "mastery": 0.0,
                    "confidence": 0.5,
                    "xp": 0
                })
                
                sub_branches_scores[sub_key] = sub_data
                
                lvl = float(sub_data.get("level", 1))
                sys_weighted_sum += lvl * weight
                sys_weight_total += weight

            # Moyenne pondérée du système
            avg_sys_level = sys_weighted_sum / sys_weight_total if sys_weight_total > 0 else 1.0
            
            systems_profile[sys_key] = {
                "name": sys_info["name"],
                "average_level": round(avg_sys_level, 2),
                "sub_branches": sub_branches_scores
            }

            total_weighted_mastery += sys_weighted_sum
            total_weights_sum += sys_weight_total

        # Calcul global de maturité cognitive pondéré
        global_maturity_score = total_weighted_mastery / total_weights_sum if total_weights_sum > 0 else 1.0

        # Détermination des comportements dynamiques (Asymétrie savant/novice)
        behavior_traits = self._derive_behavioral_traits(systems_profile)

        profile = {
            "version": "19.3",
            "global_maturity": round(global_maturity_score, 2),
            "systems": systems_profile,
            "behavior": behavior_traits,
            "updated_at": current_time
        }

        # Mise en cache isolée par utilisateur
        self._user_caches[user_id] = {
            "profile": profile,
            "timestamp": current_time
        }

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
