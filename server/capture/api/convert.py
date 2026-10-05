import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from capture.api.schemas import EventOut, FileOut, LastEventOut, RecordDetail, RecordSummary, TemplateOut
from capture.db.models import Record, ReviewEvent, Template
from capture.formschema.diff import flatten


SYSTEM_ACTOR = "System"


def _actor_name(event: ReviewEvent) -> str:
    """Events the worker writes (quarantine) have no actor."""
    return event.actor.name if event.actor is not None else SYSTEM_ACTOR


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
    return LastEventOut(action=event.action, comment=event.comment, actor_name=_actor_name(event), created_at=event.created_at)


def _same(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return isinstance(a, bool) == isinstance(b, bool) and a == b


def extraction_view(record: Record, hide_values: bool) -> dict[str, Any] | None:
    """Per-field AI results. `edited` marks values changed since the AI filled them in.

    NSU never sees the AI's own values: one the hospital changed or removed may have held an identifier.
    """
    if not record.extraction:
        return None
    current = flatten(record.field_values or {})
    fields: dict[str, Any] = {}
    for path, entry in record.extraction.get("fields", {}).items():
        view = {
            "colour": entry["colour"],
            "confidence": entry["confidence"],
            "sources": entry["sources"],
            "edited": not _same(current.get(path), entry.get("value")),
        }
        if not hide_values:
            view["value"] = entry.get("value")
        fields[path] = view
    return {"model": record.extraction.get("model"), "fields": fields}


def ai_counts(record: Record) -> tuple[int, int]:
    """Amber and red AI fields still holding the AI's value: the queue's 🟡/🔴 counts (spec §8.3)."""
    if not record.extraction:
        return 0, 0
    current = flatten(record.field_values or {})
    unchecked = [
        entry["colour"] for path, entry in record.extraction.get("fields", {}).items() if _same(current.get(path), entry.get("value"))
    ]
    return unchecked.count("amber"), unchecked.count("red")


def record_summary(record: Record, last_event: ReviewEvent | None) -> RecordSummary:
    ai_amber, ai_red = ai_counts(record)
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
        ai_amber=ai_amber,
        ai_red=ai_red,
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
    extraction_queued_at: datetime | None = None,
) -> RecordDetail:
    summary = record_summary(record, events[-1] if events else None)
    return RecordDetail(
        **summary.model_dump(),
        values=record.field_values,
        extraction=extraction_view(record, hide_change_values),
        row_version=record.row_version,
        files=[FileOut.model_validate(f) for f in record.files],
        events=[
            EventOut(
                id=e.id,
                action=e.action,
                comment=e.comment,
                actor_name=_actor_name(e),
                created_at=e.created_at,
                field_changes=_visible_changes(e.field_changes, hide_change_values),
                field_flags=e.field_flags,
            )
            for e in events
        ],
        template=template_out(record.template, phase3_enabled),
        errors=errors,
        duplicate_of=list(duplicate_of),
        quarantine=record.quarantine,
        extraction_queued_at=extraction_queued_at,
    )
