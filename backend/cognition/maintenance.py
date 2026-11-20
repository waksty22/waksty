"""Maintenance passive sans altération artificielle de l'état affectif."""

from memory.episodic_memory import apply_memory_decay


def apply_passive_maintenance(db, user_id: str) -> None:
    """Applique uniquement la décroissance mémoire liée au temps.

    L'absence d'interaction ne constitue ni une dépense d'énergie ni une
    preuve de tristesse. Les rêves et pensées sont déclenchés séparément
    par la boucle d'entretien, selon les seuils d'inactivité.
    """
    apply_memory_decay(db, user_id)
