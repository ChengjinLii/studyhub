from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.finance import OrderRecord, PaymentNotificationRecord, PaymentRecord
from app.models.materials import MaterialRecord
from app.providers.payment import PaymentGatewayProvider
from app.repos.auth_repo import AuthRepository
from app.repos.finance_repo import FinanceRepository
from app.repos.material_repo import MaterialRepository
from app.repos.read_api_repo import ReadApiRepository
from app.services.requests_service import RequestsService


PAID_ORDER_STATUSES = {"PAID"}
VISIBLE_MATERIAL_STATUSES = {"VISIBLE", "APPROVED", "PUBLISHED"}
ALIPAY_SUCCESS_STATUSES = {"TRADE_SUCCESS", "TRADE_FINISHED"}


class PaymentService:
    """
    订单、支付、支付回调统一放在这里。

    约束点：
    1. 金额全程使用分为单位，避免浮点误差。
    2. 回调先落通知，再做幂等状态推进；重复通知不会重复记账或重复授予下载权限。
    3. 本地迁移阶段仍保留表单跳转语义，前端无需改造。
    """

    def __init__(
        self,
        settings: Settings,
        read_repo: ReadApiRepository,
        auth_repo: AuthRepository,
        material_repo: MaterialRepository,
        finance_repo: FinanceRepository,
        requests_service: RequestsService,
        payment_provider: PaymentGatewayProvider,
    ) -> None:
        self.settings = settings
        self.read_repo = read_repo
        self.auth_repo = auth_repo
        self.material_repo = material_repo
        self.finance_repo = finance_repo
        self.requests_service = requests_service
        self.payment_provider = payment_provider

    def create_order(self, session: Session, user_id: int, *, material_id: int, channel: str) -> dict[str, Any]:
        self._bootstrap_materials(session)
        self._require_user(session, user_id)
        material = self._require_material(session, material_id)
        if material.uploader_id == user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能购买自己的资料")
        already_purchased = self.material_repo.has_purchase(session, material.id, user_id)
        if channel == "simulated" and not material.is_free and not already_purchased and not self._allows_simulated_payment():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="模拟支付仅限本地开发环境")

        existing = self.finance_repo.find_latest_order_for_user_material(session, user_id, material_id)
        if existing is not None and existing.status in PAID_ORDER_STATUSES:
            return self._to_order_payload(existing)

        if existing is None:
            existing = self._build_order(material=material, user_id=user_id, channel=channel)
        else:
            existing.channel = channel
            existing.amount = int(material.price or 0)
            existing.material_title = material.title
            existing.uploader_id = material.uploader_id
            existing.platform_fee_amount, existing.creator_payable_amount, existing.commission_rate = self._split_amount(existing.amount)
        self.finance_repo.save_order(session, existing)

        if material.is_free or already_purchased or (channel == "simulated" and self._allows_simulated_payment()):
            self._mark_order_paid(session, existing, pay_channel=channel, trade_no=None, paid_at=datetime.now(UTC))

        session.commit()
        return self._to_order_payload(existing)

    def get_order(self, session: Session, order_id: int, user_id: int) -> dict[str, Any]:
        order = self.finance_repo.get_order(session, order_id)
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
        if order.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该订单")
        return self._to_order_detail(order)

    def confirm_order(self, session: Session, order_id: int, user_id: int) -> dict[str, Any]:
        order = self.finance_repo.get_order(session, order_id)
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
        if order.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作该订单")
        if not self._allows_simulated_payment():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="订单手动确认仅限本地模拟支付")
        self._mark_order_paid(session, order, pay_channel=order.channel or "simulated", trade_no=None, paid_at=datetime.now(UTC))
        order.confirmed_at = datetime.now(UTC)
        self.finance_repo.save_order(session, order)
        session.commit()
        return self._to_order_payload(order)

    def create_alipay_payment(
        self,
        session: Session,
        *,
        user_id: int,
        order_id: int | None,
        material_id: int | None,
    ) -> dict[str, Any]:
        if order_id is None and material_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="订单或资料信息不能为空")

        if order_id is not None:
            order = self.finance_repo.get_order(session, order_id)
            if order is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
            if order.user_id != user_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作该订单")
        else:
            created = self.create_order(session, user_id, material_id=material_id or 0, channel=self.payment_provider.channel_name)
            order = self.finance_repo.get_order(session, int(created["orderId"]))
            if order is None:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="订单创建失败")

        if order.status in PAID_ORDER_STATUSES:
            return {
                "status": order.status,
                "orderId": order.id,
                "materialId": order.material_id,
                "orderNo": order.out_trade_no,
                "form": None,
            }

        out_trade_no = order.out_trade_no or self.finance_repo.build_out_trade_no()
        order.out_trade_no = out_trade_no
        order.pay_channel = self.payment_provider.channel_name
        self.finance_repo.save_order(session, order)

        payment = self.finance_repo.find_latest_payment_by_order(session, order.id)
        if payment is None:
            payment = PaymentRecord(
                order_id=order.id,
                channel=self.payment_provider.channel_name,
                out_trade_no=out_trade_no,
                amount=int(order.amount or 0),
                status="CREATED",
            )
        else:
            payment.channel = self.payment_provider.channel_name
            payment.out_trade_no = out_trade_no
            payment.amount = int(order.amount or 0)
            if payment.status not in PAID_ORDER_STATUSES:
                payment.status = "CREATED"
        self.finance_repo.save_payment(session, payment)
        session.commit()

        return self.payment_provider.build_checkout_payload(out_trade_no=out_trade_no, order=order)

    def get_order_status(self, session: Session, *, user_id: int, out_trade_no: str, force_check: bool) -> dict[str, Any]:
        order = self.finance_repo.find_order_by_out_trade_no(session, out_trade_no)
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
        if order.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该订单")

        if force_check and order.status == "CREATED":
            local_notification = self.payment_provider.build_force_check_notification(out_trade_no=out_trade_no, order=order)
            if local_notification is not None:
                self._mark_order_paid(
                    session,
                    order,
                    pay_channel=self.payment_provider.channel_name,
                    trade_no=local_notification.trade_no,
                    paid_at=datetime.now(UTC),
                )
                session.commit()

        return {
            "status": order.status,
            "orderId": order.id,
            "materialId": order.material_id,
            "orderNo": order.out_trade_no,
        }

    def handle_alipay_notify(self, session: Session, params: dict[str, str]) -> str:
        parsed_notification = self.payment_provider.parse_notification(params)
        out_trade_no = parsed_notification.out_trade_no
        trade_no = parsed_notification.trade_no
        trade_status = str(params.get("trade_status") or "").strip().upper()
        app_id = str(params.get("app_id") or "").strip()
        seller_id = str(params.get("seller_id") or "").strip()

        notification = PaymentNotificationRecord(
            channel="alipay",
            out_trade_no=out_trade_no or None,
            trade_no=trade_no,
            payload=json.dumps(params, ensure_ascii=False, separators=(",", ":")),
            sign_verified=parsed_notification.sign_verified,
            processed=False,
        )

        if not out_trade_no:
            notification.process_result = "MISSING_OUT_TRADE_NO"
            self.finance_repo.save_payment_notification(session, notification)
            session.commit()
            return "success"
        if not parsed_notification.sign_verified:
            notification.process_result = "INVALID_SIGN"
            self.finance_repo.save_payment_notification(session, notification)
            session.commit()
            return self.payment_provider.success_response_text()
        if trade_status not in ALIPAY_SUCCESS_STATUSES:
            notification.process_result = "TRADE_NOT_SUCCESS"
            self.finance_repo.save_payment_notification(session, notification)
            session.commit()
            return self.payment_provider.success_response_text()
        if self.settings.alipay_app_id and app_id != self.settings.alipay_app_id:
            notification.process_result = "APP_ID_MISMATCH"
            self.finance_repo.save_payment_notification(session, notification)
            session.commit()
            return self.payment_provider.success_response_text()
        if self.settings.alipay_seller_id and seller_id != self.settings.alipay_seller_id:
            notification.process_result = "SELLER_ID_MISMATCH"
            self.finance_repo.save_payment_notification(session, notification)
            session.commit()
            return self.payment_provider.success_response_text()

        if out_trade_no.startswith("RQ"):
            result = self.requests_service.mark_contribution_paid_by_out_trade_no(
                session,
                out_trade_no=out_trade_no,
                trade_no=trade_no,
                amount_cents=parsed_notification.amount_cents,
            )
            notification.processed = result["status"] in {"PAID", "DUPLICATE"}
            notification.process_result = f"REQUEST_{result['status']}"
            self.finance_repo.save_payment_notification(session, notification)
            session.commit()
            return self.payment_provider.success_response_text()

        order = self.finance_repo.find_order_by_out_trade_no(session, out_trade_no)
        if order is None:
            notification.process_result = "ORDER_NOT_FOUND"
            self.finance_repo.save_payment_notification(session, notification)
            session.commit()
            return self.payment_provider.success_response_text()

        amount_cents = parsed_notification.amount_cents
        if amount_cents is not None and int(order.amount or 0) != amount_cents:
            notification.process_result = "AMOUNT_MISMATCH"
            self.finance_repo.save_payment_notification(session, notification)
            session.commit()
            return self.payment_provider.success_response_text()

        self._mark_order_paid(
            session,
            order,
            pay_channel=self.payment_provider.channel_name,
            trade_no=trade_no,
            paid_at=datetime.now(UTC),
        )
        notification.processed = True
        notification.process_result = "OK"
        self.finance_repo.save_payment_notification(session, notification)
        session.commit()
        return self.payment_provider.success_response_text()

    def query_alipay(self, session: Session, *, out_trade_no: str) -> dict[str, Any]:
        payment = self.finance_repo.find_payment_by_out_trade_no(session, out_trade_no)
        if payment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="支付记录不存在")
        order = self.finance_repo.get_order(session, payment.order_id)
        return self.payment_provider.build_query_payload(payment=payment, order=order)

    def _bootstrap_materials(self, session: Session) -> None:
        self.material_repo.ensure_seed_bootstrap(session, self.read_repo.load_seed())

    def _require_user(self, session: Session, user_id: int) -> None:
        if self.auth_repo.find_user_by_id(session, user_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    def _require_material(self, session: Session, material_id: int) -> MaterialRecord:
        material = self.material_repo.get_material(session, material_id)
        if material is None or material.deleted_at is not None or material.status in {"REMOVED", "HIDDEN"}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
        return material

    def _build_order(self, *, material: MaterialRecord, user_id: int, channel: str) -> OrderRecord:
        platform_fee_amount, creator_payable_amount, commission_rate = self._split_amount(int(material.price or 0))
        return OrderRecord(
            user_id=user_id,
            material_id=material.id,
            uploader_id=material.uploader_id,
            material_title=material.title,
            status="CREATED",
            amount=int(material.price or 0),
            channel=channel,
            commission_rate=commission_rate,
            platform_fee_amount=platform_fee_amount,
            creator_payable_amount=creator_payable_amount,
            policy_version=self.settings.settlement_policy_version,
        )

    def _mark_order_paid(
        self,
        session: Session,
        order: OrderRecord,
        *,
        pay_channel: str | None,
        trade_no: str | None,
        paid_at: datetime,
    ) -> None:
        material = self._require_material(session, order.material_id)
        already_had_purchase = self.material_repo.has_purchase(session, material.id, order.user_id)
        generated_trade_no = trade_no or self.finance_repo.build_trade_no()

        order.status = "PAID"
        order.pay_channel = pay_channel or order.pay_channel or order.channel
        order.trade_no = generated_trade_no
        order.paid_at = paid_at
        if not order.out_trade_no:
            order.out_trade_no = self.finance_repo.build_out_trade_no()
        self.finance_repo.save_order(session, order)

        payment = self.finance_repo.find_latest_payment_by_order(session, order.id)
        if payment is None:
            payment = PaymentRecord(
                order_id=order.id,
                channel=order.pay_channel or order.channel or "simulated",
                out_trade_no=order.out_trade_no or self.finance_repo.build_out_trade_no(),
                amount=int(order.amount or 0),
                status="PAID",
            )
        payment.status = "PAID"
        payment.channel = order.pay_channel or order.channel or payment.channel
        payment.out_trade_no = order.out_trade_no or payment.out_trade_no
        payment.amount = int(order.amount or 0)
        payment.trade_no = generated_trade_no
        payment.paid_at = paid_at
        self.finance_repo.save_payment(session, payment)

        if not already_had_purchase:
            self.material_repo.add_purchase(session, material_id=material.id, user_id=order.user_id, source="order-payment")
            if not material.is_free:
                material.sales_count = int(material.sales_count or 0) + 1
                self.material_repo.save_material(session, material)

    def _split_amount(self, amount_cents: int) -> tuple[int, int, float]:
        rate = Decimal(str(self.settings.platform_commission_rate))
        gross = Decimal(amount_cents)
        platform_fee = int((gross * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        creator_payable = max(0, amount_cents - platform_fee)
        return platform_fee, creator_payable, float(rate)

    def _allows_simulated_payment(self) -> bool:
        return not self.settings.is_production and self.payment_provider.provider_name == "local_alipay"

    def _to_order_payload(self, order: OrderRecord) -> dict[str, Any]:
        return {
            "orderId": order.id,
            "status": order.status,
            "amount": int(order.amount or 0),
            "orderNo": order.out_trade_no,
            "materialId": order.material_id,
        }

    def _to_order_detail(self, order: OrderRecord) -> dict[str, Any]:
        return {
            "id": order.id,
            "status": order.status,
            "amount": int(order.amount or 0),
            "channel": order.channel,
            "materialId": order.material_id,
            "createdAt": order.created_at.isoformat() if order.created_at else None,
            "paidAt": order.paid_at.isoformat() if order.paid_at else None,
            "orderNo": order.out_trade_no,
        }
