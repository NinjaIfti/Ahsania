from capture.api.schemas import TemplateOut
from capture.db.models import Template


def template_out(template: Template, phase3_enabled: bool) -> TemplateOut:
    return TemplateOut(
        key=template.key,
        version=template.version,
        phase=template.phase,
        kind=template.kind,
        title=template.title,
        definition=template.definition,
        locked=template.phase == 3 and not phase3_enabled,
    )
