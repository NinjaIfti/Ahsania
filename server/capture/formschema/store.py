import json
from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from capture.db.models import Template
from capture.formschema.model import TemplateDef


class TemplateConflict(Exception):
    pass


def _canonical(definition: dict) -> str:
    return json.dumps(definition, sort_keys=True, separators=(",", ":"))


def load_templates(session: Session, directory: Path) -> list[str]:
    """Insert every *.yaml template not yet in the database; refuse silent edits."""
    report: list[str] = []
    for path in sorted(Path(directory).glob("*.yaml")):
        tpl = TemplateDef.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        definition = tpl.model_dump(mode="json", exclude_none=True)
        existing = session.scalar(select(Template).where(Template.key == tpl.key, Template.version == tpl.version))
        if existing is None:
            session.add(
                Template(
                    key=tpl.key,
                    version=tpl.version,
                    phase=tpl.phase,
                    kind=tpl.kind,
                    title=tpl.title,
                    definition=definition,
                )
            )
            report.append(f"{tpl.key} v{tpl.version}: created")
        elif _canonical(existing.definition) != _canonical(definition):
            raise TemplateConflict(f"{path.name}: {tpl.key} v{tpl.version} was changed without bumping 'version'")
        else:
            report.append(f"{tpl.key} v{tpl.version}: unchanged")
    session.flush()
    return report


def active_templates(session: Session) -> list[Template]:
    latest = select(Template.key, func.max(Template.version).label("version")).group_by(Template.key).subquery()
    stmt = (
        select(Template)
        .join(latest, (Template.key == latest.c.key) & (Template.version == latest.c.version))
        .order_by(Template.phase, Template.key)
    )
    return list(session.scalars(stmt))


def get_active(session: Session, key: str) -> Template | None:
    return session.scalar(select(Template).where(Template.key == key).order_by(Template.version.desc()).limit(1))


def template_def(template: Template) -> TemplateDef:
    return TemplateDef.model_validate(template.definition)
