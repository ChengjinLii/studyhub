import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { FormEvent, useEffect, useState } from 'react';
import AdminMarketPanel from '../../components/admin/AdminMarketPanel';
import AdminMaterialsPanel from '../../components/admin/AdminMaterialsPanel';
import AdminPayoutQrModal from '../../components/admin/AdminPayoutQrModal';
import { useAppDialog } from '../../components/AppDialogProvider';
import NavBar from '../../components/NavBar';
import PaginationBar from '../../components/PaginationBar';
import { readSession, hasRole } from '../../lib/auth';
import { getRequestOrigin } from '../../lib/apiBase';
import {
  broadcastAdminNotification,
  createAdminUser,
  fetchAdminFeedbacks,
  fetchAdminInitialDashboard,
  fetchAdminMarketItems,
  fetchAdminMaterials,
  fetchAdminUsers,
  fetchAdminVolunteers,
  restoreAdminMaterial,
  updateAdminFeedbackStatus,
  updateAdminUserRole,
  updateAdminVolunteerStatus,
} from '../../lib/adminApi';
import { toErrorMessage } from '../../lib/errors';
import { useAdminMonthlyPayout } from '../../lib/useAdminMonthlyPayout';
import { formatDateTime } from '../../lib/format';
import { useSectionNavigation } from '../../lib/useSectionNavigation';
import { useAdminBatchActions } from '../../lib/useAdminBatchActions';
import { useAdminReports } from '../../lib/useAdminReports';
import { useAdminUserNotes } from '../../lib/useAdminUserNotes';
import { useAdminPayouts } from '../../lib/useAdminPayouts';
import { SessionUser, RoleMask } from '../../types/user';
import {
  UserSummary,
  FeedbackEntry,
  VolunteerApplicationEntry,
  AdminMaterial,
  AdminMarketItem,
  AdminListMeta,
  AdminReport,
} from '../../types/admin';
import { AdminMonthlyPayoutOverview, AdminMonthlyPayoutItem, AdminPayoutQr } from '../../types/payout';

interface AdminPageProps {
  user: SessionUser;
  users: UserSummary[];
  token: string;
  feedbacks: FeedbackEntry[];
  volunteers: VolunteerApplicationEntry[];
  materials: AdminMaterial[];
  materialsMeta: AdminListMeta;
  marketItems: AdminMarketItem[];
  marketMeta: AdminListMeta;
  reports: AdminReport[];
  reportsMeta: AdminListMeta;
}

const FEEDBACK_TYPES = [
  { value: 'BUG', label: 'Bug 反馈' },
  { value: 'FEATURE', label: '功能建议' },
  { value: 'UX', label: '体验问题' },
  { value: 'OTHER', label: '其他' },
];
const FEEDBACK_STATUS_OPTIONS = [
  { value: 'NEW', label: '待处理' },
  { value: 'IN_PROGRESS', label: '处理中' },
  { value: 'RESOLVED', label: '已解决' },
  { value: 'IGNORED', label: '忽略' },
];

const VOLUNTEER_STATUS_OPTIONS = [
  { value: 'NEW', label: '待确认' },
  { value: 'CONTACTED', label: '已联系' },
  { value: 'ACCEPTED', label: '已加入' },
  { value: 'REJECTED', label: '已婉拒' },
];

const TIME_COMMITMENT_LABELS: Record<string, string> = {
  '2-4H': '每周 2-4 小时',
  '4-8H': '每周 4-8 小时',
  '8H+': '每周 8 小时以上',
};

const REPORT_STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'PENDING', label: '待处理' },
  { value: 'IN_PROGRESS', label: '处理中' },
  { value: 'RESOLVED', label: '已处理' },
  { value: 'REJECTED', label: '已驳回' },
];

const REPORT_TARGET_OPTIONS = [
  { value: '', label: '全部类型' },
  { value: 'MATERIAL', label: '资料' },
  { value: 'COMMENT', label: '评论' },
  { value: 'MARKET_ITEM', label: '集市' },
  { value: 'USER', label: '用户' },
];

const ADMIN_QUICK_NAV_ITEMS = [
  { id: 'admin-income', label: '收入总览', icon: '💹' },
  { id: 'admin-broadcast', label: '广播通知', icon: '📣' },
  { id: 'admin-materials', label: '资料管理', icon: '📄' },
  { id: 'admin-market', label: '集市管理', icon: '🏪' },
  { id: 'admin-reports', label: '举报工单', icon: '🚨' },
  { id: 'admin-settlements', label: '结算管理', icon: '💰' },
  { id: 'admin-monthly-payout', label: '月度打款', icon: '🧾' },
  { id: 'admin-schedule', label: '结算日程', icon: '📅' },
  { id: 'admin-admins', label: '管理员', icon: '🛡️' },
  { id: 'admin-users', label: '用户列表', icon: '👥' },
];

const getCurrentMonthValue = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
};

export default function AdminPage({
  user,
  users: initialUsers,
  feedbacks: initialFeedbacks,
  volunteers: initialVolunteers,
  materials: initialMaterials,
  materialsMeta: initialMaterialsMeta,
  marketItems: initialMarketItems,
  marketMeta: initialMarketMeta,
  reports: initialReports,
  reportsMeta: initialReportsMeta,
}: AdminPageProps) {
  const dialog = useAppDialog();
  const [users, setUsers] = useState<UserSummary[]>(initialUsers);
  const [feedbacks, setFeedbacks] = useState<FeedbackEntry[]>(initialFeedbacks);
  const [volunteers, setVolunteers] = useState<VolunteerApplicationEntry[]>(initialVolunteers);
  const [materials, setMaterials] = useState<AdminMaterial[]>(initialMaterials);
  const [materialsMeta, setMaterialsMeta] = useState(initialMaterialsMeta);
  const [materialView, setMaterialView] = useState<'active' | 'removed'>('active');
  const [marketItems, setMarketItems] = useState<AdminMarketItem[]>(initialMarketItems);
  const [marketMeta, setMarketMeta] = useState(initialMarketMeta);
  const [reports, setReports] = useState<AdminReport[]>(initialReports);
  const [reportsMeta, setReportsMeta] = useState(initialReportsMeta);
  const [materialsLoading, setMaterialsLoading] = useState(false);
  const [marketLoading, setMarketLoading] = useState(false);
  const [restoringMaterialId, setRestoringMaterialId] = useState<number | null>(null);
  const [form, setForm] = useState({ username: '', password: '', nickname: '', admin: true, developer: true });
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [volunteerMessage, setVolunteerMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [userSearch, setUserSearch] = useState('');
  const [broadcastText, setBroadcastText] = useState('');
  const [broadcastStatus, setBroadcastStatus] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [broadcasting, setBroadcasting] = useState(false);
  const [actualTotalRaw, setActualTotalRaw] = useState('');
  const [actualTotalValue, setActualTotalValue] = useState<number | null>(null);
  const [actualTotalNotice, setActualTotalNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const {
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
  } = useAdminMonthlyPayout(getCurrentMonthValue());
  const {
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
  } = useAdminPayouts();
  const { activeSection: activeAdminSection, jumpToSection } = useSectionNavigation(ADMIN_QUICK_NAV_ITEMS, {
    rootMargin: '-20% 0px -60% 0px',
    threshold: [0.1, 0.25, 0.5],
  });
  const materialPageSize = materialsMeta?.size || 15;
  const materialTotalItems = materialsMeta?.total || 0;
  const currentMaterialPage = Math.max(1, (materialsMeta?.page ?? 0) + 1);
  const marketPageSize = marketMeta?.size || 15;
  const marketTotalItems = marketMeta?.total || 0;
  const currentMarketPage = Math.max(1, marketMeta?.page || 1);
  const reportPageSize = reportsMeta?.size || 15;
  const reportTotalItems = reportsMeta?.total || 0;
  const currentReportPage = Math.max(1, (reportsMeta?.page ?? 0) + 1);
  const isSuperAdmin = hasRole(user.roleMask, RoleMask.DEVELOPER);
  const isAgenticAdmin = hasRole(user.roleMask, RoleMask.ADMIN);
  const roleLabel = isSuperAdmin ? '超级管理员' : '管理员';
  const totalEarnings = users.reduce((sum, item) => sum + Number(item.totalEarnings ?? 0), 0);
  const scaleToActual = (amountCents: number) =>
    (amountCents / 100) *
    (actualTotalValue !== null && totalEarnings > 0 ? actualTotalValue / totalEarnings : 1);

  const reloadUsers = async (keywordParam?: string) => {
    const data = await fetchAdminUsers(keywordParam);
    setUsers(data);
  };

  const reloadFeedbacks = async () => {
    const data = await fetchAdminFeedbacks();
    setFeedbacks(data);
  };

  const reloadVolunteers = async () => {
    const data = await fetchAdminVolunteers();
    setVolunteers(data);
  };

  const loadMaterials = async (page = materialsMeta?.page ?? 0, view = materialView) => {
    setMaterialsLoading(true);
    try {
      const data = await fetchAdminMaterials({
        page: Math.max(page, 0),
        size: materialsMeta?.size ?? 15,
        status: view === 'removed' ? 'removed' : undefined,
      });
      setMaterials(data.items || []);
      setMaterialsMeta(data.meta || { page: 0, size: materialsMeta?.size ?? 15, total: 0 });
      setSelectedMaterialIds((prev) =>
        prev.filter((id) => (data.items || []).some((entry: AdminMaterial) => entry.id === id))
      );
    } catch (err: unknown) {
      setBatchMessage({ type: 'error', text: toErrorMessage(err, '加载资料失败') });
    } finally {
      setMaterialsLoading(false);
    }
  };

  const handleMaterialPageChange = (targetPage: number) => {
    const pageIndex = Math.max(targetPage - 1, 0);
    void loadMaterials(pageIndex, materialView);
  };

  const handleMaterialViewChange = (nextView: 'active' | 'removed') => {
    if (nextView === materialView) {
      return;
    }
    setMaterialView(nextView);
    clearMaterialSelection();
    void loadMaterials(0, nextView);
  };

  const loadMarketItems = async (page = marketMeta?.page ?? 1) => {
    setMarketLoading(true);
    try {
      const data = await fetchAdminMarketItems({ page: Math.max(page, 1), size: marketMeta?.size ?? 15 });
      const items: AdminMarketItem[] = data.items || [];
      setMarketItems(items);
      setMarketMeta(data.meta || { page, size: marketMeta?.size ?? 15, total: 0 });
      setSelectedMarketIds((prev) => prev.filter((id) => items.some((entry) => entry.id === id)));
    } catch (err: unknown) {
      setMarketBatchMessage({ type: 'error', text: toErrorMessage(err, '加载校园集市商品失败') });
    } finally {
      setMarketLoading(false);
    }
  };

  const handleMarketPageChange = (targetPage: number) => {
    const safeTarget = Math.max(targetPage, 1);
    void loadMarketItems(safeTarget);
  };

  const {
    selectedMaterialIds,
    setSelectedMaterialIds,
    selectedMarketIds,
    setSelectedMarketIds,
    batchForm,
    batchMajorSelections,
    batchMessage,
    setBatchMessage,
    batchDeleting,
    batchRestoring,
    marketBatchForm,
    marketBatchMessage,
    setMarketBatchMessage,
    marketBatchDeleting,
    toggleMaterialSelection,
    selectAllMaterials,
    clearMaterialSelection,
    toggleMarketSelection,
    selectAllMarketItems,
    clearMarketSelection,
    handleBatchInputChange,
    handleBatchMajorToggle,
    handleMarketBatchInputChange,
    handleBatchSubmit,
    handleBatchDelete,
    handleBatchRestore,
    applyMarketBatchUpdate,
    handleMarketBatchSubmit,
    handleMarketBatchDelete,
  } = useAdminBatchActions({
    materials,
    marketItems,
    materialView,
    currentMaterialPage,
    currentMarketPage,
    loadMaterials,
    loadMarketItems,
  });
  const {
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
  } = useAdminReports({
    reports,
    setReports,
    reportsMeta,
    setReportsMeta,
  });

  const handleRestoreMaterial = async (materialId: number) => {
    if (!materialId) return;
    const confirmed = await dialog.confirm({ title: '恢复资料', message: '确定恢复该资料？', confirmText: '恢复资料' });
    if (!confirmed) return;
    setRestoringMaterialId(materialId);
    setBatchMessage(null);
    try {
      await restoreAdminMaterial(materialId);
      setBatchMessage({ type: 'success', text: '资料已恢复' });
      await loadMaterials(currentMaterialPage - 1, 'removed');
    } catch (err: unknown) {
      setBatchMessage({ type: 'error', text: toErrorMessage(err, '恢复失败') });
    } finally {
      setRestoringMaterialId((prev) => (prev === materialId ? null : prev));
    }
  };

  const handleCreate = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!form.username || !form.password) {
      setMessage({ type: 'error', text: '用户名和密码不能为空' });
      return;
    }
    setSubmitting(true);
    setMessage(null);
    try {
      const roleMask =
        1 |
        (form.admin ? RoleMask.ADMIN : 0) |
        (form.developer ? RoleMask.DEVELOPER : 0) |
        RoleMask.CONTRIBUTOR;
      await createAdminUser({
        username: form.username,
        password: form.password,
        nickname: form.nickname,
        roleMask,
      });
      setMessage({ type: 'success', text: '管理员已创建' });
      setForm({ username: '', password: '', nickname: '', admin: true, developer: true });
      reloadUsers();
    } catch (err: unknown) {
      setMessage({ type: 'error', text: toErrorMessage(err, '创建失败') });
    } finally {
      setSubmitting(false);
    }
  };

  const handleUserSearch = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    reloadUsers(userSearch.trim());
  };
  const {
    noteDrafts,
    setNoteDrafts,
    noteAlerts,
    userNotes,
    notesLoading,
    notePanelOpen,
    toggleNotePanel,
    handleSendNote,
  } = useAdminUserNotes();

  const updateFeedbackStatus = async (id: number, status: string) => {
    setFeedbackMessage(null);
    try {
      await updateAdminFeedbackStatus(id, status);
      setFeedbackMessage({ type: 'success', text: '反馈状态已更新' });
      reloadFeedbacks();
    } catch (err: unknown) {
      setFeedbackMessage({ type: 'error', text: toErrorMessage(err, '更新失败') });
    }
  };

  const updateVolunteerStatus = async (id: number, status: string) => {
    setVolunteerMessage(null);
    try {
      await updateAdminVolunteerStatus(id, status);
      setVolunteerMessage({ type: 'success', text: '申请状态已更新' });
      reloadVolunteers();
    } catch (err: unknown) {
      setVolunteerMessage({ type: 'error', text: toErrorMessage(err, '更新失败') });
    }
  };

  const toggleRole = async (id: number, roleMask: number) => {
    try {
      await updateAdminUserRole(id, roleMask);
      setMessage({ type: 'success', text: '角色更新成功' });
      reloadUsers();
    } catch (err: unknown) {
      setMessage({ type: 'error', text: toErrorMessage(err, '更新失败') });
    }
  };

  const handleBroadcast = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const messageText = broadcastText.trim();
    if (!messageText) {
      setBroadcastStatus({ type: 'error', text: '通知内容不能为空' });
      return;
    }
    setBroadcasting(true);
    setBroadcastStatus(null);
    try {
      await broadcastAdminNotification(messageText);
      setBroadcastStatus({ type: 'success', text: '已广播给所有用户' });
      setBroadcastText('');
    } catch (err: unknown) {
      setBroadcastStatus({ type: 'error', text: toErrorMessage(err, '广播失败') });
    } finally {
      setBroadcasting(false);
    }
  };

  const handleConfirmActualTotal = () => {
    const parsed = parseFloat(actualTotalRaw);
    if (Number.isNaN(parsed) || parsed < 0) {
      setActualTotalNotice({ type: 'error', text: '请输入合法的实际总收入（非负数字）' });
      return;
    }
    setActualTotalNotice({ type: 'success', text: '已更新实际总收入' });
    setActualTotalValue(parsed);
  };

  useEffect(() => {
    reloadPayouts();
    reloadMonthlyPayoutOverview();
    loadSchedule();
  }, [loadSchedule, reloadMonthlyPayoutOverview, reloadPayouts]);

  return (
    <>
      <NavBar user={user} />
      <main className="container admin-layout">
        <aside className="admin-sidebar">
          <div className="admin-sidebar__title">管理导航</div>
          <div className="admin-sidebar__items">
            {ADMIN_QUICK_NAV_ITEMS.map((item) => (
              <a
                key={item.id}
                className={`admin-sidebar__item ${activeAdminSection === item.id ? 'active' : ''}`}
                href={`#${item.id}`}
                onClick={(event) => {
                  event.preventDefault();
                  jumpToSection(item.id);
                }}
              >
                <span className="admin-sidebar__indicator" aria-hidden="true" />
                <span className="admin-sidebar__text">{item.label}</span>
              </a>
            ))}
          </div>
        </aside>

        <div className="admin-content admin-grid">
        <section id="admin-top" className="card admin-hero">
          <div className="admin-hero__content">
            <div className="admin-hero__left">
              <span className="admin-hero__eyebrow">{roleLabel}控制台</span>
              <h1>管理后台</h1>
              <div className="admin-hero__meta">
                <span className="admin-meta-chip">当前登录：{user.nickname}</span>
                <span className="admin-meta-chip">角色：{roleLabel}</span>
                <span className="admin-meta-chip">ID：{user.id}</span>
              </div>
              {isAgenticAdmin && (
                <Link className="button ghost small admin-agentic-platform-link" href="/admin/agentic-platform">
                  进入 Agent 运行控制台
                </Link>
              )}
            </div>
          </div>
        </section>

        <section id="admin-income" className="card admin-section">
          <div className="card-title">收入总览</div>
          <p className="help-text">所有用户应得收入汇总</p>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
            <strong style={{ fontSize: '2rem' }}>¥{totalEarnings.toFixed(2)}</strong>
            <span className="material-meta">应得收入汇总</span>
          </div>
          <div className="form-grid" style={{ marginTop: 12 }}>
            <div className="form-item">
              <label htmlFor="actual-total">实际总收入</label>
              <input
                id="actual-total"
                type="number"
                inputMode="decimal"
                placeholder="填写实际总收入"
                value={actualTotalRaw}
                onChange={(e) => setActualTotalRaw(e.target.value)}
              />
            </div>
            <div className="form-item">
              <button className="button primary" type="button" onClick={handleConfirmActualTotal}>
                确认计算
              </button>
            </div>
            {actualTotalNotice && (
              <p className={actualTotalNotice.type === 'error' ? 'error-text' : 'success-text'}>
                {actualTotalNotice.text}
              </p>
            )}
            {actualTotalValue !== null && (
              <p className="help-text">已设置实际总收入：¥{actualTotalValue.toFixed(2)}</p>
            )}
          </div>
        </section>

        <section id="admin-broadcast" className="card admin-section">
          <div className="card-title">广播通知</div>
          <p className="help-text">发送后所有用户的悬浮窗会出现“新消息”提示。</p>
          <form className="form-grid" onSubmit={handleBroadcast}>
            <div className="form-item">
              <label htmlFor="broadcast-message">通知内容</label>
              <textarea
                id="broadcast-message"
                className="input"
                rows={3}
                placeholder="填写要广播的消息，所有用户都会收到"
                value={broadcastText}
                onChange={(e) => setBroadcastText(e.target.value)}
              />
            </div>
            {broadcastStatus && (
              <p className={broadcastStatus.type === 'error' ? 'error-text' : 'success-text'}>{broadcastStatus.text}</p>
            )}
            <div className="form-item">
              <button className="button primary" type="submit" disabled={broadcasting}>
                {broadcasting ? '发送中...' : '广播给所有用户'}
              </button>
            </div>
          </form>
        </section>

        <AdminMaterialsPanel
          materials={materials}
          materialView={materialView}
          materialsLoading={materialsLoading}
          batchMessage={batchMessage}
          selectedMaterialIds={selectedMaterialIds}
          batchDeleting={batchDeleting}
          batchRestoring={batchRestoring}
          restoringMaterialId={restoringMaterialId}
          currentMaterialPage={currentMaterialPage}
          materialTotalItems={materialTotalItems}
          materialPageSize={materialPageSize}
          batchForm={batchForm}
          batchMajorSelections={batchMajorSelections}
          onRefresh={() => loadMaterials(currentMaterialPage - 1)}
          onViewChange={handleMaterialViewChange}
          onSelectAll={selectAllMaterials}
          onClearSelection={clearMaterialSelection}
          onBatchRestore={handleBatchRestore}
          onBatchDelete={handleBatchDelete}
          onToggleSelection={toggleMaterialSelection}
          onRestoreMaterial={handleRestoreMaterial}
          onPageChange={handleMaterialPageChange}
          onBatchSubmit={handleBatchSubmit}
          onBatchInputChange={handleBatchInputChange}
          onBatchMajorToggle={handleBatchMajorToggle}
        />

        <AdminMarketPanel
          marketItems={marketItems}
          marketLoading={marketLoading}
          selectedMarketIds={selectedMarketIds}
          marketBatchMessage={marketBatchMessage}
          marketBatchDeleting={marketBatchDeleting}
          marketBatchForm={marketBatchForm}
          currentMarketPage={currentMarketPage}
          marketTotalItems={marketTotalItems}
          marketPageSize={marketPageSize}
          onRefresh={() => loadMarketItems(currentMarketPage)}
          onSelectAll={selectAllMarketItems}
          onClearSelection={clearMarketSelection}
          onApplyMarketBatchUpdate={applyMarketBatchUpdate}
          onMarketBatchDelete={handleMarketBatchDelete}
          onToggleSelection={toggleMarketSelection}
          onPageChange={handleMarketPageChange}
          onMarketBatchSubmit={handleMarketBatchSubmit}
          onMarketBatchInputChange={handleMarketBatchInputChange}
        />

        <section id="admin-reports" className="card admin-section">
          <div className="card-title">举报工单</div>
          <p className="help-text">资料 / 评论 / 集市 / 用户的举报汇总。</p>
          <div className="inline-group wrap" style={{ marginBottom: 12 }}>
            <select
              value={reportFilters.status}
              onChange={(e) => handleReportFilterChange('status', e.target.value)}
            >
              {REPORT_STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <select
              value={reportFilters.targetType}
              onChange={(e) => handleReportFilterChange('targetType', e.target.value)}
            >
              {REPORT_TARGET_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <button
              className="button ghost small"
              type="button"
              onClick={() => loadReports(reportsMeta?.page ?? 0)}
              disabled={reportsLoading}
            >
              {reportsLoading ? '刷新中...' : '刷新列表'}
            </button>
          </div>
          {reportNotice && (
            <p className={reportNotice.type === 'error' ? 'error-text' : 'success-text'}>{reportNotice.text}</p>
          )}
          {reports.length === 0 ? (
            <p className="help-text">暂无举报记录</p>
          ) : (
            <ul className="materials-list">
              {reports.map((report) => {
                const typeLabel =
                  REPORT_TARGET_OPTIONS.find((option) => option.value === report.targetType)?.label || report.targetType;
                const statusLabel =
                  REPORT_STATUS_OPTIONS.find((option) => option.value === report.status)?.label || report.status;
                const targetHidden = report.targetStatus?.toLowerCase() === 'hidden';
                return (
                  <li key={report.id} className="purchase-row">
                    <div>
                      <strong>
                        {typeLabel} · {report.targetLabel || `#${report.targetId}`}
                      </strong>
                      <p className="material-meta">举报理由：{report.reason}</p>
                      <p className="material-meta">
                        举报人：{report.reporterName || report.reporterId || '匿名'} · 状态：{statusLabel}
                        {report.targetStatus ? ` · 目标状态：${report.targetStatus}` : ''}
                      </p>
                      <p className="material-meta">
                        {formatDateTime(report.createdAt) || '-'}
                      </p>
                      {report.targetUrl && (
                        <p className="material-meta">
                          <a className="text-button" href={report.targetUrl} target="_blank" rel="noreferrer">
                            查看目标
                          </a>
                        </p>
                      )}
                    </div>
                    <div className="inline-group wrap">
                      <select
                        value={report.status}
                        onChange={(e) => handleReportFieldUpdate(report.id, 'status', e.target.value)}
                      >
                        {REPORT_STATUS_OPTIONS.filter((option) => option.value).map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <input
                        value={report.adminNote || ''}
                        placeholder="管理员备注"
                        onChange={(e) => handleReportFieldUpdate(report.id, 'adminNote', e.target.value)}
                      />
                      <button
                        className="button primary small"
                        type="button"
                        onClick={() => handleReportUpdate(report.id)}
                        disabled={reportUpdatingId === report.id}
                      >
                        {reportUpdatingId === report.id ? '更新中...' : '更新'}
                      </button>
                      {targetHidden && (
                        <button
                          className="button ghost small"
                          type="button"
                          onClick={() => handleReportRestore(report.id)}
                          disabled={reportRestoringId === report.id}
                        >
                          {reportRestoringId === report.id ? '恢复中...' : '恢复展示'}
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          <PaginationBar
            currentPage={currentReportPage}
            totalItems={reportTotalItems}
            pageSize={reportPageSize}
            loading={reportsLoading}
            onPageChange={handleReportPageChange}
            className="admin-pagination"
          />
        </section>

        <section id="admin-settlements" className="card admin-section">
          <div className="card-title">结算管理</div>
          <p className="help-text">创作者收益申请，按周期审核/结算。</p>
          <div className="inline-group" style={{ marginBottom: 12 }}>
            <button className="button primary" type="button" onClick={reloadPayouts} disabled={payoutLoading}>
              {payoutLoading ? '刷新中...' : '刷新申请列表'}
            </button>
          </div>
          {payoutMessage && (
            <p className={payoutMessage.type === 'error' ? 'error-text' : 'success-text'}>{payoutMessage.text}</p>
          )}
          {payouts.length === 0 ? (
            <p className="help-text">暂无收益申请</p>
          ) : (
            <ul className="materials-list">
              {payouts.map((p) => (
                <li key={p.id} className="purchase-row">
                  <div>
                    <strong>{p.applicantName || '未知用户'}</strong> · {p.alipayName || '-'} · {p.alipayAccount || '-'}
                    <span className="material-meta">联系方式：{p.contactValue} · {p.contactType}</span>
                    <p className="material-meta">
                      周期：{p.cycleKey || '-'} · 状态：{p.status} · 实名：{p.kycStatus || '-'} · 提交时间：
                      {formatDateTime(p.createdAt) || '--'}
                    </p>
                    {p.reviewNotes && <p className="material-meta">审核备注：{p.reviewNotes}</p>}
                    {p.earnings && (
                      <p className="material-meta">
                        预计实得：¥{scaleToActual(p.earnings.payoutAmount ?? 0).toFixed(2)} · 未结算累计：¥
                        {scaleToActual(p.earnings.unclaimedPayoutTotal ?? 0).toFixed(2)}
                      </p>
                    )}
                    {payoutDetailOpen[p.id!] && (
                      <div className="request-detail-responses" style={{ marginTop: 12 }}>
                        {payoutDetailLoading[p.id!] && <p className="help-text">明细加载中...</p>}
                        {!payoutDetailLoading[p.id!] && (payoutDetails[p.id!] || []).length === 0 && (
                          <p className="help-text">暂无可结算明细</p>
                        )}
                        {!payoutDetailLoading[p.id!] && (payoutDetails[p.id!] || []).length > 0 && (
                          <ul className="request-response-list">
                            {(payoutDetails[p.id!] || []).map((detail) => (
                              <li key={detail.settlementId}>
                                <div className="request-response-header">
                                  <span>{detail.materialTitle || '资料结算'}</span>
                                  <span className="help-text">
                                    {detail.sourceType || '-'} · {detail.policyVersion || '-'}
                                  </span>
                                </div>
                                <p className="material-meta">
                                  毛额 ¥{scaleToActual(detail.grossAmount ?? 0).toFixed(2)} · 平台费 ¥
                                  {scaleToActual(detail.platformFee ?? 0).toFixed(2)} · 净额 ¥
                                  {scaleToActual(detail.payoutAmount ?? 0).toFixed(2)}
                                </p>
                                <p className="help-text">
                                  结算时间：{detail.scheduledPayoutAt ? formatDateTime(detail.scheduledPayoutAt) : '--'} · 状态：
                                  {detail.status || '-'}
                                </p>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="inline-group wrap">
                    <button
                      className="button ghost small"
                      type="button"
                      disabled={p.status !== 'PENDING' || p.kycStatus !== 'VERIFIED'}
                      onClick={() => handlePayoutAction(p.id!, 'APPROVED')}
                    >
                      通过
                    </button>
                    <button className="button ghost small" type="button" onClick={() => togglePayoutDetails(p.id!)}>
                      {payoutDetailOpen[p.id!] ? '收起明细' : '查看明细'}
                    </button>
                    <button
                      className="button ghost small"
                      type="button"
                      onClick={() => handlePayoutAction(p.id!, 'REJECTED', '资料不全')}
                    >
                      拒绝
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section id="admin-monthly-payout" className="card admin-section">
          <div className="card-title">月度打款</div>
          <p className="help-text">仅统计「支付成功且已下载」的付费记录；按下载时订单实得金额汇总，重复下载不重复计入。</p>
          <div className="inline-group wrap" style={{ marginBottom: 12, alignItems: 'center' }}>
            <label className="material-meta" htmlFor="monthly-payout-month">
              结算月份
            </label>
            <input
              id="monthly-payout-month"
              type="month"
              value={monthlyPayoutMonth}
              onChange={(e) => setMonthlyPayoutMonth(e.target.value)}
              max={getCurrentMonthValue()}
            />
            <button
              className="button primary small"
              type="button"
              onClick={() => reloadMonthlyPayoutOverview(monthlyPayoutMonth)}
              disabled={monthlyPayoutLoading}
            >
              {monthlyPayoutLoading ? '加载中...' : '查询'}
            </button>
          </div>
          {monthlyPayoutMessage && (
            <p className={monthlyPayoutMessage.type === 'error' ? 'error-text' : 'success-text'}>
              {monthlyPayoutMessage.text}
            </p>
          )}
          {monthlyPayoutOverview && (
            <p className="help-text">
              区间：{monthlyPayoutOverview.periodStart || '--'} 至 {monthlyPayoutOverview.periodEnd || '--'} · 创作者：
              {monthlyPayoutOverview.creatorCount ?? 0} 人 · 应付合计：¥
              {((monthlyPayoutOverview.totalPayoutAmount ?? 0) / 100).toFixed(2)} · 付费下载：
              {monthlyPayoutOverview.totalPaidDownloadCount ?? 0} 次
            </p>
          )}
          {!monthlyPayoutOverview || (monthlyPayoutOverview.items || []).length === 0 ? (
            <p className="help-text">该月份暂无可打款记录。</p>
          ) : (
            <ul className="materials-list">
              {(monthlyPayoutOverview.items || []).map((item) => {
                const displayName = item.uploaderNickname || item.uploaderUsername || `用户 #${item.uploaderId}`;
                const marking = monthlyPayoutMarkingId === item.uploaderId;
                return (
                  <li key={`${item.uploaderId}-${monthlyPayoutOverview.monthKey}`} className="purchase-row">
                    <div>
                      <strong>{displayName}</strong>
                      <p className="material-meta">
                        用户ID：{item.uploaderId} · 应付金额：¥{((item.payoutAmount ?? 0) / 100).toFixed(2)} · 计入下载：
                        {item.paidDownloadCount ?? 0}
                      </p>
                      <p className="material-meta">
                        收款码：{item.hasPayoutQr ? '已上传' : '未上传'}
                        {item.markedPaid
                          ? ` · 已打款${item.markedAt ? `：${formatDateTime(item.markedAt)}` : ''}${
                              item.markedByName ? `（${item.markedByName}）` : ''
                            }`
                          : ' · 未打款'}
                      </p>
                    </div>
                    <div className="inline-group wrap">
                      <button
                        className="button ghost small"
                        type="button"
                        disabled={!item.hasPayoutQr}
                        onClick={() => openPayoutQrModal(item)}
                        style={!item.hasPayoutQr ? { opacity: 0.5, cursor: 'not-allowed' } : undefined}
                      >
                        查看收款码
                      </button>
                      <button
                        className={`button ${item.markedPaid ? 'ghost' : 'primary'} small`}
                        type="button"
                        disabled={marking}
                        onClick={() => handleMonthlyMark(item, !item.markedPaid)}
                      >
                        {marking ? '处理中...' : item.markedPaid ? '撤销已打款' : '标记已打款'}
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section id="admin-schedule" className="card admin-section">
          <div className="card-title">上线日期 / 结算日</div>
          <p className="help-text">首结算日 = 上线日 + 7 天，可选自定义下一结算日。</p>
          <form className="form-grid" onSubmit={submitSchedule}>
            <div className="form-item">
              <label htmlFor="launch-date">上线日期</label>
              <input
                id="launch-date"
                type="date"
                value={scheduleForm.launchDate}
                onChange={(e) => setScheduleForm((prev) => ({ ...prev, launchDate: e.target.value }))}
                required
              />
            </div>
            <div className="form-item">
              <label htmlFor="next-payout-date">下一结算日（可选）</label>
              <input
                id="next-payout-date"
                type="date"
                value={scheduleForm.nextPayoutDate}
                onChange={(e) => setScheduleForm((prev) => ({ ...prev, nextPayoutDate: e.target.value }))}
              />
            </div>
            <div className="form-item">
              <button className="button primary" type="submit">
                {scheduleLoading ? '更新中...' : '更新'}
              </button>
            </div>
          </form>
          {scheduleMessage && (
            <p className={scheduleMessage.type === 'error' ? 'error-text' : 'success-text'}>{scheduleMessage.text}</p>
          )}
          {schedule && (
            <div className="help-text">
              <div>上线日期：{schedule.launchDate || '--'}</div>
              <div>上次结算：{schedule.lastPayoutDate || '--'}</div>
              <div>下一结算：{schedule.nextPayoutDate || '--'}</div>
              <div>
                所有结算日：
                {schedule.recentPayoutDates && schedule.recentPayoutDates.length > 0
                  ? schedule.recentPayoutDates.join(' / ')
                  : '--'}
              </div>
            </div>
          )}
        </section>

        <section id="admin-admins" className="card admin-section">
          <div className="card-title">创建新的管理员</div>
          <form className="form-grid" onSubmit={handleCreate}>
            <div className="form-item">
              <label htmlFor="new-username">用户名</label>
              <input
                id="new-username"
                value={form.username}
                onChange={(e) => setForm((prev) => ({ ...prev, username: e.target.value }))}
                required
              />
            </div>
            <div className="form-item">
              <label htmlFor="new-password">密码</label>
              <input
                id="new-password"
                type="password"
                value={form.password}
                onChange={(e) => setForm((prev) => ({ ...prev, password: e.target.value }))}
                required
              />
            </div>
            <div className="form-item">
              <label htmlFor="new-nickname">昵称（可选）</label>
              <input
                id="new-nickname"
                value={form.nickname}
                onChange={(e) => setForm((prev) => ({ ...prev, nickname: e.target.value }))}
              />
            </div>
            <div className="form-item">
              <label>角色</label>
              <div className="inline-group wrap">
                <label className="choice">
                  <input
                    type="checkbox"
                    checked={form.admin}
                    onChange={(e) => setForm((prev) => ({ ...prev, admin: e.target.checked }))}
                  />
                  管理员
                </label>
                <label className="choice">
                  <input
                    type="checkbox"
                    checked={form.developer}
                    onChange={(e) => setForm((prev) => ({ ...prev, developer: e.target.checked }))}
                  />
                  开发者
                </label>
              </div>
            </div>
            <div className="form-item">
              <button className="button primary" type="submit" disabled={submitting}>
                {submitting ? '创建中...' : '创建账号'}
              </button>
            </div>
          </form>
          {message && <p className={message.type === 'error' ? 'error-text' : 'success-text'}>{message.text}</p>}
        </section>

        <section id="admin-users" className="card admin-section">
          <div className="card-title">用户列表</div>
          <form className="inline-form" onSubmit={handleUserSearch} style={{ marginBottom: 16 }}>
            <input
              type="text"
              placeholder="搜索用户名或昵称"
              value={userSearch}
              onChange={(e) => setUserSearch(e.target.value)}
            />
            <button className="button primary" type="submit">
              查找
            </button>
            <button
              className="button ghost"
              type="button"
              onClick={() => {
                setUserSearch('');
                reloadUsers();
              }}
            >
              重置
            </button>
          </form>
          {users.length === 0 ? (
            <p className="help-text">暂无用户</p>
          ) : (
            <ul className="materials-list">
              {users.map((u) => (
                <li key={u.id} className="purchase-row">
                  <div>
                    <strong>{u.username}</strong> · {u.nickname || '未填写昵称'}
                    <p className="material-meta">
                      role_mask={u.roleMask} · 创建于 {formatDateTime(u.createdAt) || '--'}
                      {typeof u.totalEarnings === 'number' && (
                        <span style={{ marginLeft: 8 }}>| 应得收入 ¥{(u.totalEarnings ?? 0).toFixed(2)}</span>
                      )}
                      {actualTotalValue !== null && totalEarnings > 0 && typeof u.totalEarnings === 'number' && (
                        <span style={{ marginLeft: 8 }}>
                          | 预计实得 ¥{(((u.totalEarnings ?? 0) / totalEarnings) * actualTotalValue).toFixed(2)}
                        </span>
                      )}
                    </p>
                  </div>
                  <div className="inline-group wrap">
                    <button
                      className="button ghost small"
                      type="button"
                      onClick={() => {
                        const nextMask = u.roleMask ^ RoleMask.ADMIN;
                        toggleRole(u.id, nextMask);
                      }}
                    >
                      {u.roleMask & RoleMask.ADMIN ? '移除管理员' : '设为管理员'}
                    </button>
                    <button
                      className="button ghost small"
                      type="button"
                      onClick={() => {
                        const nextMask = u.roleMask ^ RoleMask.DEVELOPER;
                        toggleRole(u.id, nextMask);
                      }}
                    >
                      {u.roleMask & RoleMask.DEVELOPER ? '移除开发者' : '设为开发者'}
                    </button>
                  </div>
                  <div className="user-note-tools">
                    <textarea
                      placeholder="管理员留言（会展示给该用户）"
                      value={noteDrafts[u.id] ?? ''}
                      onChange={(e) => setNoteDrafts((prev) => ({ ...prev, [u.id]: e.target.value }))}
                    />
                    <div className="inline-group wrap">
                      <button className="button primary small" type="button" onClick={() => handleSendNote(u.id)}>
                        发送留言
                      </button>
                      <button className="button ghost small" type="button" onClick={() => toggleNotePanel(u.id)}>
                        {notePanelOpen[u.id] ? '收起留言' : '查看留言'}
                      </button>
                    </div>
                    {noteAlerts[u.id] && (
                      <p className={noteAlerts[u.id]?.type === 'error' ? 'error-text' : 'success-text'}>
                        {noteAlerts[u.id]?.text}
                      </p>
                    )}
                    {notePanelOpen[u.id] && (
                      <div className="user-note-list">
                        {notesLoading[u.id] ? (
                          <p className="help-text">加载中...</p>
                        ) : (userNotes[u.id] || []).length === 0 ? (
                          <p className="help-text">暂无留言</p>
                        ) : (
                          <ul>
                            {userNotes[u.id]?.map((note) => (
                              <li key={note.id}>
                                <p>{note.message}</p>
                                <span>
                                  {note.adminNickname || note.adminUsername || '管理员'} ·{' '}
                                  {formatDateTime(note.createdAt)}
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
        </div>

        <AdminPayoutQrModal
          open={payoutQrModal.open}
          loading={payoutQrModal.loading}
          error={payoutQrModal.error}
          url={payoutQrModal.url}
          title={payoutQrModal.title}
          onClose={closePayoutQrModal}
        />
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<AdminPageProps> = async (ctx) => {
  const session = readSession(ctx.req);
  if (
    !session.user ||
    (!hasRole(session.user.roleMask, RoleMask.ADMIN) && !hasRole(session.user.roleMask, RoleMask.DEVELOPER))
  ) {
    return {
      redirect: {
        destination: '/login?next=/admin',
        permanent: false,
      },
    };
  }
  let users: UserSummary[] = [];
  let feedbacks: FeedbackEntry[] = [];
  let volunteers: VolunteerApplicationEntry[] = [];
  let materials: AdminMaterial[] = [];
  let materialsMeta = { page: 0, size: 15, total: 0 };
  let marketItems: AdminMarketItem[] = [];
  let marketMeta: AdminListMeta = { page: 1, size: 15, total: 0 };
  let reports: AdminReport[] = [];
  let reportsMeta: AdminListMeta = { page: 0, size: 15, total: 0 };
  if (session.token) {
    try {
      const dashboard = await fetchAdminInitialDashboard(session.token, getRequestOrigin(ctx.req));
      users = dashboard.users;
      feedbacks = dashboard.feedbacks;
      volunteers = dashboard.volunteers;
      materials = dashboard.materials;
      materialsMeta = dashboard.materialsMeta;
      marketItems = dashboard.marketItems;
      marketMeta = dashboard.marketMeta;
      reports = dashboard.reports;
      reportsMeta = dashboard.reportsMeta;
    } catch (err) {
      // ignore fetch errors in SSR
    }
  }
  return {
    props: {
      user: session.user,
      users,
      token: session.token || '',
      feedbacks,
      volunteers,
      materials,
      materialsMeta,
      marketItems,
      marketMeta,
      reports,
      reportsMeta,
    },
  };
};
