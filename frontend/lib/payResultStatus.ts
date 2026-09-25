export const PAY_STATUS_POLL_INTERVAL_MS = 3000;
export const PAY_STATUS_MAX_POLL_DURATION_MS = 2 * 60 * 1000;

const PENDING_PAY_STATUSES = new Set(['CREATED', 'PENDING']);

export type PayStatusCheckOutcome = 'pending' | 'settled';
export type PayResultTone = 'success' | 'failure' | 'pending' | 'timeout';

export interface PayResultView {
  tone: PayResultTone;
  title: string;
  description: string;
}

const firstQueryValue = (value: unknown) => (typeof value === 'string' && value ? value : '');

/** Alipay's return_url appends `out_trade_no` instead of our own `orderNo` parameter. */
export const resolvePayResultOrderNo = (query: Record<string, unknown>) =>
  firstQueryValue(query.orderNo) || firstQueryValue(query.out_trade_no);

export const isPendingPayStatus = (status: string) => PENDING_PAY_STATUSES.has(status);

export const resolvePayResultView = (status: string, pollingExhausted: boolean): PayResultView => {
  if (status === 'PAID') {
    return { tone: 'success', title: '支付成功', description: '支付已确认，正在为你跳转…' };
  }
  if (!isPendingPayStatus(status)) {
    return {
      tone: 'failure',
      title: '支付未完成',
      description: '订单已关闭、失败或已退款，本次未扣款成功。如需继续，请返回重新下单。',
    };
  }
  if (pollingExhausted) {
    return {
      tone: 'timeout',
      title: '支付结果仍在确认中',
      description: '暂未收到支付结果。若你已完成支付，请稍后点击“刷新状态”，无需重复付款。',
    };
  }
  return { tone: 'pending', title: '正在确认支付结果…', description: '系统将自动校验支付结果并跳转。' };
};

interface PayStatusPollingOptions {
  check: (forceCheck: boolean) => Promise<PayStatusCheckOutcome>;
  onExhausted: () => void;
  intervalMs?: number;
  maxDurationMs?: number;
}

/**
 * Force-checks once, then polls until the status settles or the cap is reached.
 * The next check is only scheduled after the previous one finishes, so requests never overlap.
 * Returns a function that stops polling.
 */
export function startPayStatusPolling({
  check,
  onExhausted,
  intervalMs = PAY_STATUS_POLL_INTERVAL_MS,
  maxDurationMs = PAY_STATUS_MAX_POLL_DURATION_MS,
}: PayStatusPollingOptions) {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const startedAt = Date.now();

  const tick = async (forceCheck: boolean) => {
    let outcome: PayStatusCheckOutcome = 'pending';
    try {
      outcome = await check(forceCheck);
    } catch {
      outcome = 'pending';
    }
    if (stopped || outcome === 'settled') return;
    if (Date.now() - startedAt + intervalMs > maxDurationMs) {
      onExhausted();
      return;
    }
    timer = setTimeout(() => void tick(false), intervalMs);
  };

  void tick(true);
  return () => {
    stopped = true;
    if (timer !== undefined) clearTimeout(timer);
  };
}
