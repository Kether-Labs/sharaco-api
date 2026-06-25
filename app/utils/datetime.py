from datetime import datetime, timezone

def to_naive_utc(dt: datetime | None) -> datetime | None:
    """Convertit un datetime en UTC naive (sans timezone) pour PostgreSQL."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        # Convertir en UTC puis retirer la timezone
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt