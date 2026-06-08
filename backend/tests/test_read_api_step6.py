from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_user_read_service
from app.core.db import session_scope
from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users


def test_step6_public_read_endpoints_follow_expected_shapes(client: TestClient) -> None:
    materials_response = client.get("/api/materials", params={"page": 1, "size": 2})
    assert materials_response.status_code == 200
    materials_data = materials_response.json()["data"]
    assert materials_data["meta"] == {"page": 1, "size": 2, "total": 4}
    assert materials_data["items"][0]["id"] == 101
    assert "originalFilename" not in materials_data["items"][0]
    assert materials_data["stats"]["userCount"] == 3
    assert materials_data["availableTags"] == ["一页纸", "保研面经", "期末真题", "期末答案（自制解析）", "期末速成", "经验分享"]

    detail_response = client.get("/api/materials/101")
    assert detail_response.status_code == 200
    detail_data = detail_response.json()["data"]
    assert detail_data["originalFilename"] == "数据结构-期末真题解析.pdf"
    assert detail_data["purchased"] is True
    assert detail_data["liked"] is False

    leaderboard_response = client.get("/api/leaderboard/contributors", params={"limit": 2, "period": "all"})
    assert leaderboard_response.status_code == 200
    assert leaderboard_response.json()["data"] == [
        {"userId": 2, "username": "baishan", "downloads": 298, "roleMask": 2},
        {"userId": 1, "username": "alice", "downloads": 84, "roleMask": 1},
    ]

    market_response = client.get("/api/market", params={"page": 1})
    assert market_response.status_code == 200
    market_data = market_response.json()["data"]
    assert market_data["meta"] == {"page": 1, "size": 20, "total": 2}
    assert market_data["stats"] == {"active": 1, "sold": 1, "userCount": 3}
    assert market_data["items"][0]["id"] == 201

    market_detail_response = client.get("/api/market/201")
    assert market_detail_response.status_code == 200
    market_detail = market_detail_response.json()["data"]
    assert market_detail["canViewContact"] is False
    assert market_detail["contactType"] is None
    assert market_detail["contactValue"] is None
    assert "thumbnail" not in market_detail

    comments_response = client.get("/api/comments", params={"materialId": 101, "sort": "latest", "page": 0, "size": 20})
    assert comments_response.status_code == 200
    comments_data = comments_response.json()["data"]
    assert comments_data["meta"] == {"page": 0, "size": 20, "total": 2}
    assert [item["id"] for item in comments_data["items"]] == [9002, 9001]

    replies_response = client.get("/api/comments/9001/replies", params={"page": 0, "size": 20})
    assert replies_response.status_code == 200
    replies_data = replies_response.json()["data"]
    assert replies_data["items"][0]["id"] == 9101
    assert replies_data["meta"] == {"page": 0, "size": 20, "total": 1}

    requests_response = client.get("/api/requests", params={"sort": "hot", "limit": 0})
    assert requests_response.status_code == 200
    requests_data = requests_response.json()["data"]
    assert [item["id"] for item in requests_data] == [401, 402]
    assert requests_data[1]["requesterName"] is None


def test_step6_authenticated_read_endpoints_follow_expected_shapes(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)

    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)

    me_response = client.get("/api/me", headers=alice_headers)
    assert me_response.status_code == 200
    me_data = me_response.json()["data"]
    assert me_data["freeDownloadStatus"] == {"remaining": 7, "unlimited": False}
    assert me_data["uploads"][0]["materialId"] == 104
    assert me_data["marketWants"][0]["itemId"] == 201

    profile_response = client.get("/api/users/2/profile", headers=alice_headers)
    assert profile_response.status_code == 200
    profile_data = profile_response.json()["data"]
    assert profile_data["nickname"] == "白山"
    assert profile_data["email"] is None
    assert profile_data["isFollowing"] is True
    assert profile_data["followersCount"] == 2
    assert profile_data["uploadCount"] == 3
    assert profile_data["marketCount"] == 1
    assert [item["materialId"] for item in profile_data["recentUploads"]] == [101, 103, 102]
    assert profile_data["recentUploads"][0]["tags"] == ["期末真题", "期末答案（自制解析）"]

    uploads_response = client.get("/api/users/2/uploads", params={"limit": 1}, headers=alice_headers)
    assert uploads_response.status_code == 200
    assert uploads_response.json()["data"] == [
        {
            "materialId": 101,
            "title": "数据结构期末真题解析",
            "status": "VISIBLE",
            "free": True,
            "price": 0.0,
            "salesCount": 0,
            "downloadCount": 128,
            "createdAt": "2026-03-18T18:00:00+08:00",
            "commentCount": 2,
            "likeCount": 31,
            "tags": ["期末真题", "期末答案（自制解析）"],
        }
    ]

    user_market_response = client.get("/api/users/2/market", headers=alice_headers)
    assert user_market_response.status_code == 200
    assert user_market_response.json()["data"][0]["itemId"] == 201

    wanted_response = client.get("/api/market/wanted", headers=alice_headers)
    assert wanted_response.status_code == 200
    assert wanted_response.json()["data"] == [201]

    market_detail_response = client.get("/api/market/201", headers=alice_headers)
    assert market_detail_response.status_code == 200
    market_detail = market_detail_response.json()["data"]
    assert market_detail["wanted"] is True
    assert market_detail["canViewContact"] is True
    assert market_detail["contactValue"] == "wx-baishan-01"

    personalized_recommendations = client.get("/api/materials/recommendations", params={"limit": 2}, headers=alice_headers)
    assert personalized_recommendations.status_code == 200
    assert [item["id"] for item in personalized_recommendations.json()["data"]] == [102, 104]

    comments_response = client.get(
        "/api/comments",
        params={"materialId": 101, "sort": "latest", "page": 0, "size": 20},
        headers=alice_headers,
    )
    assert comments_response.status_code == 200
    assert comments_response.json()["data"]["items"][0]["hasLiked"] is True

    requests_response = client.get("/api/requests", params={"sort": "hot"}, headers=alice_headers)
    assert requests_response.status_code == 200
    assert requests_response.json()["data"][0]["responded"] is True

    request_detail_response = client.get("/api/requests/401", headers=alice_headers)
    assert request_detail_response.status_code == 200
    assert request_detail_response.json()["data"]["owner"] is False

    responses_response = client.get("/api/requests/401/responses", headers=alice_headers)
    assert responses_response.status_code == 200
    assert [item["id"] for item in responses_response.json()["data"]] == [6101, 6102]

    contributions_response = client.get("/api/requests/401/contributions", headers=alice_headers)
    assert contributions_response.status_code == 200
    assert [item["id"] for item in contributions_response.json()["data"]] == [6202, 6201]

    free_download_response = client.get("/api/free-download/status", headers=alice_headers)
    assert free_download_response.status_code == 200
    assert free_download_response.json()["data"] == {"remaining": 7, "unlimited": False}

    creator_metrics_response = client.get("/api/creator/metrics", headers=baishan_headers)
    assert creator_metrics_response.status_code == 200
    creator_metrics = creator_metrics_response.json()["data"]
    assert creator_metrics["weekSales"] == 3
    assert creator_metrics["commissionRate"] == 0.15
    assert creator_metrics["countdown"].startswith("P")


def test_step6_login_boundaries_match_java_style_401(client: TestClient) -> None:
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/users/2/profile").status_code == 401
    assert client.get("/api/market/wanted").status_code == 401
    assert client.get("/api/requests/401").status_code == 401
    assert client.get("/api/free-download/status").status_code == 401
    assert client.get("/api/creator/metrics").status_code == 401


def test_public_profile_counts_do_not_load_full_collections(client: TestClient, monkeypatch) -> None:
    _ = client
    service = get_user_read_service()
    original_uploads = service.get_user_uploads
    original_market = service.get_user_market_listings

    def guarded_uploads(session, viewer_id, target_user_id, viewer_role_mask, limit):
        if limit is None:
            raise AssertionError("public profile uploadCount should use count query")
        return original_uploads(session, viewer_id, target_user_id, viewer_role_mask, limit)

    def guarded_market(session, viewer_id, target_user_id, viewer_role_mask, limit):
        if limit is None:
            raise AssertionError("public profile marketCount should use count query")
        return original_market(session, viewer_id, target_user_id, viewer_role_mask, limit)

    monkeypatch.setattr(service, "get_user_uploads", guarded_uploads)
    monkeypatch.setattr(service, "get_user_market_listings", guarded_market)

    with session_scope() as session:
        profile = service.get_public_profile(session, viewer_id=1, viewer_role_mask=1, target_user_id=2)

    assert profile["uploadCount"] == 3
    assert profile["marketCount"] == 1
