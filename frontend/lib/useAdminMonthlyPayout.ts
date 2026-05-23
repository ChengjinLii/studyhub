import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchAdminMonthlyPayoutOverview, fetchAdminPayoutQr, updateAdminMonthlyPayoutMark } from './adminApi';
import { toErrorMessage } from './errors';
import { AdminMonthlyPayoutItem, AdminMonthlyPayoutOverview } from '../types/payout';

export interface PayoutQrModalState {
  open: boolean;
  title: string;
  loading: boolean;
  error: string | null;
  url: string | null;
}

const INITIAL_PAYOUT_QR_MODAL: PayoutQrModalState = {
  open: false,
  title: '',
  loading: false,
  error: null,
  url: null,
};

export const useAdminMonthlyPayout = (initialMonth: string) => {
  const [monthlyPayoutMonth, setMonthlyPayoutMonth] = useState(initialMonth);
  const monthlyPayoutMonthRef = useRef(monthlyPayoutMonth);
  const [monthlyPayoutOverview, setMonthlyPayoutOverview] = useState<AdminMonthlyPayoutOverview | null>(null);
  const [monthlyPayoutMessage, setMonthlyPayoutMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [monthlyPayoutLoading, setMonthlyPayoutLoading] = useState(false);
  const [monthlyPayoutMarkingId, setMonthlyPayoutMarkingId] = useState<number | null>(null);
  const [payoutQrModal, setPayoutQrModal] = useState<PayoutQrModalState>(INITIAL_PAYOUT_QR_MODAL);

  useEffect(() => {
    monthlyPayoutMonthRef.current = monthlyPayoutMonth;
  }, [monthlyPayoutMonth]);

  const reloadMonthlyPayoutOverview = useCallback(async (monthParam?: string) => {
    const targetMonth = monthParam ?? monthlyPayoutMonthRef.current;
    if (!targetMonth) {
      setMonthlyPayoutMessage({ type: 'error', text: '请选择月份' });
      return;
    }
    setMonthlyPayoutLoading(true);
    setMonthlyPayoutMessage(null);
    try {
      const data = await fetchAdminMonthlyPayoutOverview(targetMonth);
      setMonthlyPayoutOverview(data);
    } catch (error: unknown) {
      setMonthlyPayoutMessage({ type: 'error', text: toErrorMessage(error, '加载月度打款数据失败') });
    } finally {
      setMonthlyPayoutLoading(false);
    }
  }, []);

  const handleMonthlyMark = useCallback(
    async (item: AdminMonthlyPayoutItem, markPaid: boolean) => {
      if (!item?.uploaderId) {
        return;
      }
      setMonthlyPayoutMarkingId(item.uploaderId);
      setMonthlyPayoutMessage(null);
      try {
        await updateAdminMonthlyPayoutMark({
          monthKey: monthlyPayoutMonthRef.current,
          uploaderId: item.uploaderId,
          markPaid,
        });
        setMonthlyPayoutMessage({ type: 'success', text: markPaid ? '已标记为已打款' : '已撤销打款标记' });
        await reloadMonthlyPayoutOverview();
      } catch (error: unknown) {
        setMonthlyPayoutMessage({ type: 'error', text: toErrorMessage(error, '更新打款标记失败') });
      } finally {
        setMonthlyPayoutMarkingId(null);
      }
    },
    [reloadMonthlyPayoutOverview]
  );

  const openPayoutQrModal = useCallback(async (item: AdminMonthlyPayoutItem) => {
    const name = item.uploaderNickname || item.uploaderUsername || `用户 #${item.uploaderId}`;
    if (!item?.uploaderId) {
      return;
    }
    setPayoutQrModal({
      open: true,
      title: `${name} 的收款码`,
      loading: true,
      error: null,
      url: null,
    });
    try {
      const data = await fetchAdminPayoutQr(item.uploaderId);
      if (!data?.hasPayoutQr || !data?.payoutQrUrl) {
        throw new Error('该用户尚未上传收款码');
      }
      setPayoutQrModal((prev) => ({ ...prev, loading: false, url: data.payoutQrUrl || null }));
    } catch (error: unknown) {
      setPayoutQrModal((prev) => ({
        ...prev,
        loading: false,
        error: toErrorMessage(error, '加载收款码失败'),
      }));
    }
  }, []);

  const closePayoutQrModal = useCallback(() => {
    setPayoutQrModal(INITIAL_PAYOUT_QR_MODAL);
  }, []);

  return {
    monthlyPayoutMonth,
    setMonthlyPayoutMonth,
    monthlyPayoutOverview,
    monthlyPayoutMessage,
    monthlyPayoutLoading,
    monthlyPayoutMarkingId,
    payoutQrModal,
    reloadMonthlyPayoutOverview,
    handleMonthlyMark,
    openPayoutQrModal,
    closePayoutQrModal,
  };
};
