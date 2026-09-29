from __future__ import annotations

from sqlalchemy import select

from app.models.batch_submissions import BatchSubmissionItemRecord as Item
from app.models.batch_submissions import BatchPublicationRecord as Publication
from app.models.materials import MaterialRecord


def serialize_batch(session, batch, *, admin=False, created=False, items=None, publications=None):
    """Serialize a batch without exposing private fields to its uploader."""
    session.flush()
    if items is None:
        items = session.scalars(
            select(Item)
            .where(Item.batch_id == batch.id)
            .order_by(Item.id)
            .execution_options(populate_existing=True)
        ).all()
    if publications is None:
        publications = list(session.execute(
            select(Publication, MaterialRecord.title)
            .join(MaterialRecord, MaterialRecord.id == Publication.material_id)
            .where(Publication.batch_id == batch.id, Publication.status == "PUBLISHED")
        ))
    result = {
        "id": batch.id,
        "status": batch.status,
        "deliveryMethod": batch.delivery_method,
        "publicationIntent": batch.publication_intent,
        "createdAt": batch.created_at,
        "updatedAt": batch.updated_at,
        "itemCount": len(items),
        "totalBytes": sum(item.size_bytes for item in items),
        "items": [
            {
                "id": item.id,
                "status": item.status,
                "scanStatus": item.scan_status,
                "sizeBytes": item.size_bytes,
                **({"name": item.name, "contentType": item.content_type} if admin or created else {}),
                "reason": item.reason,
            }
            for item in items
        ],
        "publications": [
            {
                "id": publication.id,
                "materialId": publication.material_id,
                "title": title,
                "url": f"/materials/{publication.material_id}",
            }
            for publication, title in publications
        ],
    }
    if admin:
        result.update(
            uploaderId=batch.uploader_id,
            note=batch.note,
            pricingNote=batch.pricing_note,
            netdiskUrl=batch.netdisk_url,
            netdiskPassword=batch.netdisk_password,
        )
    return result
