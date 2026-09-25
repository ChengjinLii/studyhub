from __future__ import annotations

from sqlalchemy import case, func, update
from sqlalchemy.orm import Session

from app.models.materials import MaterialRecord


def shift_material_counter(session: Session, material: MaterialRecord, column_name: str, delta: int) -> int:
    """Move a material counter by ±1 in SQL so concurrent requests cannot lose updates."""
    current = func.coalesce(getattr(MaterialRecord, column_name), 0)
    next_value = current + 1 if delta > 0 else case((current > 0, current - 1), else_=0)
    session.execute(
        update(MaterialRecord)
        .where(MaterialRecord.id == material.id)
        .values({column_name: next_value})
        .execution_options(synchronize_session=False)
    )
    session.expire(material, [column_name])
    return int(getattr(material, column_name) or 0)


def apply_material_rating(session: Session, material: MaterialRecord, *, rating: int, previous: int | None) -> tuple[float, int]:
    """Fold a new (previous is None) or changed rating into the aggregate in one UPDATE."""
    count = func.coalesce(MaterialRecord.rating_count, 0)
    avg = func.coalesce(MaterialRecord.rating_avg, 0.0)
    if previous is None:
        next_avg = func.round(((avg * count) + rating) / (count + 1), 2)
        next_count = count + 1
    else:
        next_avg = case((count > 0, func.round(((avg * count) - previous + rating) / count, 2)), else_=float(rating))
        next_count = count
    # rating_avg must be assigned first: MySQL evaluates SET left to right
    # with already-updated values, SQLite with the original row.
    session.execute(
        update(MaterialRecord)
        .where(MaterialRecord.id == material.id)
        .ordered_values((MaterialRecord.rating_avg, next_avg), (MaterialRecord.rating_count, next_count))
        .execution_options(synchronize_session=False)
    )
    session.expire(material, ["rating_avg", "rating_count"])
    return round(float(material.rating_avg or 0), 2), int(material.rating_count or 0)
