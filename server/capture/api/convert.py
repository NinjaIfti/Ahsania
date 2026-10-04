import uuid
from collections.abc import Iterable

from capture.api.schemas import EventOut, FileOut, LastEventOut, RecordDetail, RecordSummary, TemplateOut
from capture.db.models import Record, ReviewEvent, Template


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


def _last_event(event: ReviewEvent | None) -> LastEventOut | None:
    if event is None:
        return None
    return LastEventOut(action=event.action, comment=event.comment, actor_name=event.actor.name, created_at=event.created_at)


def record_summary(record: Record, last_event: ReviewEvent | None) -> RecordSummary:
    return RecordSummary(
        id=record.id,
        study_code=record.study_code,
        template_key=record.template.key,
        template_title=record.template.title,
        template_version=record.template.version,
        status=record.status,
        extraction_status=record.extraction_status,
        document_date=record.document_date,
        created_by_id=record.created_by,
        created_by_name=record.creator.name,
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_event=_last_event(last_event),
    )


def _visible_changes(changes: list | None, hide_values: bool) -> list | None:
    if changes is None or not hide_values:
        return changes
    return [{"path": change["path"]} for change in changes]


def record_detail(
    record: Record,
    events: list[ReviewEvent],
    errors: list[dict[str, str]],
    phase3_enabled: bool,
    duplicate_of: Iterable[uuid.UUID] = (),
    hide_change_values: bool = False,
) -> RecordDetail:
    summary = record_summary(record, events[-1] if events else None)
    return RecordDetail(
        **summary.model_dump(),
        values=record.field_values,
        extraction=record.extraction,
        row_version=record.row_version,
        files=[FileOut.model_validate(f) for f in record.files],
        events=[
            EventOut(
                id=e.id,
                action=e.action,
                comment=e.comment,
                actor_name=e.actor.name,
                created_at=e.created_at,
                field_changes=_visible_changes(e.field_changes, hide_change_values),
                field_flags=e.field_flags,
            )
            for e in events
        ],
        template=template_out(record.template, phase3_enabled),
        errors=errors,
        duplicate_of=list(duplicate_of),
    )
