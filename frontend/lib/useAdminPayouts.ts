import { FormEvent, useCallback, useState } from 'react';
import {
  fetchPayoutApplications,
  fetchPayoutSchedule,
  fetchPayoutSettlementDetails,
  updatePayoutApplication,
  updatePayoutSchedule,
} from './adminApi';
import { toErrorMessage } from './errors';
import { PayoutApplication, PayoutSchedule, PayoutSettlementDetail } from '../types/payout';

type AlertMessage = { type: 'success' | 'error'; text: string } | null;

export const useAdminPayouts = () => {
  const [payouts, setPayouts] = useState<PayoutApplication[]>([]);
  const [payoutMessage, setPayoutMessage] = useState<AlertMessage>(null);
  const [payoutLoading, setPayoutLoading] = useState(false);
  const [payoutDetails, setPayoutDetails] = useState<Record<number, PayoutSettlementDetail[]>>({});
  const [payoutDetailLoading, setPayoutDetailLoading] = useState<Record<number, boolean>>({});
  const [payoutDetailOpen, setPayoutDetailOpen] = useState<Record<number, boolean>>({});
  const [schedule, setSchedule] = useState<PayoutSchedule | null>(null);
  const [scheduleForm, setScheduleForm] = useState({ launchDate: '', nextPayoutDate: '' });
  const [scheduleMessage, setScheduleMessage] = useState<AlertMessage>(null);
  const [scheduleLoading, setScheduleLoading] = useState(false);

  const reloadPayouts = useCallback(async () => {
    setPayoutLoading(true);
    try {
      const data = await fetchPayoutApplications();
      setPayouts(data.items || []);
    } catch (err: unknown) {
      setPayoutMessage({ type: 'error', text: toErrorMessage(err, '加载收益申请失败') });
    } finally {
      setPayoutLoading(false);
    }
  }, []);

  const handlePayoutAction = useCallback(async (id: number, status: 'APPROVED' | 'REJECTED', reviewNotes?: string) => {
    setPayoutMessage(null);
    try {
      await updatePayoutApplication(id, status, reviewNotes);
      setPayoutMessage({ type: 'success', text: '已更新收益申请' });
      await reloadPayouts();
    } catch (err: unknown) {
      setPayoutMessage({ type: 'error', text: toErrorMessage(err, '操作失败') });
    }
  }, [reloadPayouts]);

  const togglePayoutDetails = useCallback(async (id: number) => {
    setPayoutDetailOpen((prev) => ({ ...prev, [id]: !prev[id] }));
    if (payoutDetails[id] || payoutDetailLoading[id]) {
      return;
    }
    setPayoutDetailLoading((prev) => ({ ...prev, [id]: true }));
    try {
      const details = await fetchPayoutSettlementDetails(id);
      setPayoutDetails((prev) => ({ ...prev, [id]: details || [] }));
    } catch (error: unknown) {
      setPayoutMessage({ type: 'error', text: toErrorMessage(error, '加载收益明细失败') });
    } finally {
      setPayoutDetailLoading((prev) => ({ ...prev, [id]: false }));
    }
  }, [payoutDetailLoading, payoutDetails]);

  const loadSchedule = useCallback(async () => {
    setScheduleLoading(true);
    try {
      const data = await fetchPayoutSchedule();
      setSchedule(data);
      setScheduleForm({
        launchDate: data.launchDate || '',
        nextPayoutDate: data.nextPayoutDate || '',
      });
    } catch (err: unknown) {
      setScheduleMessage({ type: 'error', text: toErrorMessage(err, '加载上线日期失败') });
    } finally {
      setScheduleLoading(false);
    }
  }, []);

  const submitSchedule = useCallback(async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setScheduleLoading(true);
    setScheduleMessage(null);
    try {
      const payload: { launchDate: string | null; nextPayoutDate?: string } = {
        launchDate: scheduleForm.launchDate || null,
      };
      if (scheduleForm.nextPayoutDate) {
        payload.nextPayoutDate = scheduleForm.nextPayoutDate;
      }
      const data = await updatePayoutSchedule(payload);
      setSchedule(data);
      setScheduleForm({
        launchDate: data.launchDate || '',
        nextPayoutDate: data.nextPayoutDate || '',
      });
      setScheduleMessage({ type: 'success', text: '上线日期已更新' });
    } catch (err: unknown) {
      setScheduleMessage({ type: 'error', text: toErrorMessage(err, '更新失败') });
    } finally {
      setScheduleLoading(false);
    }
  }, [scheduleForm]);

  return {
    payouts,
    payoutMessage,
    payoutLoading,
    payoutDetails,
    payoutDetailLoading,
    payoutDetailOpen,
    reloadPayouts,
    handlePayoutAction,
    togglePayoutDetails,
    schedule,
    scheduleForm,
    setScheduleForm,
    scheduleMessage,
    scheduleLoading,
    loadSchedule,
    submitSchedule,
  };
};
