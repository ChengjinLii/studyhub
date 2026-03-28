from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.db import session_scope
from app.services.auth_service import AuthService
from tests.support import authenticate_client, build_auth_headers, seed_read_users


def test_step7_me_account_patch_matches_java_cookie_and_profile_semantics(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    authenticate_client(client, user_id=1, remember_me=True)

    account_response = client.get("/api/me/account")
    assert account_response.status_code == 200
    account_data = account_response.json()["data"]
    assert account_data["purchaseCount"] == 1
    assert account_data["saleCount"] == 1
    assert account_data["gradeStages"] == ["大三"]

    patch_response = client.patch(
        "/api/me/account",
        json={
            "nickname": "   ",
            "emailPrivacy": True,
            "signature": "  这是新的 Markdown 签名  ",
            "school": "电子科技大学",
            "college": "信通",
            "major": "通信",
            "gradeStages": ["大一", "大二", "大二", "  "],
        },
    )
    assert patch_response.status_code == 200
    patch_data = patch_response.json()["data"]
    assert patch_data["nickname"] == "alice"
    assert patch_data["emailPrivacy"] is True
    assert patch_data["signature"] == "这是新的 Markdown 签名"
    assert patch_data["school"] == "电子科技大学"
    assert patch_data["college"] == "信通"
    assert patch_data["major"] == "通信"
    assert patch_data["gradeStages"] == ["大一", "大二"]
    assert patch_data["purchaseCount"] == 1
    assert patch_data["saleCount"] == 1

    refreshed_headers = patch_response.headers.get_list("set-cookie")
    assert any("studyhub_token=" in header and "Max-Age=604800" in header for header in refreshed_headers)
    assert any("studyhub_user=" in header and "Max-Age=604800" in header for header in refreshed_headers)
    assert all("Secure" not in header for header in refreshed_headers)

    session_response = client.get("/api/session")
    assert session_response.status_code == 200
    session_user = session_response.json()["data"]["user"]
    assert session_user["nickname"] == "alice"
    assert session_user["emailPrivacy"] is True

    with session_scope() as session:
        user = auth_service.repo.find_user_by_id(session, 1)
        assert user is not None
        assert user.nickname == "alice"
        assert user.signature == "这是新的 Markdown 签名"
        assert user.grade_stages == "大一,大二"


def test_step7_profile_update_and_follow_endpoints_match_java_ordering_and_idempotency(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)

    invalid_school = client.patch("/api/me/account", json={"school": "清华大学"}, headers=alice_headers)
    assert invalid_school.status_code == 400
    assert invalid_school.json()["msg"] == "当前仅支持电子科技大学"

    invalid_grade_count = client.patch(
        "/api/me/account",
        json={"gradeStages": ["大一", "大二", "大三", "大四", "研究生", "英语", "技能", "大一"]},
        headers=alice_headers,
    )
    assert invalid_grade_count.status_code == 400
    assert invalid_grade_count.json()["msg"] == "Value error, 年级/阶段最多选择 7 项"

    followers_response = client.get("/api/users/2/followers", headers=alice_headers)
    assert followers_response.status_code == 200
    assert [item["id"] for item in followers_response.json()["data"]] == [3, 1]

    following_response = client.get("/api/users/1/following", headers=alice_headers)
    assert following_response.status_code == 200
    assert [item["id"] for item in following_response.json()["data"]] == [2]

    duplicate_follow = client.post("/api/users/2/follow", headers=alice_headers)
    assert duplicate_follow.status_code == 200
    duplicate_followers = client.get("/api/users/2/followers", headers=alice_headers)
    assert [item["id"] for item in duplicate_followers.json()["data"]] == [3, 1]

    self_follow = client.post("/api/users/1/follow", headers=alice_headers)
    assert self_follow.status_code == 400
    assert self_follow.json()["msg"] == "不能关注自己"

    new_follow = client.post("/api/users/3/follow", headers=alice_headers)
    assert new_follow.status_code == 200
    updated_following = client.get("/api/users/1/following", headers=alice_headers)
    assert [item["id"] for item in updated_following.json()["data"]] == [3, 2]

    public_profile = client.get("/api/users/3/profile", headers=alice_headers)
    assert public_profile.status_code == 200
    profile_data = public_profile.json()["data"]
    assert profile_data["followersCount"] == 1
    assert profile_data["followingCount"] == 1
    assert profile_data["isFollowing"] is True

    delete_follow = client.delete("/api/users/3/follow", headers=alice_headers)
    assert delete_follow.status_code == 200
    delete_follow_again = client.delete("/api/users/3/follow", headers=alice_headers)
    assert delete_follow_again.status_code == 200
    restored_following = client.get("/api/users/1/following", headers=alice_headers)
    assert [item["id"] for item in restored_following.json()["data"]] == [2]


def test_step7_free_download_and_creator_metrics_keep_exact_current_semantics(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)

    with session_scope() as session:
        user = auth_service.repo.find_user_by_id(session, 1)
        assert user is not None
        user.free_download_quota = None

    alice_headers = build_auth_headers(1, 1)
    admin_headers = build_auth_headers(3, 8)
    baishan_headers = build_auth_headers(2, 2)

    free_download_response = client.get("/api/free-download/status", headers=alice_headers)
    assert free_download_response.status_code == 200
    assert free_download_response.json()["data"] == {"remaining": 200, "unlimited": False}

    admin_free_download = client.get("/api/free-download/status", headers=admin_headers)
    assert admin_free_download.status_code == 200
    assert admin_free_download.json()["data"] == {"remaining": 2147483647, "unlimited": True}

    creator_metrics_response = client.get("/api/creator/metrics", headers=baishan_headers)
    assert creator_metrics_response.status_code == 200
    assert creator_metrics_response.json()["data"] == {
        "nextPayoutDate": "2026-03-31T10:00:00+00:00",
        "countdown": "P6DT18H1S",
        "weekSales": 3,
        "weekGross": 49.9,
        "weekNet": 42.41,
        "commissionRate": 0.15,
    }
