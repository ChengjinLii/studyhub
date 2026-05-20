import { Dispatch, SetStateAction, useState } from 'react';
import { fetchBackend } from './apiBase';
import { toErrorMessage } from './errors';
import { AdminListMeta, AdminReport } from '../types/admin';

type AlertMessage = { type: 'success' | 'error'; text: string } | null;
type ReportFilters = { status: string; targetType: string };

interface UseAdminReportsOptions {
  reports: AdminReport[];
  setReports: Dispatch<SetStateAction<AdminReport[]>>;
  reportsMeta: AdminListMeta;
  setReportsMeta: Dispatch<SetStateAction<AdminListMeta>>;
}

export const useAdminReports = ({
  reports,
  setReports,
  reportsMeta,
  setReportsMeta,
}: UseAdminReportsOptions) => {
  const [reportFilters, setReportFilters] = useState<ReportFilters>({ status: '', targetType: '' });
  const [reportNotice, setReportNotice] = useState<AlertMessage>(null);
  const [reportsLoading, setReportsLoading] = useState(false);
  const [reportUpdatingId, setReportUpdatingId] = useState<number | null>(null);
  const [reportRestoringId, setReportRestoringId] = useState<number | null>(null);

  const loadReports = async (page = reportsMeta?.page ?? 0, nextFilters = reportFilters) => {
    setReportsLoading(true);
    setReportNotice(null);
    try {
      const params = new URLSearchParams();
      params.set('page', String(Math.max(page, 0)));
      params.set('size', String(reportsMeta?.size ?? 15));
      if (nextFilters.status) {
        params.set('status', nextFilters.status);
      }
      if (nextFilters.targetType) {
        params.set('targetType', nextFilters.targetType);
      }
      const resp = await fetchBackend(`/admin/reports?${params.toString()}`);
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '加载举报列表失败');
      }
      setReports(json.data.items || []);
      setReportsMeta(json.data.meta || { page: 0, size: reportsMeta?.size ?? 15, total: 0 });
    } catch (err: unknown) {
      setReportNotice({ type: 'error', text: toErrorMessage(err, '加载举报列表失败') });
    } finally {
      setReportsLoading(false);
    }
  };

  const handleReportPageChange = (targetPage: number) => {
    const pageIndex = Math.max(targetPage - 1, 0);
    void loadReports(pageIndex);
  };

  const handleReportFilterChange = (field: 'status' | 'targetType', value: string) => {
    const next = { ...reportFilters, [field]: value };
    setReportFilters(next);
    void loadReports(0, next);
  };

  const handleReportFieldUpdate = (id: number, field: 'status' | 'adminNote', value: string) => {
    setReports((prev) =>
      prev.map((report) => (report.id === id ? { ...report, [field]: value } : report))
    );
  };

  const handleReportUpdate = async (id: number) => {
    const target = reports.find((entry) => entry.id === id);
    if (!target) return;
    setReportUpdatingId(id);
    setReportNotice(null);
    try {
      const resp = await fetchBackend(`/admin/reports/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: target.status, adminNote: target.adminNote ?? '' }),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '更新举报失败');
      }
      setReports((prev) => prev.map((item) => (item.id === id ? json.data : item)));
      setReportNotice({ type: 'success', text: '举报工单已更新' });
    } catch (err: unknown) {
      setReportNotice({ type: 'error', text: toErrorMessage(err, '更新举报失败') });
    } finally {
      setReportUpdatingId(null);
    }
  };

  const handleReportRestore = async (id: number) => {
    setReportRestoringId(id);
    setReportNotice(null);
    try {
      const resp = await fetchBackend(`/admin/reports/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ restoreTarget: true }),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '恢复展示失败');
      }
      setReports((prev) => prev.map((item) => (item.id === id ? json.data : item)));
      setReportNotice({ type: 'success', text: '目标已恢复展示' });
    } catch (err: unknown) {
      setReportNotice({ type: 'error', text: toErrorMessage(err, '恢复展示失败') });
    } finally {
      setReportRestoringId(null);
    }
  };

  return {
    reportFilters,
    reportNotice,
    reportsLoading,
    reportUpdatingId,
    reportRestoringId,
    loadReports,
    handleReportPageChange,
    handleReportFilterChange,
    handleReportFieldUpdate,
    handleReportUpdate,
    handleReportRestore,
  };
};
