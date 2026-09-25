from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from app.api.deps import get_materials_service
from app.core.db import session_scope
from app.models.comments import CommentRecord
from app.models.materials import MaterialRecord
from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users


PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4//8/AwAI/AL+p5qgoAAAAABJRU5ErkJggg==")


def test_step9_comments_write_flow_matches_current_contract(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)

    create_response = client.post(
        "/api/comments",
        headers=alice_headers,
        json={"materialId": 101, "content": "Step 9 新评论"},
    )
    assert create_response.status_code == 200
    created = create_response.json()["data"]
    assert created["materialId"] == 101
    assert created["content"] == "Step 9 新评论"
    assert created["user"]["id"] == 1

    duplicate_comment = client.post(
        "/api/comments",
        headers=alice_headers,
        json={"materialId": 101, "content": "Step 9 新评论"},
    )
    assert duplicate_comment.status_code == 409
    assert duplicate_comment.json()["error"]["code"] == "COMMENT_DUPLICATE"

    reply_response = client.post(
        "/api/comments",
        headers=baishan_headers,
        json={"materialId": 101, "parentId": created["id"], "content": "Step 9 回复"},
    )
    assert reply_response.status_code == 200
    reply = reply_response.json()["data"]
    assert reply["parentId"] == created["id"]

    replies_response = client.get(f"/api/comments/{created['id']}/replies", headers=alice_headers)
    assert replies_response.status_code == 200
    replies_data = replies_response.json()["data"]
    assert replies_data["meta"]["total"] == 1
    assert replies_data["items"][0]["id"] == reply["id"]

    update_response = client.patch(
        f"/api/comments/{created['id']}",
        headers=alice_headers,
        json={"content": "Step 9 新评论（已更新）"},
    )
    assert update_response.status_code == 200
    updated = update_response.json()["data"]
    assert updated["content"] == "Step 9 新评论（已更新）"
    assert updated["edited"] is True

    like_response = client.post(f"/api/comments/{created['id']}/like", headers=baishan_headers)
    assert like_response.status_code == 200
    assert like_response.json()["data"] == {"likeCount": 1}

    duplicate_like = client.post(f"/api/comments/{created['id']}/like", headers=baishan_headers)
    assert duplicate_like.status_code == 400
    assert duplicate_like.json()["msg"] == "已点赞"

    unlike_response = client.delete(f"/api/comments/{created['id']}/like", headers=baishan_headers)
    assert unlike_response.status_code == 200
    assert unlike_response.json()["data"] == {"likeCount": 0}

    report_response = client.post(
        f"/api/comments/{created['id']}/report",
        headers=baishan_headers,
        json={"reason": "无关内容"},
    )
    assert report_response.status_code == 200
    assert report_response.json()["data"] == {"success": True}

    delete_response = client.delete(f"/api/comments/{created['id']}", headers=alice_headers)
    assert delete_response.status_code == 200
    assert delete_response.json()["data"] == {"success": True}

    list_response = client.get("/api/comments", params={"materialId": 101, "page": 0, "size": 20}, headers=alice_headers)
    assert list_response.status_code == 200
    listed_ids = {item["id"] for item in list_response.json()["data"]["items"]}
    assert created["id"] not in listed_ids


def test_step9_market_write_and_notification_flow(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    admin_headers = build_auth_headers(3, 8)

    payload = {
        "title": "Step 9 Campus Router",
        "category": "DIGITAL",
        "description": "九成新路由器，宿舍换新后闲置。",
        "price": 88.5,
        "contactType": "WECHAT",
        "contactValue": "step9-router-wechat",
        "school": "电子科技大学",
    }
    create_response = client.post(
        "/api/market",
        headers=alice_headers,
        data={"payload": json.dumps(payload, ensure_ascii=False)},
        files=[("images", ("router.png", PNG_1X1, "image/png"))],
    )
    assert create_response.status_code == 200
    created = create_response.json()["data"]
    item_id = created["id"]
    assert created["title"] == payload["title"]
    assert created["isOwner"] is True
    assert created["canViewContact"] is True
    assert created["images"] == [f"/api/market/{item_id}/images/1"]

    image_response = client.get(created["images"][0])
    assert image_response.status_code == 200
    assert image_response.headers["content-type"].startswith("image/")

    status_response = client.patch(
        f"/api/market/{item_id}/status",
        headers=alice_headers,
        json={"status": "SOLD"},
    )
    assert status_response.status_code == 200
    assert status_response.json()["data"]["status"] == "SOLD"

    reopen_response = client.patch(
        f"/api/market/{item_id}/status",
        headers=alice_headers,
        json={"status": "SALE"},
    )
    assert reopen_response.status_code == 200
    assert reopen_response.json()["data"]["status"] == "SALE"

    want_response = client.post(f"/api/market/{item_id}/want", headers=baishan_headers)
    assert want_response.status_code == 200
    wanted = want_response.json()["data"]
    assert wanted["wanted"] is True
    assert wanted["wantCount"] == 1
    assert wanted["canViewContact"] is True
    assert wanted["contactValue"] == "step9-router-wechat"

    wanted_ids_response = client.get("/api/market/wanted", headers=baishan_headers)
    assert wanted_ids_response.status_code == 200
    assert item_id in wanted_ids_response.json()["data"]

    seller_summary = client.get("/api/notifications/summary", headers=alice_headers)
    assert seller_summary.status_code == 200
    summary_data = seller_summary.json()["data"]
    assert summary_data["hasUnread"] is True
    assert summary_data["latestSender"] == "想要提醒"
    assert "Step 9 Campus Router" in summary_data["latestMessage"]

    seller_list = client.get("/api/notifications/list", headers=alice_headers)
    assert seller_list.status_code == 200
    assert any("Step 9 Campus Router" in item["message"] for item in seller_list.json()["data"])

    mark_read = client.post("/api/notifications/read", headers=alice_headers)
    assert mark_read.status_code == 200

    seller_summary_after_read = client.get("/api/notifications/summary", headers=alice_headers)
    assert seller_summary_after_read.status_code == 200
    assert seller_summary_after_read.json()["data"]["hasUnread"] is False

    admin_list = client.get("/api/admin/market", headers=admin_headers, params={"page": 1, "size": 20})
    assert admin_list.status_code == 200
    assert any(item["id"] == item_id for item in admin_list.json()["data"]["items"])

    batch_update = client.post(
        "/api/admin/market/batch-update",
        headers=admin_headers,
        json={"itemIds": [item_id], "status": "HIDDEN"},
    )
    assert batch_update.status_code == 200
    assert batch_update.json()["data"] == {"updated": 1, "requested": 1, "missingIds": []}

    hidden_detail = client.get(f"/api/market/{item_id}", headers=baishan_headers)
    assert hidden_detail.status_code == 404

    batch_delete = client.post(
        "/api/admin/market/batch-delete",
        headers=admin_headers,
        json={"itemIds": [item_id]},
    )
    assert batch_delete.status_code == 200
    assert batch_delete.json()["data"] == {"deleted": 1, "requested": 1, "failedIds": []}

    deleted_detail = client.get(f"/api/market/{item_id}", headers=alice_headers)
    assert deleted_detail.status_code == 404


def test_step9_community_reports_and_admin_aliases(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    admin_headers = build_auth_headers(3, 8)

    feedback_response = client.post(
        "/api/feedback",
        headers=alice_headers,
        json={"type": "feature", "page": "/materials/101", "content": "希望支持更多过滤器", "contact": "alice-qq"},
    )
    assert feedback_response.status_code == 200
    feedback = feedback_response.json()["data"]
    assert feedback["type"] == "FEATURE"
    assert feedback["userId"] == 1

    volunteer_response = client.post(
        "/api/volunteers",
        headers=baishan_headers,
        json={
            "name": "白山",
            "schoolMajorGrade": "电子科大 / 微电子 / 大四",
            "skills": ["frontend", "frontend", "design"],
            "timeCommitment": "4-8h",
            "portfolioUrl": "https://example.com/step9",
            "intro": "希望继续参与前端体验优化。",
            "contact": "wx-baishan-step9",
        },
    )
    assert volunteer_response.status_code == 200
    volunteer = volunteer_response.json()["data"]
    assert volunteer["skills"] == ["FRONTEND", "DESIGN"]

    feedback_list = client.get("/api/admin/community/feedbacks", headers=admin_headers)
    assert feedback_list.status_code == 200
    assert any(item["id"] == feedback["id"] for item in feedback_list.json()["data"])

    feedback_alias_list = client.get("/api/admin/feedbacks", headers=admin_headers)
    assert feedback_alias_list.status_code == 200
    assert any(item["id"] == feedback["id"] for item in feedback_alias_list.json()["data"])

    feedback_update = client.patch(
        "/api/admin/feedbacks",
        headers=admin_headers,
        params={"id": feedback["id"]},
        json={"status": "IN_PROGRESS"},
    )
    assert feedback_update.status_code == 200
    assert feedback_update.json()["data"]["status"] == "IN_PROGRESS"

    volunteer_alias_list = client.get("/api/admin/volunteers", headers=admin_headers)
    assert volunteer_alias_list.status_code == 200
    assert any(item["id"] == volunteer["id"] for item in volunteer_alias_list.json()["data"])

    volunteer_update = client.patch(
        "/api/admin/volunteers",
        headers=admin_headers,
        params={"id": volunteer["id"]},
        json={"status": "CONTACTED"},
    )
    assert volunteer_update.status_code == 200
    assert volunteer_update.json()["data"]["status"] == "CONTACTED"

    direct_notice = client.post(
        "/api/admin/notifications",
        headers=admin_headers,
        json={"userId": 1, "message": "Step 9 单播通知"},
    )
    assert direct_notice.status_code == 200

    alias_notice = client.post(
        "/api/notifications/admin",
        headers=admin_headers,
        json={"userId": 2, "message": "Step 9 别名通知"},
    )
    assert alias_notice.status_code == 200

    removed_broadcast = client.post(
        "/api/admin/notifications",
        headers=admin_headers,
        json={"userId": None, "message": "已停用的广播通知"},
    )
    assert removed_broadcast.status_code == 400

    alice_notifications = client.get("/api/notifications/list", headers=alice_headers)
    assert alice_notifications.status_code == 200
    assert any(item["message"] == "Step 9 单播通知" for item in alice_notifications.json()["data"])

    baishan_notifications = client.get("/api/notifications/list", headers=baishan_headers)
    assert baishan_notifications.status_code == 200
    assert any(item["message"] == "Step 9 别名通知" for item in baishan_notifications.json()["data"])

    report_payload = {"targetType": "MARKET_ITEM", "targetId": 201, "reason": "疑似违规信息"}
    first_report = client.post("/api/reports", headers=alice_headers, json=report_payload)
    assert first_report.status_code == 200
    assert isinstance(first_report.json()["data"]["id"], int)

    duplicate_report = client.post("/api/reports", headers=alice_headers, json=report_payload)
    assert duplicate_report.status_code == 409
    assert duplicate_report.json()["msg"] == "已提交过举报"

    second_report = client.post("/api/reports", headers=baishan_headers, json=report_payload)
    assert second_report.status_code == 200

    third_report = client.post("/api/reports", headers=admin_headers, json=report_payload)
    assert third_report.status_code == 200

    hidden_market = client.get("/api/market/201")
    assert hidden_market.status_code == 404

    admin_reports = client.get(
        "/api/admin/reports",
        headers=admin_headers,
        params={"page": 0, "size": 20, "targetType": "MARKET_ITEM"},
    )
    assert admin_reports.status_code == 200
    report_items = admin_reports.json()["data"]["items"]
    latest_market_report = next(item for item in report_items if item["targetId"] == 201)
    assert latest_market_report["targetStatus"] == "HIDDEN"

    restore_response = client.patch(
        f"/api/admin/reports/{latest_market_report['id']}",
        headers=admin_headers,
        json={"status": "RESOLVED", "adminNote": "已人工复核", "restoreTarget": True},
    )
    assert restore_response.status_code == 200
    restored = restore_response.json()["data"]
    assert restored["status"] == "RESOLVED"
    assert restored["adminNote"] == "已人工复核"
    assert restored["targetStatus"] == "SALE"

    restored_market = client.get("/api/market/201")
    assert restored_market.status_code == 200


def test_deleting_reply_twice_decrements_parent_reply_count_once(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)

    parent = client.post("/api/comments", headers=alice_headers, json={"materialId": 101, "content": "父评论"})
    assert parent.status_code == 200
    parent_id = parent.json()["data"]["id"]
    replies = [
        client.post(
            "/api/comments",
            headers=baishan_headers,
            json={"materialId": 101, "parentId": parent_id, "content": content},
        )
        for content in ("回复一", "回复二")
    ]
    assert [reply.status_code for reply in replies] == [200, 200]
    reply_id = replies[0].json()["data"]["id"]

    assert client.delete(f"/api/comments/{reply_id}", headers=baishan_headers).status_code == 200
    assert client.delete(f"/api/comments/{reply_id}", headers=baishan_headers).status_code == 200

    with session_scope() as session:
        parent_record = session.get(CommentRecord, parent_id)
        assert parent_record is not None
        assert parent_record.reply_count == 1


def _material_state(material_id: int) -> tuple[str | None, str | None]:
    with session_scope() as session:
        material = session.get(MaterialRecord, material_id)
        assert material is not None
        return material.status, material.review_status


def test_resolved_reports_do_not_count_towards_auto_hide_after_restore(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    with session_scope() as session:
        extra_user = auth_service.create_local_user(
            session,
            username="reporter4",
            password="secret123",
            email="reporter4@example.com",
            verified=True,
            nickname="Reporter 4",
        )
        extra_user_id = int(extra_user.id)
    admin_headers = build_auth_headers(3, 8)
    report_payload = {"targetType": "MATERIAL", "targetId": 101, "reason": "疑似违规资料"}

    report_ids = []
    for user_id, role_mask in ((1, 1), (2, 2), (3, 8)):
        response = client.post("/api/reports", headers=build_auth_headers(user_id, role_mask), json=report_payload)
        assert response.status_code == 200
        report_ids.append(response.json()["data"]["id"])
    assert _material_state(101)[0] == "HIDDEN"

    for index, report_id in enumerate(report_ids):
        body = {"status": "RESOLVED", "restoreTarget": index == 0}
        assert client.patch(f"/api/admin/reports/{report_id}", headers=admin_headers, json=body).status_code == 200
    assert _material_state(101)[0] == "VISIBLE"

    fourth_report = client.post("/api/reports", headers=build_auth_headers(extra_user_id, 1), json=report_payload)

    assert fourth_report.status_code == 200
    assert _material_state(101)[0] == "VISIBLE"


def test_report_restore_keeps_security_held_material_hidden(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    with session_scope() as session:
        get_materials_service()._bootstrap(session)
    with session_scope() as session:
        material = session.get(MaterialRecord, 101)
        assert material is not None
        material.status = "HIDDEN"
        material.review_status = "SECURITY_PENDING"

    report = client.post(
        "/api/reports",
        headers=build_auth_headers(1, 1),
        json={"targetType": "MATERIAL", "targetId": 101, "reason": "疑似违规资料"},
    )
    assert report.status_code == 200

    restored = client.patch(
        f"/api/admin/reports/{report.json()['data']['id']}",
        headers=build_auth_headers(3, 8),
        json={"status": "RESOLVED", "restoreTarget": True},
    )

    assert restored.status_code == 200
    assert _material_state(101) == ("HIDDEN", "SECURITY_PENDING")


def test_report_auto_hide_invalidates_anonymous_market_cache(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    admin_headers = build_auth_headers(3, 8)

    # Warm the anonymous public-read cache for this market item before it is
    # auto-hidden below. Without invalidating that cache on auto-hide, the
    # next anonymous read would keep serving this stale (pre-hide) response
    # until the cache TTL expires instead of reflecting the hide immediately.
    warm = client.get("/api/market/201")
    assert warm.status_code == 200

    payload = {"targetType": "MARKET_ITEM", "targetId": 201, "reason": "缓存失效验证"}
    assert client.post("/api/reports", headers=alice_headers, json=payload).status_code == 200
    assert client.post("/api/reports", headers=baishan_headers, json=payload).status_code == 200
    assert client.post("/api/reports", headers=admin_headers, json=payload).status_code == 200

    hidden = client.get("/api/market/201")
    assert hidden.status_code == 404


def test_report_restore_invalidates_anonymous_market_cache(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    admin_headers = build_auth_headers(3, 8)

    payload = {"targetType": "MARKET_ITEM", "targetId": 201, "reason": "缓存失效验证"}
    assert client.post("/api/reports", headers=alice_headers, json=payload).status_code == 200
    assert client.post("/api/reports", headers=baishan_headers, json=payload).status_code == 200
    report = client.post("/api/reports", headers=admin_headers, json=payload)
    assert report.status_code == 200
    assert client.get("/api/market/201").status_code == 404

    # Warm the anonymous *list* cache while item 201 is hidden (a 404 detail
    # response is never cached -- see cache_if_anonymous_async/get_or_set_async,
    # which only memoizes successful factory() results -- so this must be a
    # 200 whose content changes once the restore below takes effect).
    warm_list = client.get("/api/market")
    assert warm_list.status_code == 200
    assert all(item["id"] != 201 for item in warm_list.json()["data"]["items"])

    restored = client.patch(
        f"/api/admin/reports/{report.json()['data']['id']}",
        headers=admin_headers,
        json={"status": "RESOLVED", "restoreTarget": True},
    )
    assert restored.status_code == 200
    assert restored.json()["data"]["targetStatus"] == "SALE"

    # Without invalidating the cache on restore, this would still return the
    # stale cached list (missing item 201) until the cache TTL expires.
    refreshed_list = client.get("/api/market")
    assert refreshed_list.status_code == 200
    assert any(item["id"] == 201 for item in refreshed_list.json()["data"]["items"])

    # The detail endpoint (a separate cache namespace) must also reflect the
    # restore immediately.
    assert client.get("/api/market/201").status_code == 200


def test_report_auto_hide_invalidates_anonymous_materials_cache(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    admin_headers = build_auth_headers(3, 8)

    warm = client.get("/api/materials/101")
    assert warm.status_code == 200

    payload = {"targetType": "MATERIAL", "targetId": 101, "reason": "缓存失效验证"}
    assert client.post("/api/reports", headers=alice_headers, json=payload).status_code == 200
    assert client.post("/api/reports", headers=baishan_headers, json=payload).status_code == 200
    assert client.post("/api/reports", headers=admin_headers, json=payload).status_code == 200

    # Without invalidating on auto-hide, this would still return the stale
    # cached (pre-hide) 200 response until the cache TTL expires.
    hidden = client.get("/api/materials/101")
    assert hidden.status_code == 404


def test_report_auto_hide_invalidates_anonymous_comments_cache(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    # Exercises the COMMENT branch of /api/reports directly (as opposed to
    # /api/comments/{id}/report, covered separately below).
    seed_read_users(auth_service)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    admin_headers = build_auth_headers(3, 8)

    created = client.post(
        "/api/comments",
        headers=alice_headers,
        json={"materialId": 101, "content": "缓存失效验证评论"},
    )
    assert created.status_code == 200
    comment_id = created.json()["data"]["id"]

    warm = client.get("/api/comments", params={"materialId": 101})
    assert warm.status_code == 200
    assert any(item["id"] == comment_id for item in warm.json()["data"]["items"])

    payload = {"targetType": "COMMENT", "targetId": comment_id, "reason": "缓存失效验证"}
    assert client.post("/api/reports", headers=alice_headers, json=payload).status_code == 200
    assert client.post("/api/reports", headers=baishan_headers, json=payload).status_code == 200
    assert client.post("/api/reports", headers=admin_headers, json=payload).status_code == 200

    # Without invalidating on auto-hide, this would still return the stale
    # cached list still including the now-hidden comment.
    refreshed = client.get("/api/comments", params={"materialId": 101})
    assert refreshed.status_code == 200
    assert all(item["id"] != comment_id for item in refreshed.json()["data"]["items"])


def test_comment_report_route_invalidates_anonymous_comments_cache(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    # Same as above but through /api/comments/{id}/report (CommentsService.report),
    # a separate entry point into the same auto-hide path.
    seed_read_users(auth_service)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    admin_headers = build_auth_headers(3, 8)

    created = client.post(
        "/api/comments",
        headers=alice_headers,
        json={"materialId": 101, "content": "缓存失效验证评论二"},
    )
    assert created.status_code == 200
    comment_id = created.json()["data"]["id"]

    warm = client.get("/api/comments", params={"materialId": 101})
    assert warm.status_code == 200
    assert any(item["id"] == comment_id for item in warm.json()["data"]["items"])

    report_payload = {"reason": "缓存失效验证"}
    assert client.post(f"/api/comments/{comment_id}/report", headers=alice_headers, json=report_payload).status_code == 200
    assert client.post(f"/api/comments/{comment_id}/report", headers=baishan_headers, json=report_payload).status_code == 200
    assert client.post(f"/api/comments/{comment_id}/report", headers=admin_headers, json=report_payload).status_code == 200

    refreshed = client.get("/api/comments", params={"materialId": 101})
    assert refreshed.status_code == 200
    assert all(item["id"] != comment_id for item in refreshed.json()["data"]["items"])
