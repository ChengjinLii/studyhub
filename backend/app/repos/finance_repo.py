from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
import uuid

from sqlalchemy import Select, bindparam, case, func, inspect, select, text, update
from sqlalchemy.orm import Session

from app.models.finance import (
    AdminMonthlyPayoutMarkRecord,
    AlipayGatewayNotificationRecord,
    CreatorPayoutApplicationRecord,
    OrderRecord,
    PaymentNotificationRecord,
    PaymentRecord,
    PayoutScheduleRecord,
    PayoutTransferRecord,
    SettlementRecord,
    WorkerLockRecord,
)


_TABLE_COLUMN_CACHE: dict[tuple[str, str], set[str]] = {}
_ORDER_MAPPED_COLUMNS = tuple(OrderRecord.__table__.columns)
_SETTLEMENT_MAPPED_COLUMNS = tuple(SettlementRecord.__table__.columns)
_MONTHLY_MARK_MAPPED_COLUMNS = tuple(AdminMonthlyPayoutMarkRecord.__table__.columns)


def _bind_cache_key(session: Session) -> str:
    bind = session.get_bind()
    try:
        url = bind.engine.url
        rendered = url.render_as_string(hide_password=True)
        if url.database in {None, ":memory:"}:
            return f"{rendered}:{id(bind)}"
        return rendered
    except Exception:
        return str(bind)


def _table_columns(session: Session, table_name: str) -> set[str]:
    cache_key = (_bind_cache_key(session), table_name)
    cached = _TABLE_COLUMN_CACHE.get(cache_key)
    if cached is not None:
        return cached
    inspector = inspect(session.get_bind())
    column_names = {column["name"] for column in inspector.get_columns(table_name)}
    _TABLE_COLUMN_CACHE[cache_key] = column_names
    return column_names


def _has_table_column(session: Session, table_name: str, column_name: str) -> bool:
    return column_name in _table_columns(session, table_name)


class FinanceRepository:
    def _uses_legacy_orders(self, session: Session) -> bool:
        existing_columns = _table_columns(session, "orders")
        return any(column.name not in existing_columns for column in _ORDER_MAPPED_COLUMNS)

    def _uses_legacy_settlements(self, session: Session) -> bool:
        existing_columns = _table_columns(session, "settlements")
        return any(column.name not in existing_columns for column in _SETTLEMENT_MAPPED_COLUMNS)

    def _has_settlement_transfer_binding(self, session: Session) -> bool:
        return _has_table_column(session, "settlements", "payout_transfer_id")

    def _uses_legacy_monthly_marks(self, session: Session) -> bool:
        existing_columns = _table_columns(session, "admin_monthly_payout_marks")
        return any(column.name not in existing_columns for column in _MONTHLY_MARK_MAPPED_COLUMNS)

    def get_order(self, session: Session, order_id: int) -> OrderRecord | None:
        if self._uses_legacy_orders(session):
            rows = self._select_legacy_orders(session, "o.id = :order_id", {"order_id": order_id}, "o.id ASC", limit=1)
            return rows[0] if rows else None
        return session.get(OrderRecord, order_id)

    def find_order_by_out_trade_no(self, session: Session, out_trade_no: str) -> OrderRecord | None:
        if self._uses_legacy_orders(session):
            rows = self._select_legacy_orders(
                session,
                "o.out_trade_no = :out_trade_no",
                {"out_trade_no": out_trade_no},
                "o.id DESC",
                limit=1,
            )
            return rows[0] if rows else None
        stmt = select(OrderRecord).where(OrderRecord.out_trade_no == out_trade_no)
        return session.scalar(stmt)

    def find_latest_order_for_user_material(self, session: Session, user_id: int, material_id: int) -> OrderRecord | None:
        if self._uses_legacy_orders(session):
            rows = self._select_legacy_orders(
                session,
                "o.user_id = :user_id AND o.material_id = :material_id",
                {"user_id": user_id, "material_id": material_id},
                "o.created_at DESC, o.id DESC",
                limit=1,
            )
            return rows[0] if rows else None
        stmt = (
            select(OrderRecord)
            .where(OrderRecord.user_id == user_id, OrderRecord.material_id == material_id)
            .order_by(OrderRecord.created_at.desc(), OrderRecord.id.desc())
            .limit(1)
        )
        return session.scalar(stmt)

    def list_paid_orders_between(self, session: Session, start: datetime, end: datetime) -> list[OrderRecord]:
        if self._uses_legacy_orders(session):
            return self._select_legacy_orders(
                session,
                "o.status = 'PAID' AND o.paid_at IS NOT NULL AND o.paid_at >= :start AND o.paid_at < :end",
                {"start": start, "end": end},
                "o.paid_at DESC, o.id DESC",
            )
        stmt = (
            select(OrderRecord)
            .where(
                OrderRecord.status == "PAID",
                OrderRecord.paid_at.is_not(None),
                OrderRecord.paid_at >= start,
                OrderRecord.paid_at < end,
            )
            .order_by(OrderRecord.paid_at.desc(), OrderRecord.id.desc())
        )
        return list(session.scalars(stmt))

    def list_paid_orders_for_creator_between(self, session: Session, uploader_id: int, start: datetime, end: datetime) -> list[OrderRecord]:
        if self._uses_legacy_orders(session):
            return self._select_legacy_orders(
                session,
                f"""
                o.status = 'PAID'
                AND {self._legacy_order_uploader_expr(session)} = :uploader_id
                AND o.paid_at IS NOT NULL
                AND o.paid_at >= :start
                AND o.paid_at < :end
                """,
                {"uploader_id": uploader_id, "start": start, "end": end},
                "o.paid_at DESC, o.id DESC",
            )
        stmt = (
            select(OrderRecord)
            .where(
                OrderRecord.status == "PAID",
                OrderRecord.uploader_id == uploader_id,
                OrderRecord.paid_at.is_not(None),
                OrderRecord.paid_at >= start,
                OrderRecord.paid_at < end,
            )
            .order_by(OrderRecord.paid_at.desc(), OrderRecord.id.desc())
        )
        return list(session.scalars(stmt))

    def list_paid_orders_eligible_for_settlement(self, session: Session, threshold: datetime) -> list[OrderRecord]:
        if self._uses_legacy_orders(session):
            return self._select_legacy_orders(
                session,
                "o.status = 'PAID' AND o.paid_at IS NOT NULL AND o.paid_at <= :threshold",
                {"threshold": threshold},
                "o.paid_at ASC, o.id ASC",
            )
        stmt = (
            select(OrderRecord)
            .where(
                OrderRecord.status == "PAID",
                OrderRecord.paid_at.is_not(None),
                OrderRecord.paid_at <= threshold,
            )
            .order_by(OrderRecord.paid_at.asc(), OrderRecord.id.asc())
        )
        return list(session.scalars(stmt))

    def save_order(self, session: Session, entity: OrderRecord) -> OrderRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def _legacy_order_uploader_expr(self, session: Session) -> str:
        return "COALESCE(o.uploader_id, m.uploader_id)" if _has_table_column(session, "orders", "uploader_id") else "m.uploader_id"

    def _select_legacy_orders(
        self,
        session: Session,
        where_sql: str,
        params: dict[str, Any],
        order_sql: str,
        *,
        limit: int | None = None,
    ) -> list[OrderRecord]:
        order_columns = _table_columns(session, "orders")
        uploader_expr = self._legacy_order_uploader_expr(session)
        material_title_expr = "o.material_title" if "material_title" in order_columns else "m.title"
        confirmed_expr = "o.confirmed_at" if "confirmed_at" in order_columns else "NULL"
        limit_sql = "LIMIT :limit" if limit is not None else ""
        query_params = dict(params)
        if limit is not None:
            query_params["limit"] = max(1, int(limit))
        rows = session.execute(
            text(
                f"""
                SELECT
                    o.id,
                    o.user_id,
                    o.material_id,
                    {uploader_expr} AS uploader_id,
                    {material_title_expr} AS material_title,
                    o.status,
                    o.amount,
                    o.channel,
                    o.pay_channel,
                    o.out_trade_no,
                    o.trade_no,
                    o.commission_rate,
                    o.platform_fee_amount,
                    o.creator_payable_amount,
                    o.policy_version,
                    o.paid_at,
                    {confirmed_expr} AS confirmed_at,
                    o.created_at,
                    o.updated_at
                FROM orders o
                LEFT JOIN materials m ON m.id = o.material_id
                WHERE {where_sql}
                ORDER BY {order_sql}
                {limit_sql}
                """
            ),
            query_params,
        ).mappings().all()
        return [self._legacy_order_record(row) for row in rows]

    def _legacy_order_record(self, row) -> OrderRecord:
        return OrderRecord(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            material_id=int(row["material_id"]),
            uploader_id=None if row["uploader_id"] is None else int(row["uploader_id"]),
            material_title=row["material_title"],
            status=row["status"],
            amount=int(row["amount"] or 0),
            channel=row["channel"],
            pay_channel=row["pay_channel"],
            out_trade_no=row["out_trade_no"],
            trade_no=row["trade_no"],
            commission_rate=row["commission_rate"],
            platform_fee_amount=None if row["platform_fee_amount"] is None else int(row["platform_fee_amount"]),
            creator_payable_amount=None if row["creator_payable_amount"] is None else int(row["creator_payable_amount"]),
            policy_version=row["policy_version"],
            paid_at=row["paid_at"],
            confirmed_at=row["confirmed_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def find_payment_by_out_trade_no(self, session: Session, out_trade_no: str) -> PaymentRecord | None:
        stmt = select(PaymentRecord).where(PaymentRecord.out_trade_no == out_trade_no)
        return session.scalar(stmt)

    def find_latest_payment_by_order(self, session: Session, order_id: int) -> PaymentRecord | None:
        stmt = (
            select(PaymentRecord)
            .where(PaymentRecord.order_id == order_id)
            .order_by(PaymentRecord.created_at.desc(), PaymentRecord.id.desc())
            .limit(1)
        )
        return session.scalar(stmt)

    def save_payment(self, session: Session, entity: PaymentRecord) -> PaymentRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def save_payment_notification(self, session: Session, entity: PaymentNotificationRecord) -> PaymentNotificationRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def find_settlement_by_source(self, session: Session, source_type: str, source_id: int) -> SettlementRecord | None:
        if self._uses_legacy_settlements(session):
            rows = self._select_legacy_settlements(
                session,
                "s.source_type = :source_type AND s.source_id = :source_id",
                {"source_type": source_type, "source_id": source_id},
                "s.id ASC",
                limit=1,
            )
            return rows[0] if rows else None
        stmt = select(SettlementRecord).where(SettlementRecord.source_type == source_type, SettlementRecord.source_id == source_id)
        return session.scalar(stmt)

    def list_settlements_for_uploader(self, session: Session, uploader_id: int) -> list[SettlementRecord]:
        if self._uses_legacy_settlements(session):
            return self._select_legacy_settlements(
                session,
                "s.uploader_id = :uploader_id",
                {"uploader_id": uploader_id},
                "s.created_at DESC, s.id DESC",
            )
        stmt = (
            select(SettlementRecord)
            .where(SettlementRecord.uploader_id == uploader_id)
            .order_by(SettlementRecord.created_at.desc(), SettlementRecord.id.desc())
        )
        return list(session.scalars(stmt))

    def summarize_settlements_for_uploaders(
        self,
        session: Session,
        uploader_ids: list[int],
        now: datetime,
    ) -> dict[int, dict[str, int]]:
        if not uploader_ids:
            return {}
        if not self._has_settlement_transfer_binding(session):
            normalized_ids = sorted({int(uploader_id) for uploader_id in uploader_ids})
            stmt = text(
                """
                SELECT
                    uploader_id,
                    COUNT(id) AS order_count,
                    COALESCE(SUM(gross_amount), 0) AS gross_amount,
                    COALESCE(SUM(platform_fee), 0) AS platform_fee,
                    COALESCE(SUM(CASE WHEN status = 'PENDING' THEN payout_amount ELSE 0 END), 0) AS pending_total,
                    COALESCE(SUM(
                        CASE
                            WHEN status = 'PENDING'
                             AND scheduled_payout_at IS NOT NULL
                             AND scheduled_payout_at <= :now
                            THEN payout_amount
                            ELSE 0
                        END
                    ), 0) AS available
                FROM settlements
                WHERE uploader_id IN :uploader_ids
                GROUP BY uploader_id
                """
            ).bindparams(bindparam("uploader_ids", expanding=True))
            rows = session.execute(stmt, {"uploader_ids": normalized_ids, "now": now}).mappings().all()
            return {
                int(row["uploader_id"]): {
                    "grossAmount": int(row["gross_amount"] or 0),
                    "platformFee": int(row["platform_fee"] or 0),
                    "payoutAmount": int(row["available"] or 0),
                    "orderCount": int(row["order_count"] or 0),
                    "unclaimedPayoutTotal": int(row["pending_total"] or 0),
                }
                for row in rows
                if row["uploader_id"] is not None
            }
        normalized_ids = sorted({int(uploader_id) for uploader_id in uploader_ids})
        pending_condition = SettlementRecord.status == "PENDING"
        available_condition = (
            pending_condition
            & SettlementRecord.payout_transfer_id.is_(None)
            & SettlementRecord.scheduled_payout_at.is_not(None)
            & (SettlementRecord.scheduled_payout_at <= now)
        )
        stmt = (
            select(
                SettlementRecord.uploader_id,
                func.count(SettlementRecord.id).label("order_count"),
                func.coalesce(func.sum(SettlementRecord.gross_amount), 0).label("gross_amount"),
                func.coalesce(func.sum(SettlementRecord.platform_fee), 0).label("platform_fee"),
                func.coalesce(
                    func.sum(case((pending_condition, SettlementRecord.payout_amount), else_=0)),
                    0,
                ).label("pending_total"),
                func.coalesce(
                    func.sum(case((available_condition, SettlementRecord.payout_amount), else_=0)),
                    0,
                ).label("available"),
            )
            .where(SettlementRecord.uploader_id.in_(normalized_ids))
            .group_by(SettlementRecord.uploader_id)
        )
        rows = session.execute(stmt).mappings().all()
        return {
            int(row["uploader_id"]): {
                "grossAmount": int(row["gross_amount"] or 0),
                "platformFee": int(row["platform_fee"] or 0),
                "payoutAmount": int(row["available"] or 0),
                "orderCount": int(row["order_count"] or 0),
                "unclaimedPayoutTotal": int(row["pending_total"] or 0),
            }
            for row in rows
            if row["uploader_id"] is not None
        }

    def list_pending_due_settlements_for_uploader(self, session: Session, uploader_id: int, now: datetime) -> list[SettlementRecord]:
        if self._uses_legacy_settlements(session):
            return self._select_legacy_settlements(
                session,
                """
                s.uploader_id = :uploader_id
                AND s.status = 'PENDING'
                AND s.scheduled_payout_at IS NOT NULL
                AND s.scheduled_payout_at <= :now
                """,
                {"uploader_id": uploader_id, "now": now},
                "s.created_at ASC, s.id ASC",
            )
        stmt = (
            select(SettlementRecord)
            .where(
                SettlementRecord.uploader_id == uploader_id,
                SettlementRecord.status == "PENDING",
                SettlementRecord.scheduled_payout_at.is_not(None),
                SettlementRecord.scheduled_payout_at <= now,
            )
            .order_by(SettlementRecord.created_at.asc(), SettlementRecord.id.asc())
        )
        return list(session.scalars(stmt))

    def list_claimable_due_settlements_for_uploader(self, session: Session, uploader_id: int, now: datetime) -> list[SettlementRecord]:
        if self._uses_legacy_settlements(session):
            transfer_filter = "AND s.payout_transfer_id IS NULL" if self._has_settlement_transfer_binding(session) else ""
            return self._select_legacy_settlements(
                session,
                f"""
                s.uploader_id = :uploader_id
                AND s.status = 'PENDING'
                {transfer_filter}
                AND s.scheduled_payout_at IS NOT NULL
                AND s.scheduled_payout_at <= :now
                """,
                {"uploader_id": uploader_id, "now": now},
                "s.created_at ASC, s.id ASC",
            )
        stmt = (
            select(SettlementRecord)
            .where(
                SettlementRecord.uploader_id == uploader_id,
                SettlementRecord.status == "PENDING",
                SettlementRecord.payout_transfer_id.is_(None),
                SettlementRecord.scheduled_payout_at.is_not(None),
                SettlementRecord.scheduled_payout_at <= now,
            )
            .order_by(SettlementRecord.created_at.asc(), SettlementRecord.id.asc())
        )
        return list(session.scalars(stmt))

    def list_settlements_for_transfer(self, session: Session, transfer_id: int) -> list[SettlementRecord]:
        if not self._has_settlement_transfer_binding(session):
            return []
        if self._uses_legacy_settlements(session):
            return self._select_legacy_settlements(
                session,
                "s.payout_transfer_id = :transfer_id",
                {"transfer_id": transfer_id},
                "s.created_at ASC, s.id ASC",
            )
        stmt = (
            select(SettlementRecord)
            .where(SettlementRecord.payout_transfer_id == transfer_id)
            .order_by(SettlementRecord.created_at.asc(), SettlementRecord.id.asc())
        )
        return list(session.scalars(stmt))

    def claim_due_settlements_for_transfer(
        self, session: Session, uploader_id: int, transfer_id: int, now: datetime
    ) -> list[SettlementRecord]:
        """Atomically bind every claimable-due settlement to ``transfer_id``.

        The conditional ``payout_transfer_id IS NULL`` UPDATE is the claim: a concurrent
        transaction cannot bind the same row to a second transfer, so each settlement is
        paid out exactly once. Returns the rows actually claimed by this transfer.
        """
        if not self._has_settlement_transfer_binding(session):
            return self.list_claimable_due_settlements_for_uploader(session, uploader_id, now)
        stmt = (
            update(SettlementRecord)
            .where(
                SettlementRecord.uploader_id == uploader_id,
                SettlementRecord.status == "PENDING",
                SettlementRecord.payout_transfer_id.is_(None),
                SettlementRecord.scheduled_payout_at.is_not(None),
                SettlementRecord.scheduled_payout_at <= now,
            )
            .values(payout_transfer_id=transfer_id)
        )
        session.execute(stmt)
        session.flush()
        return self.list_settlements_for_transfer(session, transfer_id)

    def unbind_pending_settlements_from_transfer(self, session: Session, transfer_id: int) -> int:
        """Release still-PENDING settlements bound to a failed transfer back to claimable."""
        if not self._has_settlement_transfer_binding(session):
            return 0
        stmt = (
            update(SettlementRecord)
            .where(
                SettlementRecord.payout_transfer_id == transfer_id,
                SettlementRecord.status == "PENDING",
            )
            .values(payout_transfer_id=None)
        )
        result = session.execute(stmt)
        session.flush()
        return int(result.rowcount or 0)

    def list_pending_transfers(self, session: Session) -> list[PayoutTransferRecord]:
        stmt = (
            select(PayoutTransferRecord)
            .where(PayoutTransferRecord.status.in_(("SUBMITTED", "PENDING")))
            .order_by(PayoutTransferRecord.created_at.asc(), PayoutTransferRecord.id.asc())
        )
        return list(session.scalars(stmt))

    def save_settlement(self, session: Session, entity: SettlementRecord) -> SettlementRecord:
        if self._uses_legacy_settlements(session):
            self._save_legacy_settlement(session, entity)
            return entity
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def _select_legacy_settlements(
        self,
        session: Session,
        where_sql: str,
        params: dict[str, Any],
        order_sql: str,
        *,
        limit: int | None = None,
    ) -> list[SettlementRecord]:
        settlement_columns = _table_columns(session, "settlements")
        material_title_expr = "s.material_title" if "material_title" in settlement_columns else "m.title"
        payout_transfer_expr = "s.payout_transfer_id" if "payout_transfer_id" in settlement_columns else "NULL"
        limit_sql = "LIMIT :limit" if limit is not None else ""
        query_params = dict(params)
        if limit is not None:
            query_params["limit"] = max(1, int(limit))
        rows = session.execute(
            text(
                f"""
                SELECT
                    s.id,
                    s.order_id,
                    s.material_id,
                    {material_title_expr} AS material_title,
                    s.uploader_id,
                    s.gross_amount,
                    s.platform_fee,
                    s.payout_amount,
                    s.status,
                    {payout_transfer_expr} AS payout_transfer_id,
                    s.policy_version,
                    s.policy_id,
                    s.source_type,
                    s.source_id,
                    s.scheduled_payout_at,
                    s.processed_at,
                    s.created_at,
                    s.updated_at
                FROM settlements s
                LEFT JOIN materials m ON m.id = s.material_id
                WHERE {where_sql}
                ORDER BY {order_sql}
                {limit_sql}
                """
            ),
            query_params,
        ).mappings().all()
        return [self._legacy_settlement_record(row) for row in rows]

    def _legacy_settlement_record(self, row) -> SettlementRecord:
        return SettlementRecord(
            id=int(row["id"]),
            order_id=None if row["order_id"] is None else int(row["order_id"]),
            material_id=None if row["material_id"] is None else int(row["material_id"]),
            material_title=row["material_title"],
            uploader_id=None if row["uploader_id"] is None else int(row["uploader_id"]),
            gross_amount=int(row["gross_amount"] or 0),
            platform_fee=int(row["platform_fee"] or 0),
            payout_amount=int(row["payout_amount"] or 0),
            status=row["status"] or "PENDING",
            payout_transfer_id=None if row["payout_transfer_id"] is None else int(row["payout_transfer_id"]),
            policy_version=row["policy_version"],
            policy_id=row["policy_id"],
            source_type=row["source_type"] or "ORDER",
            source_id=int(row["source_id"] or row["id"]),
            scheduled_payout_at=row["scheduled_payout_at"],
            processed_at=row["processed_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"] or row["created_at"],
        )

    def _save_legacy_settlement(self, session: Session, entity: SettlementRecord) -> None:
        existing_columns = _table_columns(session, "settlements")
        now = datetime.now(UTC)
        if entity.created_at is None:
            entity.created_at = now
        entity.updated_at = now
        values = {
            "id": entity.id,
            "order_id": entity.order_id,
            "material_id": entity.material_id,
            "material_title": entity.material_title,
            "uploader_id": entity.uploader_id,
            "gross_amount": int(entity.gross_amount or 0),
            "platform_fee": int(entity.platform_fee or 0),
            "payout_amount": int(entity.payout_amount or 0),
            "status": entity.status,
            "payout_transfer_id": entity.payout_transfer_id,
            "policy_version": entity.policy_version,
            "policy_id": entity.policy_id,
            "source_type": entity.source_type,
            "source_id": entity.source_id,
            "scheduled_payout_at": entity.scheduled_payout_at,
            "processed_at": entity.processed_at,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
        }
        row_exists = (
            entity.id is not None
            and session.execute(text("SELECT 1 FROM settlements WHERE id = :id LIMIT 1"), {"id": int(entity.id)}).first() is not None
        )
        if row_exists:
            update_columns = [
                column
                for column in values
                if column in existing_columns and column not in {"id", "created_at"}
            ]
            assignments = ", ".join(f"{column} = :{column}" for column in update_columns)
            if assignments:
                params = {column: values[column] for column in update_columns}
                params["id"] = int(entity.id)
                session.execute(text(f"UPDATE settlements SET {assignments} WHERE id = :id"), params)
            return
        insert_columns = [column for column in values if column in existing_columns and values[column] is not None]
        placeholders = ", ".join(f":{column}" for column in insert_columns)
        result = session.execute(
            text(f"INSERT INTO settlements ({', '.join(insert_columns)}) VALUES ({placeholders})"),
            {column: values[column] for column in insert_columns},
        )
        if entity.id is None and result.lastrowid is not None:
            entity.id = int(result.lastrowid)

    def get_payout_application(self, session: Session, application_id: int) -> CreatorPayoutApplicationRecord | None:
        return session.get(CreatorPayoutApplicationRecord, application_id)

    def find_latest_payout_application_for_user(self, session: Session, user_id: int) -> CreatorPayoutApplicationRecord | None:
        stmt = (
            select(CreatorPayoutApplicationRecord)
            .where(CreatorPayoutApplicationRecord.user_id == user_id)
            .order_by(CreatorPayoutApplicationRecord.created_at.desc(), CreatorPayoutApplicationRecord.id.desc())
            .limit(1)
        )
        return session.scalar(stmt)

    def find_payout_application_by_user_cycle(self, session: Session, user_id: int, cycle_key: str) -> CreatorPayoutApplicationRecord | None:
        stmt = select(CreatorPayoutApplicationRecord).where(
            CreatorPayoutApplicationRecord.user_id == user_id,
            CreatorPayoutApplicationRecord.cycle_key == cycle_key,
        )
        return session.scalar(stmt)

    def find_latest_verified_kyc(self, session: Session, user_id: int) -> CreatorPayoutApplicationRecord | None:
        stmt = (
            select(CreatorPayoutApplicationRecord)
            .where(
                CreatorPayoutApplicationRecord.user_id == user_id,
                CreatorPayoutApplicationRecord.kyc_status == "VERIFIED",
                CreatorPayoutApplicationRecord.kyc_verified_at.is_not(None),
            )
            .order_by(CreatorPayoutApplicationRecord.kyc_verified_at.desc(), CreatorPayoutApplicationRecord.id.desc())
            .limit(1)
        )
        return session.scalar(stmt)

    def list_payout_applications(self, session: Session, *, page: int, size: int) -> tuple[list[CreatorPayoutApplicationRecord], int]:
        safe_page = max(page, 0)
        safe_size = max(1, min(size, 100))
        total = int(session.scalar(select(func.count()).select_from(CreatorPayoutApplicationRecord)) or 0)
        stmt = (
            select(CreatorPayoutApplicationRecord)
            .order_by(CreatorPayoutApplicationRecord.created_at.desc(), CreatorPayoutApplicationRecord.id.desc())
            .offset(safe_page * safe_size)
            .limit(safe_size)
        )
        return list(session.scalars(stmt)), total

    def save_payout_application(self, session: Session, entity: CreatorPayoutApplicationRecord) -> CreatorPayoutApplicationRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def get_payout_transfer(self, session: Session, transfer_id: int) -> PayoutTransferRecord | None:
        return session.get(PayoutTransferRecord, transfer_id)

    def find_transfer_by_application(self, session: Session, payout_application_id: int) -> PayoutTransferRecord | None:
        stmt = select(PayoutTransferRecord).where(PayoutTransferRecord.payout_application_id == payout_application_id)
        return session.scalar(stmt)

    def find_transfer_by_out_biz_no(self, session: Session, out_biz_no: str) -> PayoutTransferRecord | None:
        stmt = select(PayoutTransferRecord).where(PayoutTransferRecord.out_biz_no == out_biz_no)
        return session.scalar(stmt)

    def save_payout_transfer(self, session: Session, entity: PayoutTransferRecord) -> PayoutTransferRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def save_gateway_notification(self, session: Session, entity: AlipayGatewayNotificationRecord) -> AlipayGatewayNotificationRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def get_payout_schedule(self, session: Session) -> PayoutScheduleRecord | None:
        stmt = select(PayoutScheduleRecord).order_by(PayoutScheduleRecord.id.asc()).limit(1)
        return session.scalar(stmt)

    def save_payout_schedule(self, session: Session, entity: PayoutScheduleRecord) -> PayoutScheduleRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def find_monthly_payout_mark(self, session: Session, month_key: str, uploader_id: int) -> AdminMonthlyPayoutMarkRecord | None:
        if self._uses_legacy_monthly_marks(session):
            row = session.execute(
                text(
                    """
                    SELECT id, month_key, uploader_id, status, marked_at, marked_by, amount_snapshot, created_at, updated_at
                    FROM admin_monthly_payout_marks
                    WHERE month_key = :month_key AND uploader_id = :uploader_id
                    LIMIT 1
                    """
                ),
                {"month_key": month_key, "uploader_id": uploader_id},
            ).mappings().first()
            return self._legacy_monthly_mark_record(row) if row is not None else None
        stmt = select(AdminMonthlyPayoutMarkRecord).where(
            AdminMonthlyPayoutMarkRecord.month_key == month_key,
            AdminMonthlyPayoutMarkRecord.uploader_id == uploader_id,
        )
        return session.scalar(stmt)

    def list_monthly_payout_marks(self, session: Session, month_key: str) -> list[AdminMonthlyPayoutMarkRecord]:
        if self._uses_legacy_monthly_marks(session):
            rows = session.execute(
                text(
                    """
                    SELECT id, month_key, uploader_id, status, marked_at, marked_by, amount_snapshot, created_at, updated_at
                    FROM admin_monthly_payout_marks
                    WHERE month_key = :month_key
                    """
                ),
                {"month_key": month_key},
            ).mappings().all()
            return [self._legacy_monthly_mark_record(row) for row in rows]
        stmt = select(AdminMonthlyPayoutMarkRecord).where(AdminMonthlyPayoutMarkRecord.month_key == month_key)
        return list(session.scalars(stmt))

    def save_monthly_payout_mark(self, session: Session, entity: AdminMonthlyPayoutMarkRecord) -> AdminMonthlyPayoutMarkRecord:
        if self._uses_legacy_monthly_marks(session):
            timestamp = datetime.now(UTC)
            if entity.id is not None and session.execute(text("SELECT 1 FROM admin_monthly_payout_marks WHERE id = :id LIMIT 1"), {"id": int(entity.id)}).first():
                session.execute(
                    text(
                        """
                        UPDATE admin_monthly_payout_marks
                        SET status = :status,
                            amount_snapshot = :amount_snapshot,
                            marked_by = :marked_by,
                            marked_at = :marked_at,
                            updated_at = :updated_at
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": int(entity.id),
                        "status": entity.status,
                        "amount_snapshot": entity.amount_snapshot,
                        "marked_by": entity.marked_by_id,
                        "marked_at": entity.marked_at,
                        "updated_at": timestamp,
                    },
                )
                entity.updated_at = timestamp
                return entity
            result = session.execute(
                text(
                    """
                    INSERT INTO admin_monthly_payout_marks (
                        month_key, uploader_id, status, amount_snapshot, marked_by, marked_at, created_at, updated_at
                    )
                    VALUES (
                        :month_key, :uploader_id, :status, :amount_snapshot, :marked_by, :marked_at, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "month_key": entity.month_key,
                    "uploader_id": entity.uploader_id,
                    "status": entity.status,
                    "amount_snapshot": entity.amount_snapshot,
                    "marked_by": entity.marked_by_id,
                    "marked_at": entity.marked_at,
                    "created_at": entity.created_at or timestamp,
                    "updated_at": timestamp,
                },
            )
            if entity.id is None and result.lastrowid is not None:
                entity.id = int(result.lastrowid)
            entity.updated_at = timestamp
            return entity
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def _legacy_monthly_mark_record(self, row) -> AdminMonthlyPayoutMarkRecord:
        return AdminMonthlyPayoutMarkRecord(
            id=int(row["id"]),
            month_key=row["month_key"],
            uploader_id=int(row["uploader_id"]),
            status=row["status"],
            marked_at=row["marked_at"],
            marked_by_id=None if row["marked_by"] is None else int(row["marked_by"]),
            amount_snapshot=None if row["amount_snapshot"] is None else int(row["amount_snapshot"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"] or row["created_at"],
        )

    def get_worker_lock(self, session: Session, name: str) -> WorkerLockRecord | None:
        return session.get(WorkerLockRecord, name)

    def save_worker_lock(self, session: Session, entity: WorkerLockRecord) -> WorkerLockRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def build_out_trade_no(self) -> str:
        return "OD" + uuid.uuid4().hex[:24].upper()

    def build_trade_no(self) -> str:
        return "TRADE" + uuid.uuid4().hex[:20].upper()

    def build_out_biz_no(self) -> str:
        return "PT" + uuid.uuid4().hex[:24].upper()
