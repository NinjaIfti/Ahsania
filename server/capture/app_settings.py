from sqlalchemy.orm import Session

from capture.db.models import AppSettings


def load_app_settings(db: Session, *, for_update: bool = False) -> AppSettings:
    """The single settings row (id=1) created by the initial migration."""
    return db.get(AppSettings, 1, with_for_update=True if for_update else None)
