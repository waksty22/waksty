# utils/validators.py
import re

def normalize_and_validate_user_id(user_id: str) -> str:
    """Vérifie et normalise l'identifiant utilisateur."""
    if not user_id or not isinstance(user_id, str):
        raise ValueError("Identifiant utilisateur invalide.")
    
    cleaned_id = user_id.strip()
    if not re.match(r"^[\w\-]{3,64}$", cleaned_id):
        raise ValueError("L'identifiant utilisateur ne respecte pas le format requis.")
        
    return cleaned_id
