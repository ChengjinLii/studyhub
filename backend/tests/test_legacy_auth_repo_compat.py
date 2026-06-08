from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.repos.finance_repo import FinanceRepository
from app.repos.market_repo import MarketRepository
from app.repos.material_repo import MaterialRepository
from app.services.user_read_service import UserReadService
from app.repos.auth_repo import AuthRepository
from app.repos.read_api_repo import ReadApiRepository
from app.repos.user_follow_repo import UserFollowRepository
from app.services.user_follow_service import UserFollowService


def _build_legacy_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE users (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  openid VARCHAR(128),
                  unionid VARCHAR(128),
                  nickname VARCHAR(100) NOT NULL,
                  avatar VARCHAR(255),
                  role_mask INTEGER NOT NULL DEFAULT 1,
                  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  username VARCHAR(191),
                  password_hash VARCHAR(255),
                  email VARCHAR(255),
                  verified BOOLEAN NOT NULL DEFAULT 0,
                  free_download_quota INTEGER NOT NULL DEFAULT 200,
                  last_checkin_at TIMESTAMP,
                  notification_read_at TIMESTAMP,
                  market_event_read_at TIMESTAMP,
                  unique_downloaders INTEGER NOT NULL DEFAULT 0,
                  email_privacy BOOLEAN NOT NULL DEFAULT 0,
                  signature VARCHAR(300),
                  school VARCHAR(120),
                  college VARCHAR(120),
                  major VARCHAR(120),
                  status VARCHAR(20) NOT NULL DEFAULT 'active',
                  grade_stages VARCHAR(255),
                  legendary_contributor_until TIMESTAMP,
                  payout_qr_key VARCHAR(255)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE materials (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title VARCHAR(80) NOT NULL,
                  description TEXT,
                  price INTEGER NOT NULL DEFAULT 0,
                  is_free BOOLEAN NOT NULL DEFAULT 0,
                  file_key VARCHAR(255),
                  original_filename VARCHAR(255),
                  school VARCHAR(120) NOT NULL,
                  college VARCHAR(120),
                  major VARCHAR(120),
                  is_general_education BOOLEAN NOT NULL DEFAULT 0,
                  grade_type VARCHAR(10) NOT NULL DEFAULT 'UG',
                  grade_value VARCHAR(40) NOT NULL DEFAULT '大一',
                  keywords VARCHAR(255),
                  status VARCHAR(32) NOT NULL DEFAULT 'approved',
                  review_status VARCHAR(32) NOT NULL DEFAULT 'auto-approved',
                  description_md_key VARCHAR(255),
                  preview_manifest TEXT,
                  encryption_password VARCHAR(64),
                  suspicious_score NUMERIC(5,2) NOT NULL DEFAULT 0.00,
                  suspicious_reason VARCHAR(255),
                  promo_code VARCHAR(32),
                  uploader_id INTEGER,
                  file_hash VARCHAR(128),
                  download_count INTEGER NOT NULL DEFAULT 0,
                  sales_count INTEGER NOT NULL DEFAULT 0,
                  rating_avg NUMERIC(4,2) NOT NULL DEFAULT 0.00,
                  rating_count INTEGER NOT NULL DEFAULT 0,
                  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  like_count INTEGER DEFAULT 0,
                  file_type VARCHAR(32) NOT NULL DEFAULT 'zip',
                  course_category VARCHAR(32) NOT NULL DEFAULT 'MAJOR',
                  file_size INTEGER DEFAULT 0,
                  netdisk_url VARCHAR(512),
                  netdisk_password VARCHAR(128),
                  netdisk_expired_at DATE,
                  netdisk_reminder_at DATE,
                  delivery_method VARCHAR(20) NOT NULL DEFAULT 'FILE',
                  gram_count INTEGER NOT NULL DEFAULT 0,
                  preview_watermark_enabled BOOLEAN NOT NULL DEFAULT 1,
                  preview_source VARCHAR(16) NOT NULL DEFAULT 'AUTO',
                  deleted_at TIMESTAMP,
                  custom_preview_text TEXT,
                  custom_preview_images TEXT,
                  view_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE market_items (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  seller_id INTEGER NOT NULL,
                  title VARCHAR(120) NOT NULL,
                  description TEXT,
                  price INTEGER NOT NULL,
                  category VARCHAR(32) NOT NULL,
                  images_json TEXT NOT NULL,
                  contact_type VARCHAR(16) NOT NULL,
                  contact_value VARCHAR(128) NOT NULL,
                  want_count INTEGER NOT NULL DEFAULT 0,
                  status VARCHAR(16) NOT NULL DEFAULT 'SALE',
                  school VARCHAR(64),
                  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE user_follows (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  follower_id INTEGER NOT NULL,
                  following_id INTEGER NOT NULL,
                  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO users (
                  id, username, email, password_hash, nickname, role_mask, verified, free_download_quota,
                  email_privacy, status, signature, school, college, major, grade_stages, avatar
                ) VALUES
                  (1, 'alice', 'alice@example.com', 'hash-a', 'Alice', 1, 1, 7, 0, 'active', 'hello', '电子科技大学', '信通', '通信', '大三', '/a.png'),
                  (2, 'baishan', 'baishan@example.com', 'hash-b', '白山', 2, 1, 12, 1, 'active', 'world', '电子科技大学', '格院', '微电子', '大四', '/b.png')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO materials (
                  id, title, description, price, is_free, file_key, original_filename, school, college, major,
                  is_general_education, grade_type, grade_value, keywords, status, review_status,
                  uploader_id, download_count, sales_count, rating_avg, rating_count, created_at, updated_at,
                  like_count, file_type, course_category, file_size, delivery_method, preview_watermark_enabled, preview_source, view_count
                ) VALUES
                  (11, '通信原理笔记', 'desc', 199, 0, 'materials/11.zip', '通信原理.zip', '电子科技大学', '格院', '微电子',
                   0, 'UG', '大四', '通信', 'approved', 'auto-approved',
                   2, 15, 2, 4.5, 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 3, 'zip', 'MAJOR', 1024, 'FILE', 1, 'AUTO', 20)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO market_items (
                  id, seller_id, title, description, price, category, images_json, contact_type, contact_value,
                  want_count, status, school, created_at, updated_at
                ) VALUES
                  (21, 2, '二手示波器', 'desc', 8800, 'OTHER', '[]', 'wechat', 'demo-wechat',
                   4, 'SALE', '电子科技大学', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
        )
    return Session(engine)


def test_auth_repository_uses_legacy_users_table_when_auth_users_is_missing() -> None:
    repo = AuthRepository()
    with _build_legacy_session() as session:
        alice = repo.find_user_by_id(session, 1)
        assert alice is not None
        assert alice.username == "alice"
        assert repo.find_user_by_username(session, "alice") is not None
        assert repo.find_user_by_email(session, "baishan@example.com") is not None
        assert repo.count_users(session) == 2

        alice.signature = "updated"
        repo.save_user(session, alice)
        session.commit()
        session.refresh(alice)
        assert repo.find_user_by_id(session, 1).signature == "updated"

        charlie = repo.build_user(
            session,
            username="charlie",
            email="charlie@example.com",
            password_hash="hash-c",
            nickname="Charlie",
            role_mask=1,
            verified=True,
            free_download_quota=5,
            email_privacy=False,
            status="active",
        )
        repo.save_user(session, charlie)
        session.commit()
        assert charlie.id is not None
        assert repo.find_user_by_username(session, "charlie") is not None


def test_user_follow_service_works_with_legacy_users_table() -> None:
    auth_repo = AuthRepository()
    follow_repo = UserFollowRepository()
    service = UserFollowService(follow_repo, auth_repo)

    with _build_legacy_session() as session:
        service.follow(session, follower_id=1, target_user_id=2)

        assert service.is_following(session, follower_id=1, target_user_id=2) is True
        assert service.count_followers(session, 2) == 1
        assert service.count_following(session, 1) == 1

        followers = service.list_followers(session, 2)
        assert [item["id"] for item in followers] == [1]
        assert followers[0]["username"] == "alice"

        following = service.list_following(session, 1)
        assert [item["id"] for item in following] == [2]

        service.unfollow(session, follower_id=1, target_user_id=2)
        assert service.is_following(session, follower_id=1, target_user_id=2) is False


def test_user_read_service_builds_public_profile_against_legacy_users_schema() -> None:
    auth_repo = AuthRepository()
    follow_repo = UserFollowRepository()
    follow_service = UserFollowService(follow_repo, auth_repo)

    class DummyReadRepo:
        def load_seed(self):
            return {}

    service = UserReadService(
        DummyReadRepo(),
        auth_repo,
        follow_service,
        MaterialRepository(),
        MarketRepository(),
        FinanceRepository(),
    )

    with _build_legacy_session() as session:
        follow_service.follow(session, follower_id=1, target_user_id=2)
        profile = service.get_public_profile(session, viewer_id=1, viewer_role_mask=1, target_user_id=2)
        assert profile["id"] == 2
        assert profile["followersCount"] == 1
        assert profile["followingCount"] == 0
        assert profile["isFollowing"] is True
        assert profile["uploadCount"] == 1
        assert profile["marketCount"] == 1
        assert profile["saleCount"] == 1
        assert profile["recentUploads"][0]["title"] == "通信原理笔记"
        assert profile["recentUploads"][0]["tags"] == []
        assert profile["recentMarketListings"][0]["title"] == "二手示波器"
