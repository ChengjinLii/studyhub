import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  isPendingPayStatus,
  resolvePayResultOrderNo,
  resolvePayResultView,
  startPayStatusPolling,
} from '../../lib/payResultStatus';

describe('resolvePayResultOrderNo', () => {
  it('prefers orderNo and falls back to the Alipay return out_trade_no', () => {
    expect(resolvePayResultOrderNo({ orderNo: 'SH1' })).toBe('SH1');
    expect(resolvePayResultOrderNo({ out_trade_no: 'RQ2', trade_no: 'T', sign: 'x' })).toBe('RQ2');
    expect(resolvePayResultOrderNo({ orderNo: 'SH1', out_trade_no: 'RQ2' })).toBe('SH1');
  });

  it('ignores missing, empty and repeated values', () => {
    expect(resolvePayResultOrderNo({})).toBe('');
    expect(resolvePayResultOrderNo({ orderNo: '' })).toBe('');
    expect(resolvePayResultOrderNo({ orderNo: ['A', 'B'] })).toBe('');
    expect(resolvePayResultOrderNo({ orderNo: ['A'], out_trade_no: 'RQ2' })).toBe('RQ2');
    expect(resolvePayResultOrderNo({ out_trade_no: ['A', 'B'] })).toBe('');
  });
});

describe('pay result status view', () => {
  it('treats only created/pending orders as still pending', () => {
    expect(isPendingPayStatus('CREATED')).toBe(true);
    expect(isPendingPayStatus('PENDING')).toBe(true);
    expect(isPendingPayStatus('PAID')).toBe(false);
    expect(isPendingPayStatus('CLOSED')).toBe(false);
    expect(isPendingPayStatus('REFUNDED')).toBe(false);
  });

  it('describes success, failure, pending and timed-out confirmation differently', () => {
    expect(resolvePayResultView('PAID', false)).toMatchObject({ tone: 'success', title: '支付成功' });
    expect(resolvePayResultView('PAID', true).tone).toBe('success');
    expect(resolvePayResultView('CLOSED', false)).toMatchObject({ tone: 'failure', title: '支付未完成' });
    expect(resolvePayResultView('FAILED', false).tone).toBe('failure');
    expect(resolvePayResultView('EXPIRED', true).tone).toBe('failure');
    expect(resolvePayResultView('REFUNDED', false).tone).toBe('failure');
    expect(resolvePayResultView('CREATED', false)).toMatchObject({ tone: 'pending', title: '正在确认支付结果…' });
    expect(resolvePayResultView('CREATED', true)).toMatchObject({ tone: 'timeout', title: '支付结果仍在确认中' });
    expect(resolvePayResultView('CREATED', false).title).not.toContain('支付完成');
  });
});

describe('startPayStatusPolling', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('force-checks first, then polls without force until the status settles', async () => {
    const outcomes: Array<'pending' | 'settled'> = ['pending', 'pending', 'settled'];
    const check = vi.fn(async (_forceCheck: boolean) => outcomes.shift() ?? 'settled');
    const onExhausted = vi.fn();
    startPayStatusPolling({ check, onExhausted, intervalMs: 3000, maxDurationMs: 120000 });

    await vi.advanceTimersByTimeAsync(0);
    expect(check).toHaveBeenCalledTimes(1);
    expect(check).toHaveBeenNthCalledWith(1, true);
    await vi.advanceTimersByTimeAsync(3000);
    expect(check).toHaveBeenNthCalledWith(2, false);
    await vi.advanceTimersByTimeAsync(3000);
    expect(check).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(60000);
    expect(check).toHaveBeenCalledTimes(3);
    expect(onExhausted).not.toHaveBeenCalled();
  });

  it('stops and reports exhaustion after the polling cap', async () => {
    const check = vi.fn(async () => 'pending' as const);
    const onExhausted = vi.fn();
    startPayStatusPolling({ check, onExhausted, intervalMs: 3000, maxDurationMs: 9000 });

    await vi.advanceTimersByTimeAsync(30000);
    expect(onExhausted).toHaveBeenCalledTimes(1);
    expect(check.mock.calls.length).toBeLessThanOrEqual(4);
    const callsAtExhaustion = check.mock.calls.length;
    await vi.advanceTimersByTimeAsync(30000);
    expect(check).toHaveBeenCalledTimes(callsAtExhaustion);
  });

  it('never overlaps requests while a check is still in flight', async () => {
    let resolveFirst: (value: 'pending') => void = () => undefined;
    const check = vi.fn(
      () =>
        new Promise<'pending' | 'settled'>((resolve) => {
          resolveFirst = resolve;
        })
    );
    startPayStatusPolling({ check, onExhausted: vi.fn(), intervalMs: 3000, maxDurationMs: 120000 });

    await vi.advanceTimersByTimeAsync(20000);
    expect(check).toHaveBeenCalledTimes(1);
    resolveFirst('pending');
    await vi.advanceTimersByTimeAsync(3000);
    expect(check).toHaveBeenCalledTimes(2);
  });

  it('keeps polling after a failed check and stops when cancelled', async () => {
    const check = vi.fn(async () => {
      throw new Error('network');
    });
    const stop = startPayStatusPolling({ check, onExhausted: vi.fn(), intervalMs: 3000, maxDurationMs: 120000 });

    await vi.advanceTimersByTimeAsync(3000);
    expect(check).toHaveBeenCalledTimes(2);
    stop();
    await vi.advanceTimersByTimeAsync(30000);
    expect(check).toHaveBeenCalledTimes(2);
  });
});
