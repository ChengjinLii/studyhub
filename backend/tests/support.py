from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_auth_cookie_service, get_auth_repo, get_token_codec
from app.core.config import get_settings
from app.core.db import session_scope
from app.models.finance import OrderRecord, PaymentRecord, PayoutTransferRecord
from app.models.materials import MaterialRecord
from app.repos.finance_repo import FinanceRepository
from app.repos.material_repo import MaterialRepository
from app.repos.read_api_repo import ReadApiRepository
from app.repos.user_follow_repo import UserFollowRepository
from app.services.auth_service import AuthService


def seed_read_users(auth_service: AuthService, *, with_follow_graph: bool = False) -> None:
    with session_scope() as session:
        alice = auth_service.create_local_user(
            session,
            username="alice",
            password="secret123",
            email="alice@example.com",
            verified=True,
            nickname="Alice Chen",
        )
        baishan = auth_service.create_local_user(
            session,
            username="baishan",
            password="secret123",
            email="baishan@example.com",
            verified=True,
            nickname="白山",
        )
        admin = auth_service.create_local_user(
            session,
            username="admin",
            password="secret123",
            email="admin@example.com",
            verified=True,
            nickname="超级管理员",
        )

        alice.school = "电子科技大学"
        alice.college = "信通"
        alice.major = "通信"
        alice.grade_stages = "大三"
        alice.free_download_quota = 7

        baishan.school = "电子科技大学"
        baishan.college = "格院"
        baishan.major = "微电子"
        baishan.grade_stages = "大四"
        baishan.email_privacy = True
        baishan.role_mask = 2
        baishan.free_download_quota = 12
        baishan.signature = "### 分享优先\n\n资料、经验分享和校园集市都在维护。"

        admin.school = "电子科技大学"
        admin.college = "信通"
        admin.major = "电工"
        admin.grade_stages = "研究生"
        admin.role_mask = 8
        admin.free_download_quota = None

        if with_follow_graph:
            follow_repo = UserFollowRepository()

            follow_1 = follow_repo.create(session, follower_id=alice.id, following_id=baishan.id)
            follow_1.created_at = datetime(2026, 3, 20, 1, 0, tzinfo=UTC)

            follow_2 = follow_repo.create(session, follower_id=baishan.id, following_id=alice.id)
            follow_2.created_at = datetime(2026, 3, 20, 2, 0, tzinfo=UTC)

            follow_3 = follow_repo.create(session, follower_id=admin.id, following_id=baishan.id)
            follow_3.created_at = datetime(2026, 3, 20, 3, 0, tzinfo=UTC)


def build_auth_headers(user_id: int, role_mask: int) -> dict[str, str]:
    token = get_token_codec().encode({"sub": str(user_id), "roleMask": role_mask}, ttl_seconds=3600)
    return {"Authorization": f"Bearer {token}"}


def authenticate_client(client: TestClient, *, user_id: int, remember_me: bool) -> None:
    auth_cookie_service = get_auth_cookie_service()
    repo = get_auth_repo()
    with session_scope() as session:
        user = repo.find_user_by_id(session, user_id)
        assert user is not None
        payload = auth_cookie_service.build_auth_response(user, remember_me)
    client.cookies.set("studyhub_token", payload["token"])
    client.cookies.set("studyhub_user", json.dumps(payload["user"], ensure_ascii=False, separators=(",", ":")))


def prepare_contract_diff_state(auth_service: AuthService) -> None:
    """
    为 Step 12 contract diff 准备最小但稳定的前置状态。

    这里显式创建当前仓库内需要的本地用户、支付记录和二进制资产，
    避免 contract 样本运行时去依赖外部 Spring Boot 仓库或外部服务。
    """

    seed_read_users(auth_service, with_follow_graph=False)

    settings = get_settings()
    material_repo = MaterialRepository()
    read_repo = ReadApiRepository(settings.resolved_read_api_seed_path)
    finance_repo = FinanceRepository()

    with session_scope() as session:
        material_repo.ensure_seed_bootstrap(session, read_repo.load_seed())
        alice = get_auth_repo().find_user_by_id(session, 1)
        if alice is not None:
            alice.signature = "热衷整理通信课程资料，也会在集市淘点好物。"
            alice.college = "信息与通信工程学院"
            alice.major = "通信工程"
            alice.legendary_contributor_until = datetime.fromisoformat("2026-12-31T00:00:00+08:00")
            get_auth_repo().save_user(session, alice)
        _seed_hidden_download_material(session, material_repo, settings.resolved_material_asset_dir)
        _seed_payment_contract_rows(session, finance_repo)
        _seed_gateway_transfer(session, finance_repo)


def _seed_hidden_download_material(session, material_repo: MaterialRepository, asset_root: Path) -> None:
    material_id = 990
    relative_key = "990/file/contract-sample.pdf"
    target = asset_root / relative_key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"%PDF-1.4\nstudyhub-step12\n%%EOF\n")

    if material_repo.get_material(session, material_id) is not None:
        return

    material = MaterialRecord(
        id=material_id,
        source="local",
        uploader_id=1,
        uploader_username="alice",
        uploader_nickname="Alice Chen",
        title="Step 12 Contract Asset",
        description="binary/download contract fixture",
        original_filename="合同样本.pdf",
        file_storage_key=relative_key,
        file_type="pdf",
        file_size=31,
        price=0,
        is_free=True,
        school="电子科技大学",
        college="信息与通信工程学院",
        major="通信工程",
        general_course=False,
        course_category="MAJOR",
        grade_type="STAGE",
        grade_value="大三",
        delivery_method="FILE",
        preview_watermark_enabled=True,
        preview_source="AUTO",
        status="HIDDEN",
        review_status="APPROVED",
    )
    material_repo.save_material(session, material)


def _seed_payment_contract_rows(session, finance_repo: FinanceRepository) -> None:
    if finance_repo.find_order_by_out_trade_no(session, "ODSTEP12PAY0001") is not None:
        return

    order = OrderRecord(
        user_id=2,
        material_id=104,
        uploader_id=1,
        material_title="信号与系统复习导图",
        status="CREATED",
        amount=100,
        channel="alipay_page",
        pay_channel="alipay_page",
        out_trade_no="ODSTEP12PAY0001",
        commission_rate=0.3,
        platform_fee_amount=30,
        creator_payable_amount=70,
        policy_version="MARKET_FASTAPI_V1",
    )
    finance_repo.save_order(session, order)
    payment = PaymentRecord(
        order_id=order.id,
        channel="alipay_page",
        out_trade_no="ODSTEP12PAY0001",
        amount=100,
        status="CREATED",
    )
    finance_repo.save_payment(session, payment)


def _seed_gateway_transfer(session, finance_repo: FinanceRepository) -> None:
    if finance_repo.find_transfer_by_out_biz_no(session, "PTSTEP12BIZ0001") is not None:
        return

    transfer = PayoutTransferRecord(
        payout_application_id=1,
        uploader_id=1,
        out_biz_no="PTSTEP12BIZ0001",
        amount=1850,
        payee_account="alice@example.com",
        payee_name="Alice Chen",
        status="SUBMITTED",
    )
    finance_repo.save_payout_transfer(session, transfer)
