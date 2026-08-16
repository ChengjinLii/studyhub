from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.finance import FinanceInstructionRecord
from app.models.requests import RequestContributionRecord, RequestRecord


logger = logging.getLogger(__name__)

CONTRIBUTION_STATUS_PAID = "PAID"
CONTRIBUTION_STATUS_REFUNDING = "REFUNDING"
CONTRIBUTION_STATUS_REFUNDED = "REFUNDED"
REQUEST_STATUS_REFUNDING = "REFUNDING"
REQUEST_STATUS_REFUNDED = "REFUNDED"
SUCCESS_REFUND_STATUS = "SUCCESS"
INSTRUCTION_REQUEST_REFUND = "REQUEST_REFUND"


class RequestsRefundMixin:
    def _refund_request_contributions(self, session: Session, request: RequestRecord, *, reason: str) -> None:
        contributions = self.request_repo.list_contributions(session, request.id)
        active = [item for item in contributions if item.status in {CONTRIBUTION_STATUS_PAID, CONTRIBUTION_STATUS_REFUNDING}]
        if not active:
            request.status = REQUEST_STATUS_REFUNDED
            request.settled_at = datetime.now(UTC)
            self.request_repo.save_request(session, request)
            return
        all_refunded = True
        for contribution in active:
            contribution.status = CONTRIBUTION_STATUS_REFUNDING
            self.request_repo.save_contribution(session, contribution)
            refund_ok = self._execute_refund(session, contribution, reason=reason)
            if refund_ok:
                contribution.status = CONTRIBUTION_STATUS_REFUNDED
                self.request_repo.save_contribution(session, contribution)
                self._apply_refund_to_request(request, contribution.amount_cents)
            else:
                all_refunded = False
        request.status = REQUEST_STATUS_REFUNDED if all_refunded else REQUEST_STATUS_REFUNDING
        request.settled_at = datetime.now(UTC) if all_refunded else None
        self.request_repo.save_request(session, request)

    def _apply_refund_to_request(self, request: RequestRecord, amount_cents: int | None) -> None:
        request.funded_amount_cents = max(0, int(request.funded_amount_cents or 0) - int(amount_cents or 0))
        request.contribution_count = max(0, int(request.contribution_count or 0) - 1)
        if request.contribution_count == 0:
            request.max_contribution_amount_cents = 0

    def _execute_refund(self, session: Session, contribution: RequestContributionRecord, *, reason: str) -> bool:
        if getattr(contribution, "refund_status", None) == SUCCESS_REFUND_STATUS:
            return True
        if self.payment_provider is None:
            return True
        out_trade_no = contribution.out_trade_no
        amount_cents = int(contribution.amount_cents or 0)
        if not out_trade_no or amount_cents <= 0:
            return True
        contribution.refund_status = "PENDING"
        self.request_repo.save_contribution(session, contribution)
        if self.settings.resolved_finance_outbox_enabled and self.finance_repo is not None:
            self._enqueue_refund_instruction(session, contribution, reason=reason)
            return False
        result = self.payment_provider.refund(
            out_trade_no=out_trade_no,
            trade_no=contribution.trade_no,
            refund_amount_cents=amount_cents,
            out_request_no=out_trade_no,
        )
        if result.success:
            contribution.refund_status = SUCCESS_REFUND_STATUS
            contribution.refund_trade_no = result.refund_trade_no
            contribution.refunded_at = datetime.now(UTC)
            self.request_repo.save_contribution(session, contribution)
            return True
        contribution.refund_status = "FAILED"
        self.request_repo.save_contribution(session, contribution)
        logger.warning("Refund failed for contribution %s: %s %s", contribution.id, result.error_code, result.error_message)
        return False

    def _enqueue_refund_instruction(
        self,
        session: Session,
        contribution: RequestContributionRecord,
        *,
        reason: str,
    ) -> FinanceInstructionRecord:
        if self.finance_repo is None:
            raise RuntimeError("finance repository is required for refund outbox")
        operation_key = self._refund_operation_key(contribution.id)
        existing = self.finance_repo.find_finance_instruction(session, operation_key)
        if existing is not None:
            return existing
        instruction = FinanceInstructionRecord(
            operation_key=operation_key,
            instruction_type=INSTRUCTION_REQUEST_REFUND,
            aggregate_type="REQUEST_CONTRIBUTION",
            aggregate_id=int(contribution.id),
            payload_json=json.dumps(
                {"contributionId": int(contribution.id), "reason": reason[:120]},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            status="PENDING",
        )
        return self.finance_repo.save_finance_instruction(session, instruction)

    def process_refund_instructions(self, session: Session) -> int:
        if self.finance_repo is None or self.payment_provider is None:
            return 0
        now = datetime.now(UTC)
        instructions = self.finance_repo.list_ready_finance_instructions(
            session,
            INSTRUCTION_REQUEST_REFUND,
            now,
            stale_before=now - timedelta(minutes=5),
        )
        processed = 0
        for instruction in instructions:
            contribution = self.request_repo.get_contribution(session, int(instruction.aggregate_id))
            if contribution is None:
                instruction.status = "FAILED"
                instruction.last_error = "request contribution not found"
                self.finance_repo.save_finance_instruction(session, instruction)
                session.commit()
                continue
            if contribution.refund_status == SUCCESS_REFUND_STATUS:
                instruction.status = "SUCCEEDED"
                instruction.last_error = None
                self.finance_repo.save_finance_instruction(session, instruction)
                session.commit()
                processed += 1
                continue
            if int(instruction.attempt_count or 0) > 0 and self._refund_succeeded_at_provider(contribution, instruction):
                self._complete_refund_instruction(session, contribution, instruction, refund_trade_no=instruction.provider_reference)
                session.commit()
                processed += 1
                continue
            instruction.status = "PROCESSING"
            instruction.claimed_at = now
            instruction.attempt_count = int(instruction.attempt_count or 0) + 1
            instruction.last_error = None
            self.finance_repo.save_finance_instruction(session, instruction)
            session.commit()
            try:
                amount_cents = int(contribution.amount_cents or 0)
                result = self.payment_provider.refund(
                    out_trade_no=str(contribution.out_trade_no or ""),
                    trade_no=contribution.trade_no,
                    refund_amount_cents=amount_cents,
                    out_request_no=str(contribution.out_trade_no or instruction.operation_key),
                )
                if result.success:
                    self._complete_refund_instruction(
                        session,
                        contribution,
                        instruction,
                        refund_trade_no=result.refund_trade_no,
                    )
                    processed += 1
                else:
                    instruction.status = "PENDING"
                    instruction.next_attempt_at = datetime.now(UTC) + timedelta(minutes=min(30, max(1, instruction.attempt_count)))
                    instruction.last_error = f"{result.error_code or 'REFUND_FAILED'}: {result.error_message or ''}"[:512]
            except Exception as exc:  # noqa: BLE001
                instruction.status = "PENDING"
                instruction.next_attempt_at = datetime.now(UTC) + timedelta(minutes=min(30, max(1, instruction.attempt_count)))
                instruction.last_error = str(exc)[:512]
            self.finance_repo.save_finance_instruction(session, instruction)
            session.commit()
        return processed

    def _refund_succeeded_at_provider(
        self,
        contribution: RequestContributionRecord,
        instruction: FinanceInstructionRecord,
    ) -> bool:
        query_refund = getattr(self.payment_provider, "query_refund", None)
        if not callable(query_refund) or not contribution.out_trade_no:
            return False
        result = query_refund(
            out_trade_no=str(contribution.out_trade_no),
            trade_no=contribution.trade_no,
            out_request_no=str(contribution.out_trade_no or instruction.operation_key),
        )
        if str(result.status or "").upper() != SUCCESS_REFUND_STATUS:
            return False
        instruction.provider_reference = result.refund_trade_no
        return True

    def _complete_refund_instruction(
        self,
        session: Session,
        contribution: RequestContributionRecord,
        instruction: FinanceInstructionRecord,
        *,
        refund_trade_no: str | None,
    ) -> None:
        already_refunded = contribution.status == CONTRIBUTION_STATUS_REFUNDED
        contribution.refund_status = SUCCESS_REFUND_STATUS
        contribution.refund_trade_no = refund_trade_no or contribution.refund_trade_no
        contribution.refunded_at = contribution.refunded_at or datetime.now(UTC)
        contribution.status = CONTRIBUTION_STATUS_REFUNDED
        self.request_repo.save_contribution(session, contribution)
        request = self._require_request(session, contribution.request_id)
        if not already_refunded:
            self._apply_refund_to_request(request, contribution.amount_cents)
        remaining = self.request_repo.list_contributions(session, request.id)
        unsettled_paid = [
            item
            for item in remaining
            if item.id != contribution.id and item.status in {CONTRIBUTION_STATUS_PAID, CONTRIBUTION_STATUS_REFUNDING}
        ]
        if not unsettled_paid:
            request.status = REQUEST_STATUS_REFUNDED
            request.settled_at = request.settled_at or datetime.now(UTC)
        else:
            request.status = REQUEST_STATUS_REFUNDING
        self.request_repo.save_request(session, request)
        instruction.status = "SUCCEEDED"
        instruction.provider_reference = refund_trade_no or instruction.provider_reference
        instruction.result_json = json.dumps({"success": True, "verified": True}, separators=(",", ":"))
        instruction.last_error = None

    @staticmethod
    def _refund_operation_key(contribution_id: int | None) -> str:
        return f"request-refund:{int(contribution_id or 0)}"
