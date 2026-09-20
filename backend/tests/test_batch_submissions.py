from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.deps import get_auth_repo, get_material_asset_store
from app.api.routes.batch_submissions import get_batch_submission_service
from app.core.config import get_settings
from app.core.db import session_scope
from app.models.batch_submissions import BatchSubmissionItemRecord as Item, BatchSubmissionRecord as Batch
from app.models.materials import MaterialRecord
from tests.support import build_auth_headers, seed_read_users


@pytest.fixture()
def batch_client(client, auth_service):
    seed_read_users(auth_service)
    return client


def headers(user=1):
    return build_auth_headers(user, 8 if user == 3 else 1)


def create(client, *, netdisk=False, intent="FREE", count=1, key=None):
    payload = {"submissionId": key or uuid4().hex, "deliveryMethod": "NETDISK" if netdisk else "FILE",
               "publicationIntent": intent, "pricingNote": "expected two yuan", "note": "private-note",
               "netdiskUrl": "https://example.com/private-folder" if netdisk else "",
               "netdiskPassword": "abcd" if netdisk else "", "consent": True,
               "files": [] if netdisk else [{"name": f"notes-{i}.txt", "sizeBytes": 5, "contentType": "text/plain"} for i in range(count)]}
    response = client.post("/api/batch-submissions", headers=headers(), json=payload)
    assert response.status_code == 200, response.text
    return response.json()["data"], payload


def upload(client, batch, item):
    path = f'/api/batch-submissions/{batch["id"]}/items/{item["id"]}'
    authorization = client.post(path + "/authorize", headers=headers())
    assert authorization.status_code == 200, authorization.text
    token = authorization.json()["data"]["uploadToken"]
    response = client.put(path + "/file", headers={**headers(), "x-studyhub-upload-token": token},
                          files={"file": (item["name"], b"hello", "text/plain")})
    assert response.status_code == 200, response.text
    return token


def submit(client, batch):
    response = client.post(f'/api/batch-submissions/{batch["id"]}/submit', headers=headers())
    assert response.status_code == 200, response.text


def publication(batch, *, price=0, confirmed=False):
    return {"publicationId": uuid4().hex, "itemIds": [i["id"] for i in batch["items"]],
            "title": "Batch course notes", "description": "Reviewed material", "school": "test school",
            "courseCategory": "GENERAL", "price": price, "pricingConfirmed": confirmed,
            "confirmationNote": "Uploader confirmed the price" if confirmed else ""}


def test_private_intake_owner_is_bound_and_idempotent(batch_client):
    c = batch_client
    batch, payload = create(c)
    retry = c.post("/api/batch-submissions", headers=headers(), json=payload)
    assert retry.json()["data"]["id"] == batch["id"]
    payload["uploaderId"] = 3
    assert c.post("/api/batch-submissions", headers=headers(), json=payload).status_code == 400
    assert c.get(f'/api/batch-submissions/{batch["id"]}', headers=headers(2)).status_code == 404
    assert c.get('/api/admin/batch-submissions', headers=headers()).status_code == 403
    own = c.get('/api/batch-submissions', headers=headers()).json()["data"]["items"][0]
    assert "note" not in own and "name" not in own["items"][0]
    assert c.post(f'/api/batch-submissions/{batch["id"]}/submit', headers=headers()).status_code == 409


def test_upload_retry_and_private_download(batch_client):
    c = batch_client
    batch, _ = create(c)
    item = batch["items"][0]
    token = upload(c, batch, item)
    assert c.get('/api/me', headers={"Authorization": f"Bearer {token}"}).status_code in {401, 404}
    path = f'/api/batch-submissions/{batch["id"]}/items/{item["id"]}'
    assert c.post(path + '/authorize', headers=headers()).json()["data"]["alreadyUploaded"]
    submit(c, batch)
    private = f'/api/admin/batch-submissions/{batch["id"]}/items/{item["id"]}/file'
    assert c.get(private, headers=headers()).status_code == 403
    result = c.get(private, headers=headers(3))
    assert result.status_code == 200 and result.content == b"hello"
    assert "no-store" in result.headers["cache-control"]


def test_netdisk_publish_intent_attribution_and_retry(batch_client):
    c = batch_client
    batch, _ = create(c, netdisk=True, intent="CONTACT")
    submit(c, batch)
    path = f'/api/admin/batch-submissions/{batch["id"]}/publish'
    payload = publication(batch)
    assert c.post(path, headers=headers(3), json=payload).status_code == 400
    payload.update(pricingConfirmed=True, confirmationNote="Confirmed free publication")
    response = c.post(path, headers=headers(3), json=payload)
    assert response.status_code == 200, response.text
    material_id = response.json()["data"]["materialId"]
    assert c.post(path, headers=headers(3), json=payload).json()["data"]["materialId"] == material_id
    with session_scope() as session:
        material = session.get(MaterialRecord, material_id)
        assert material.uploader_id == 1 and material.is_free
        assert material.netdisk_password == "abcd"
    own = c.get('/api/batch-submissions', headers=headers()).json()["data"]["items"][0]
    assert own["publications"][0]["url"] == f"/materials/{material_id}"
    assert "netdiskUrl" not in own


def test_return_supplement_and_reject_clear_private_metadata(batch_client):
    c = batch_client
    batch, _ = create(c, netdisk=True)
    submit(c, batch)
    path = f'/api/admin/batch-submissions/{batch["id"]}/review'
    ids = [i["id"] for i in batch["items"]]
    assert c.post(path, headers=headers(3), json={"action": "RETURN", "reason": "Please clarify", "itemIds": ids}).status_code == 200
    own = c.get(f'/api/batch-submissions/{batch["id"]}', headers=headers()).json()["data"]
    assert own["items"][0]["reason"] == "Please clarify"
    assert c.patch(f'/api/batch-submissions/{batch["id"]}', headers=headers(), json={"note": "Clarified"}).status_code == 200
    assert c.post(path, headers=headers(3), json={"action": "REJECT", "reason": "Not suitable", "itemIds": ids}).status_code == 200
    with session_scope() as session:
        get_batch_submission_service().run_once(session)
        record = session.get(Batch, batch["id"])
        assert record.status == "CLEANED"
        assert record.netdisk_url is None and record.netdisk_password is None and record.note is None


def test_scan_does_not_publish_and_cleanup_retries(batch_client, monkeypatch):
    c = batch_client
    batch, _ = create(c)
    upload(c, batch, batch["items"][0])
    item_id = batch["items"][0]["id"]
    submit(c, batch)
    monkeypatch.setattr(get_settings(), "material_security_scan_enabled", True)
    service = get_batch_submission_service()
    with session_scope() as session:
        service.run_once(session, scanner=SimpleNamespace(_scan_object=lambda key: SimpleNamespace(status="CLEAN")))
        item = session.get(Item, batch["items"][0]["id"])
        assert item.scan_status == "CLEAN" and item.status == "UPLOADED"
        assert session.get(Batch, batch["id"]).status == "WAITING"
        key = item.object_key
    path = f'/api/admin/batch-submissions/{batch["id"]}/review'
    c.post(path, headers=headers(3), json={"action": "REJECT", "reason": "Duplicate", "itemIds": [item_id]})
    store = get_material_asset_store()
    original = store.delete_key_strict
    def fail(_key):
        raise OSError("storage temporarily unavailable")
    monkeypatch.setattr(store, "delete_key_strict", fail)
    with session_scope() as session:
        service.run_once(session)
        assert session.get(Item, item_id).status == "REJECTED"
        assert session.get(Item, item_id).object_key == key
    monkeypatch.setattr(store, "delete_key_strict", original)
    with session_scope() as session:
        service.run_once(session)
        assert session.get(Item, item_id).status == "CLEANED"
    assert not store.resolve_path(key).exists()


def test_scoped_agent_access_restrictions_and_revocation(batch_client):
    c = batch_client
    batch, _ = create(c, netdisk=True)
    other, _ = create(c, netdisk=True)
    submit(c, batch)
    root = f'/api/admin/batch-submissions/{batch["id"]}'
    token = c.post(root + '/access-token', headers=headers(3), json={"permissions": ["read", "review"]}).json()["data"]["token"]
    delegated = {"Authorization": f"Bearer {token}"}
    assert c.get(root, headers=delegated).status_code == 200
    assert c.get(f'/api/admin/batch-submissions/{other["id"]}', headers=delegated).status_code == 403
    assert c.post(root + '/publish', headers=delegated, json=publication(batch)).status_code == 403
    assert c.post(root + '/review', headers=delegated, json={"itemIds": [batch["items"][0]["id"]], "action": "REJECT", "reason": "no"}).status_code == 403
    with session_scope() as session:
        get_auth_repo().bump_session_version(session, 3, reason="revoke-batch-delegation")
        session.commit()
    assert c.get(root, headers=delegated).status_code == 403


def test_file_publication_keeps_source_and_original_owner(batch_client):
    c = batch_client
    batch, _ = create(c, count=2)
    for item in batch["items"]:
        upload(c, batch, item)
    submit(c, batch)
    with session_scope() as session:
        for item in session.scalars(select(Item).where(Item.batch_id == batch["id"])):
            item.scan_status = "CLEAN"
        session.commit()
    payload = publication(batch)
    path = f'/api/admin/batch-submissions/{batch["id"]}'
    response = c.post(path + '/publish', headers=headers(3), json=payload)
    assert response.status_code == 200, response.text
    with session_scope() as session:
        material = session.get(MaterialRecord, response.json()["data"]["materialId"])
        assert material.uploader_id == 1 and material.file_type == "zip"
        assert material.file_storage_key not in [i.object_key for i in session.scalars(select(Item).where(Item.batch_id == batch["id"]))]
    assert c.post(path + '/review', headers=headers(3), json={"itemIds": payload["itemIds"], "action": "REJECT", "reason": "delete"}).status_code == 409


def test_expired_draft_cleanup(batch_client):
    batch, _ = create(batch_client)
    with session_scope() as session:
        session.get(Batch, batch["id"]).created_at = datetime.now(UTC) - timedelta(days=8)
        session.commit()
        get_batch_submission_service().run_once(session)
        assert session.get(Batch, batch["id"]).status == "CLEANED"
