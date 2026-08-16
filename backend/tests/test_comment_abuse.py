from __future__ import annotations

import pytest

from app.core.comment_abuse import (
    clear_comment_abuse_state,
    enforce_comment_user_rate_limit,
    release_comment_content,
    reserve_comment_content,
)
from app.core.config import Settings
from app.core.exceptions import BizException
from app.core.rate_limit import get_rate_limiter


@pytest.fixture(autouse=True)
def clear_abuse_state() -> None:
    get_rate_limiter().clear()
    clear_comment_abuse_state()
    yield
    get_rate_limiter().clear()
    clear_comment_abuse_state()


def test_comment_create_rate_limit_is_isolated_by_user() -> None:
    settings = Settings(
        rate_limit_backend="local",
        rate_limit_comment_create_user_minute=2,
        rate_limit_comment_create_user_hour=20,
    )

    enforce_comment_user_rate_limit(settings, user_id=7, action="create")
    enforce_comment_user_rate_limit(settings, user_id=7, action="create")

    with pytest.raises(BizException) as caught:
        enforce_comment_user_rate_limit(settings, user_id=7, action="create")

    assert caught.value.code == "COMMENT_RATE_LIMITED"
    assert caught.value.status_code == 429
    enforce_comment_user_rate_limit(settings, user_id=8, action="create")


def test_comment_actions_use_independent_buckets() -> None:
    settings = Settings(rate_limit_backend="local", rate_limit_comment_action_user_minute=1)

    enforce_comment_user_rate_limit(settings, user_id=7, action="like")
    enforce_comment_user_rate_limit(settings, user_id=7, action="update")

    with pytest.raises(BizException):
        enforce_comment_user_rate_limit(settings, user_id=7, action="like")


def test_comment_read_only_switch_blocks_writes_without_affecting_read_routes() -> None:
    settings = Settings(comments_write_enabled=False)

    with pytest.raises(BizException) as caught:
        enforce_comment_user_rate_limit(settings, user_id=7, action="create")

    assert caught.value.code == "COMMENTS_READ_ONLY"
    assert caught.value.status_code == 503


def test_duplicate_comment_reservation_normalizes_whitespace_and_can_be_released() -> None:
    settings = Settings(
        rate_limit_backend="local",
        rate_limit_comment_duplicate_seconds=300,
    )
    reservation = reserve_comment_content(
        settings,
        user_id=7,
        material_id=41,
        parent_id=None,
        content="同一条   评论",
    )

    with pytest.raises(BizException) as caught:
        reserve_comment_content(
            settings,
            user_id=7,
            material_id=41,
            parent_id=None,
            content="同一条 评论",
        )

    assert caught.value.code == "COMMENT_DUPLICATE"
    assert caught.value.status_code == 409
    release_comment_content(reservation)
    assert reserve_comment_content(
        settings,
        user_id=7,
        material_id=41,
        parent_id=None,
        content="同一条 评论",
    ) is not None


def test_duplicate_comment_scope_keeps_users_and_reply_threads_separate() -> None:
    settings = Settings(rate_limit_backend="local", rate_limit_comment_duplicate_seconds=300)

    assert reserve_comment_content(
        settings,
        user_id=7,
        material_id=41,
        parent_id=None,
        content="可以复用的回复文本",
    ) is not None
    assert reserve_comment_content(
        settings,
        user_id=8,
        material_id=41,
        parent_id=None,
        content="可以复用的回复文本",
    ) is not None
    assert reserve_comment_content(
        settings,
        user_id=7,
        material_id=41,
        parent_id=9,
        content="可以复用的回复文本",
    ) is not None
