from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from capture.api.convert import template_out
from capture.api.deps import current_user, get_db
from capture.api.schemas import TemplateOut
from capture.app_settings import load_app_settings
from capture.db.models import User
from capture.formschema.store import active_templates

router = APIRouter(tags=["templates"])


@router.get("/templates", response_model=list[TemplateOut])
def list_templates(_: User = Depends(current_user), db: Session = Depends(get_db)) -> list[TemplateOut]:
    phase3_enabled = load_app_settings(db).phase3_enabled
    return [template_out(t, phase3_enabled) for t in active_templates(db)]
