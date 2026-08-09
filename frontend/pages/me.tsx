import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import MeAccountSections from '../components/me/MeAccountSections';
import MeContentSections from '../components/me/MeContentSections';
import MePayoutSection from '../components/me/MePayoutSection';
import MeSecuritySection from '../components/me/MeSecuritySection';
import { useAppDialog } from '../components/AppDialogProvider';
import NavBar from '../components/NavBar';
import ProfileCard from '../components/ProfileCard';
import { readSession } from '../lib/auth';
import { fetchAccountProfile, fetchProfile } from '../lib/api';
import { fetchBackend, getRequestOrigin } from '../lib/apiBase';
import { ensureApiSuccess, readApiEnvelope, unwrapApiResponse } from '../lib/apiEnvelope';
import { toErrorMessage } from '../lib/errors';
import { formatDateTime } from '../lib/format';
import { sortUploadsByTime, UploadTimeOrder } from '../lib/profileUploads';
import { marketPath, materialPath } from '../lib/slug';
import { SessionUser } from '../types/user';
import { UserAccountProfile, UserFollowItem } from '../types/userProfile';
import { ProfileSummary, PurchaseItem, UploadItem, MarketWantItem, MarketListingItem } from '../types/profile';

const ADMIN_QQ = '245934740';
const EMPTY_UPLOADS: UploadItem[] = [];

interface MePageProps {
  user: SessionUser | null;
  summary: ProfileSummary | null;
  account: UserAccountProfile | null;
}

interface CaptchaState {
  captchaId: string;
  imageBase64: string;
}

const ME_NAV_GROUPS = [
  {
    label: '我的主页',
    items: [
      { id: 'profile', label: '个人主页设置' },
      { id: 'security', label: '安全设置' },
    ],
  },
  {
    label: '内容与资料',
    items: [
      { id: 'download-quota', label: '下载次数' },
      { id: 'uploads', label: '我的投稿' },
      { id: 'purchases', label: '最近购买' },
      { id: 'wants', label: '我的想要' },
    ],
  },
  {
    label: '交易与收益',
    items: [
      { id: 'listings', label: '校园好物' },
      { id: 'payout', label: '创作者收益' },
    ],
  },
];

export default function MePage({ user, summary, account }: MePageProps) {
  const dialog = useAppDialog();
  const router = useRouter();
  const defaultIdentifier = user?.email || user?.username || '';
  const [accountProfile, setAccountProfile] = useState<UserAccountProfile | null>(account);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [passwordForm, setPasswordForm] = useState({ oldPassword: '', newPassword: '', confirm: '' });
  const [emailResetForm, setEmailResetForm] = useState({ identifier: defaultIdentifier, newPassword: '', confirm: '', code: '' });
  const [resetCaptcha, setResetCaptcha] = useState<CaptchaState>({ captchaId: '', imageBase64: '' });
  const [resetCaptchaCode, setResetCaptchaCode] = useState('');
  const [emailResetMessage, setEmailResetMessage] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [emailResetCooldown, setEmailResetCooldown] = useState(0);
  const [emailResetLoading, setEmailResetLoading] = useState(false);
  const [pwdMessage, setPwdMessage] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [pwdLoading, setPwdLoading] = useState(false);
  const [bindForm, setBindForm] = useState({ email: user?.email || '', code: '' });
  const [bindVerified, setBindVerified] = useState<boolean>(!!user?.verified);
  const [bindMessage, setBindMessage] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [bindLoading, setBindLoading] = useState(false);
  const [bindCooldown, setBindCooldown] = useState(0);
  const [deletingMaterialId, setDeletingMaterialId] = useState<number | null>(null);
  const [deletingListingId, setDeletingListingId] = useState<number | null>(null);
  const freeStatus = summary?.freeDownloadStatus;
  const adminNotes = summary?.adminNotes ?? [];
  const totalDownloads = summary?.totalDownloads ?? 0;
  const uniqueDownloaders = summary?.uniqueDownloaders ?? 0;
  const totalEarnings = summary?.totalEarnings ?? 0;
  const [followTab, setFollowTab] = useState<'following' | 'followers'>('following');
  const [followingUsers, setFollowingUsers] = useState<UserFollowItem[]>([]);
  const [followersUsers, setFollowersUsers] = useState<UserFollowItem[]>([]);
  const [followLoading, setFollowLoading] = useState(false);
  const [followMessage, setFollowMessage] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [activeSection, setActiveSection] = useState('profile');
  const [purchasesExpanded, setPurchasesExpanded] = useState(false);
  const [wantsExpanded, setWantsExpanded] = useState(false);
  const [uploadsExpanded, setUploadsExpanded] = useState(false);
  const [uploadTimeOrder, setUploadTimeOrder] = useState<UploadTimeOrder>('newest');
  const [listingsExpanded, setListingsExpanded] = useState(false);
  const purchases = summary?.purchases ?? [];
  const marketWants = summary?.marketWants ?? [];
  const uploads = summary?.uploads ?? EMPTY_UPLOADS;
  const marketListings = summary?.marketListings ?? [];
  const sortedUploads = useMemo(() => sortUploadsByTime(uploads, uploadTimeOrder), [uploads, uploadTimeOrder]);
  const visiblePurchases = purchasesExpanded ? purchases : purchases.slice(0, 5);
  const visibleMarketWants = wantsExpanded ? marketWants : marketWants.slice(0, 5);
  const visibleUploads = uploadsExpanded ? sortedUploads : sortedUploads.slice(0, 5);
  const visibleMarketListings = listingsExpanded ? marketListings : marketListings.slice(0, 5);
  const canExpandPurchases = purchases.length > 5;
  const canExpandMarketWants = marketWants.length > 5;
  const canExpandUploads = uploads.length > 5;
  const canExpandMarketListings = marketListings.length > 5;

  useEffect(() => {
    if (bindCooldown <= 0) return;
    const timer = setInterval(() => {
      setBindCooldown((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [bindCooldown]);

  useEffect(() => {
    if (emailResetCooldown <= 0) return;
    const timer = setInterval(() => {
      setEmailResetCooldown((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [emailResetCooldown]);

  useEffect(() => {
    setEmailResetForm((prev) => ({ ...prev, identifier: defaultIdentifier }));
  }, [defaultIdentifier]);

  useEffect(() => {
    const loadFollowLists = async () => {
      if (!user?.id) return;
      setFollowLoading(true);
      setFollowMessage(null);
      try {
        const loadList = async (path: string) => {
          const resp = await fetchBackend(path);
          return unwrapApiResponse<UserFollowItem[]>(resp, '加载关注列表失败');
        };
        const [following, followers] = await Promise.all([
          loadList(`/users/${user.id}/following`),
          loadList(`/users/${user.id}/followers`),
        ]);
        setFollowingUsers(following);
        setFollowersUsers(followers);
      } catch (e: unknown) {
        setFollowMessage({ type: 'error', message: toErrorMessage(e, '加载关注列表失败') });
      } finally {
        setFollowLoading(false);
      }
    };
    loadFollowLists();
  }, [user?.id]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const ids = ME_NAV_GROUPS.flatMap((group) => group.items.map((item) => item.id));
    const sections = ids
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => Boolean(el));
    if (sections.length === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => (a.boundingClientRect.top ?? 0) - (b.boundingClientRect.top ?? 0));
        if (visible.length > 0) {
          setActiveSection(visible[0].target.id);
        }
      },
      { rootMargin: '-15% 0px -55% 0px', threshold: [0.12, 0.35, 0.6] }
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  const freeDownloadsLeft = freeStatus?.unlimited ? '无限' : freeStatus?.remaining ?? 0;
  const notifyQuotaLimit = (message?: string) => {
    void dialog.alert({
      title: '下载次数已用完',
      message: message || '下载次数已用完，如需继续下载请联系管理员重置额度。',
    });
  };

  const handleDownload = async (materialId: number) => {
    setToast(null);
    try {
      const resp = await fetchBackend(`/materials/${materialId}/downloads`, { method: 'POST' });
      const json = await readApiEnvelope<{ url?: string }>(resp);
      if (resp.status === 403 && json?.error?.code === 'DOWNLOAD_QUOTA_EXHAUSTED') {
        notifyQuotaLimit(json.msg);
      }
      if (!resp.ok || !json.ok || !json.data?.url) {
        throw new Error(json.msg || '获取下载链接失败');
      }
      setToast({ type: 'success', message: '下载链接已生成，请记得尊重知识创作者的辛勤付出，不要外传或用于商业用途哦~' });
      const link = document.createElement('a');
      link.href = json.data.url;
      link.style.display = 'none';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (error: unknown) {
      setToast({ type: 'error', message: toErrorMessage(error, '下载失败') });
    }
  };
  const fetchResetCaptcha = async () => {
    try {
      const resp = await fetchBackend('/captchas');
      const data = await unwrapApiResponse<CaptchaState>(resp, '获取验证码失败');
      setResetCaptcha(data);
      setResetCaptchaCode('');
    } catch (err: unknown) {
      setEmailResetMessage({ type: 'error', message: toErrorMessage(err, '获取验证码失败') });
    }
  };

  useEffect(() => {
    if (!user) return;
    fetchResetCaptcha();
  }, [user]);

  const sendEmailResetCode = async () => {
    setEmailResetMessage(null);
    if (!emailResetForm.identifier) {
      setEmailResetMessage({ type: 'error', message: '请输入账号或已绑定的邮箱' });
      return;
    }
    if (!emailResetForm.newPassword || emailResetForm.newPassword.length < 6) {
      setEmailResetMessage({ type: 'error', message: '请先填写长度不少于 6 位的新密码' });
      return;
    }
    if (emailResetForm.newPassword !== emailResetForm.confirm) {
      setEmailResetMessage({ type: 'error', message: '两次输入的新密码不一致' });
      return;
    }
    if (!resetCaptcha.captchaId || !resetCaptchaCode) {
      setEmailResetMessage({ type: 'error', message: '请先完成图形验证码' });
      return;
    }
    setEmailResetLoading(true);
    try {
      const resp = await fetchBackend('/password-resets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          identifier: emailResetForm.identifier,
          newPassword: emailResetForm.newPassword,
          captchaId: resetCaptcha.captchaId,
          captchaCode: resetCaptchaCode,
        }),
      });
      const json = await ensureApiSuccess<{ resendAfterSeconds?: number }>(resp, '发送验证码失败');
      setEmailResetCooldown(json.data?.resendAfterSeconds ?? 60);
      setEmailResetMessage({ type: 'success', message: '如果该账号存在且已绑定邮箱，验证码会发送到对应邮箱，请在 5 分钟内完成验证。' });
    } catch (error: unknown) {
      setEmailResetMessage({ type: 'error', message: toErrorMessage(error, '发送验证码失败') });
    } finally {
      setEmailResetLoading(false);
      fetchResetCaptcha();
    }
  };

  const confirmEmailReset = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setEmailResetMessage(null);
    if (!emailResetForm.identifier) {
      setEmailResetMessage({ type: 'error', message: '请输入账号或已绑定的邮箱' });
      return;
    }
    if (!emailResetForm.code) {
      setEmailResetMessage({ type: 'error', message: '请输入邮箱验证码' });
      return;
    }
    if (!emailResetForm.newPassword || emailResetForm.newPassword.length < 6) {
      setEmailResetMessage({ type: 'error', message: '请先填写新的密码' });
      return;
    }
    if (emailResetForm.newPassword !== emailResetForm.confirm) {
      setEmailResetMessage({ type: 'error', message: '两次输入的新密码不一致' });
      return;
    }
    setEmailResetLoading(true);
    try {
      const resp = await fetchBackend('/password-resets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          identifier: emailResetForm.identifier,
          newPassword: emailResetForm.newPassword,
          code: emailResetForm.code,
        }),
      });
      await ensureApiSuccess(resp, '重置密码失败');
      setEmailResetMessage({ type: 'success', message: '重置成功，请使用新密码登录。' });
      setEmailResetCooldown(0);
      setEmailResetForm((prev) => ({ ...prev, newPassword: '', confirm: '', code: '' }));
    } catch (error: unknown) {
      setEmailResetMessage({ type: 'error', message: toErrorMessage(error, '重置密码失败') });
    } finally {
      setEmailResetLoading(false);
    }
  };

  const formatPrice = (value: number) => `¥${value.toFixed(2)}`;
  const accountAssetCards = [
    { label: '剩余下载', value: `${freeDownloadsLeft}` },
    { label: '我的投稿', value: `${uploads.length}` },
    { label: '最近购买', value: `${purchases.length}` },
    { label: '创作者收益', value: formatPrice(totalEarnings) },
  ];
  const accountQuickLinks = [
    { href: '#uploads', label: '我的投稿', desc: '更新资料' },
    { href: '#purchases', label: '最近购买', desc: '查看下载' },
    { href: '#payout', label: '创作者收益', desc: '收款设置' },
    { href: '#security', label: '安全设置', desc: '账号安全' },
  ];

  const sendBindCode = async () => {
    setBindLoading(true);
    setBindMessage(null);
    try {
      const resp = await fetchBackend('/me/email', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: bindForm.email }),
      });
      const json = await ensureApiSuccess<{ resendAfterSeconds?: number }>(resp, '发送验证码失败');
      const resendAfter = json.data?.resendAfterSeconds ?? 30;
      setBindCooldown(resendAfter);
      setBindMessage({ type: 'success', message: '验证码已发送至邮箱，请在 5 分钟内完成绑定。' });
    } catch (error: unknown) {
      setBindMessage({ type: 'error', message: toErrorMessage(error, '发送验证码失败') });
    } finally {
      setBindLoading(false);
    }
  };

  const confirmBindEmail = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!bindForm.code) {
      setBindMessage({ type: 'error', message: '请输入验证码' });
      return;
    }
    setBindLoading(true);
    setBindMessage(null);
    try {
      const resp = await fetchBackend('/me/email', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: bindForm.email, code: bindForm.code }),
      });
      await ensureApiSuccess(resp, '绑定失败');
      setBindVerified(true);
      setBindMessage({ type: 'success', message: '邮箱绑定成功' });
      setBindForm((prev) => ({ ...prev, code: '' }));
    } catch (error: unknown) {
      setBindMessage({ type: 'error', message: toErrorMessage(error, '绑定失败') });
    } finally {
      setBindLoading(false);
    }
  };

  const renderPurchase = (item: PurchaseItem) => (
    <li key={item.orderId} className="purchase-row">
      <div>
        <strong>{item.title}</strong>
        <p className="material-meta">
          {item.free ? '免费' : `¥${item.amount.toFixed(2)}`} · {item.status} ·{' '}
          {formatDateTime(item.createdAt)}
        </p>
        {item.hasNetdisk && (
          <p className="help-text">
            网盘：
            {item.netdiskUrl ? (
              <a href={item.netdiskUrl} target="_blank" rel="noopener noreferrer">
                打开链接
              </a>
            ) : (
              '暂无链接'
            )}
            {item.netdiskPassword && <span> · 提取码：{item.netdiskPassword}</span>}
            {item.netdiskExpiredAt && <span> · 建议 {item.netdiskExpiredAt} 前校验</span>}
          </p>
        )}
      </div>
      <div className="inline-group">
        <Link className="button ghost small" href={materialPath(item.materialId, item.title)}>
          查看详情
        </Link>
        {item.hasFile && (
          <button className="button primary small" type="button" onClick={() => handleDownload(item.materialId)}>
            下载
          </button>
        )}
      </div>
    </li>
  );

  const renderUpload = (item: UploadItem) => (
    <li key={item.materialId} className="purchase-row upload-row">
      <div>
        <strong>{item.title}</strong>
        <p className="material-meta">
          {item.free ? '免费' : `¥${item.price.toFixed(2)}`} · 销量 {item.salesCount} · 下载 {item.downloadCount} ·{' '}
          {formatDateTime(item.createdAt)}
        </p>
      </div>
      <div className="inline-group">
        <Link className="button ghost small" href={materialPath(item.materialId, item.title)}>
          查看
        </Link>
        <button
          className="button primary small"
          type="button"
          onClick={() => router.push(`/upload?materialId=${item.materialId}`)}
        >
          更新资料
        </button>
        <button
          className="button danger small"
          type="button"
          disabled={deletingMaterialId === item.materialId}
          onClick={() => handleDeleteUpload(item.materialId)}
        >
          {deletingMaterialId === item.materialId ? '删除中...' : '删除'}
        </button>
      </div>
    </li>
  );

  const renderMarketWant = (item: MarketWantItem) => (
    <li key={`want-${item.itemId}-${item.createdAt}`} className="purchase-row">
      <div>
        <strong>{item.title}</strong>
        <p className="material-meta">
          {formatPrice(item.price)} · {item.wantCount ?? 0} 人想要 · 卖家 {item.sellerName || '匿名同学'} ·{' '}
          {formatDateTime(item.createdAt)}
        </p>
      </div>
      <Link className="button ghost small" href={marketPath(item.itemId, item.title)}>
        查看商品
      </Link>
    </li>
  );

  const renderMarketListing = (item: MarketListingItem) => {
    const statusLabel = item.status === 'SALE' ? '在售' : '已售出';
    return (
      <li key={`listing-${item.itemId}`} className="purchase-row">
        <div>
          <strong>{item.title}</strong>
          <p className="material-meta">
            {formatPrice(item.price)} · {item.wantCount ?? 0} 人想要 · 状态：{statusLabel} ·{' '}
            {formatDateTime(item.createdAt)}
          </p>
        </div>
        <div className="inline-group">
          <Link className="button ghost small" href={marketPath(item.itemId, item.title)}>
            查看
          </Link>
          {item.status === 'SALE' && (
            <button
              className="button primary small"
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                handleListingStatus(item.itemId, 'SOLD');
              }}
            >
              标记已售
            </button>
          )}
          <button
            className="button danger small"
            type="button"
            disabled={deletingListingId === item.itemId}
            onClick={(e) => {
              e.stopPropagation();
              handleDeleteListing(item.itemId);
            }}
          >
            {deletingListingId === item.itemId ? '删除中...' : '删除'}
          </button>
        </div>
      </li>
    );
  };

  const handleListingStatus = async (itemId: number, status: 'SALE' | 'SOLD') => {
    setToast(null);
    try {
      const resp = await fetchBackend(`/market/${itemId}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      await ensureApiSuccess(resp, '操作失败');
      setToast({ type: 'success', message: status === 'SOLD' ? '已标记为已售' : '状态已更新' });
      router.replace(router.asPath);
    } catch (error: unknown) {
      setToast({ type: 'error', message: toErrorMessage(error, '操作失败') });
    }
  };

  const handleDeleteUpload = async (materialId: number) => {
    const confirmed = await dialog.confirm({
      title: '删除资料',
      message: '确定删除该资料吗？删除后将从列表隐藏，管理员可协助恢复。',
      confirmText: '删除资料',
      danger: true,
    });
    if (!confirmed) return;
    setToast(null);
    setDeletingMaterialId(materialId);
    try {
      const resp = await fetchBackend(`/materials/${materialId}`, { method: 'DELETE' });
      await ensureApiSuccess(resp, '删除失败');
      setToast({ type: 'success', message: '资料已删除' });
      router.replace(router.asPath);
    } catch (error: unknown) {
      setToast({ type: 'error', message: toErrorMessage(error, '删除失败') });
    } finally {
      setDeletingMaterialId((prev) => (prev === materialId ? null : prev));
    }
  };

  const handleDeleteListing = async (itemId: number) => {
    const confirmed = await dialog.confirm({
      title: '删除商品',
      message: '确定删除该商品吗？删除后不可恢复。',
      confirmText: '删除商品',
      danger: true,
    });
    if (!confirmed) return;
    setToast(null);
    setDeletingListingId(itemId);
    try {
      const resp = await fetchBackend(`/market/${itemId}`, { method: 'DELETE' });
      await ensureApiSuccess(resp, '删除失败');
      setToast({ type: 'success', message: '商品已删除' });
      router.replace(router.asPath);
    } catch (error: unknown) {
      setToast({ type: 'error', message: toErrorMessage(error, '删除失败') });
    } finally {
      setDeletingListingId((prev) => (prev === itemId ? null : prev));
    }
  };

  const submitPasswordChange = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setPwdMessage(null);
    if (!passwordForm.newPassword || passwordForm.newPassword.length < 6) {
      setPwdMessage({ type: 'error', message: '新密码长度至少 6 位' });
      return;
    }
    if (passwordForm.newPassword !== passwordForm.confirm) {
      setPwdMessage({ type: 'error', message: '两次输入的新密码不一致' });
      return;
    }
    setPwdLoading(true);
    try {
      const resp = await fetchBackend('/me/password', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ oldPassword: passwordForm.oldPassword, newPassword: passwordForm.newPassword }),
      });
      await ensureApiSuccess(resp, '修改密码失败');
      setPwdMessage({ type: 'success', message: '密码修改成功，下次登录请使用新密码。' });
      setPasswordForm({ oldPassword: '', newPassword: '', confirm: '' });
    } catch (error: unknown) {
      setPwdMessage({ type: 'error', message: toErrorMessage(error, '修改密码失败') });
    } finally {
      setPwdLoading(false);
    }
  };

  return (
    <>
      <NavBar user={user} />
      <main className="container me-grid">
        <div className="me-layout">
          <aside className="me-sidebar">
            <div className="me-sidebar__brand">个人中心</div>
            {ME_NAV_GROUPS.map((group) => (
              <div key={group.label} className="me-sidebar__group">
                <div className="me-sidebar__label">{group.label}</div>
                <div className="me-sidebar__items">
                  {group.items.map((item) => (
                    <a
                      key={item.id}
                      className={`me-sidebar__item ${activeSection === item.id ? 'active' : ''}`}
                      href={`#${item.id}`}
                      onClick={() => setActiveSection(item.id)}
                    >
                      <span className="me-sidebar__indicator" aria-hidden="true" />
                      <span className="me-sidebar__text">{item.label}</span>
                    </a>
                  ))}
                </div>
              </div>
            ))}
          </aside>

          <div className="me-content">
          <section className="card me-hero" id="overview">
            {user && summary ? (
              <>
                <div className="me-hero__inner">
                  <div className="me-hero__intro">
                    <div className="me-hero__eyebrow">我的 StudyHub</div>
                    <div className="me-hero__title-row">
                      <h1 className="me-hero__title">欢迎回来，{user.nickname}。</h1>
                      <svg className="me-hero__title-icon" viewBox="0 0 24 24" aria-hidden="true">
                        <circle cx="12" cy="8" r="4" fill="none" stroke="currentColor" strokeWidth="1.6" />
                        <path
                          d="M4 21a8 8 0 0 1 16 0"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.6"
                          strokeLinecap="round"
                        />
                      </svg>
                    </div>
                    <p className="me-hero__subtitle">可在此查看最近购买记录与投稿表现。</p>
                  </div>
                </div>
                <div className="me-hero__meta">
                  <span>
                    <strong>{uniqueDownloaders}</strong> 被下载用户数 · <strong>{totalDownloads}</strong> 资料总下载次数
                  </span>
                </div>
                <div className="me-asset-grid" aria-label="个人资产概览">
                  {accountAssetCards.map((item) => (
                    <div key={item.label} className="me-asset-card">
                      <span>{item.label}</span>
                      <strong>{item.value}</strong>
                    </div>
                  ))}
                </div>
                <div className="me-quick-actions" aria-label="个人中心快捷入口">
                  {accountQuickLinks.map((item) => (
                    <a key={item.href} className="me-quick-action" href={item.href}>
                      <span>
                        <strong>{item.label}</strong>
                        <em>{item.desc}</em>
                      </span>
                      <b aria-hidden="true">›</b>
                    </a>
                  ))}
                </div>
              </>
            ) : (
              <>
                <div className="me-hero__eyebrow">我的 StudyHub</div>
                <h1 className="me-hero__title">欢迎来到 StudyHub。</h1>
                <p className="me-hero__subtitle">
                  您当前为游客，<Link className="login-link" href="/login?next=/me">登录</Link>后可查看订单、收藏、投稿与结算信息。
                </p>
                <div className="me-hero__actions">
                  <Link className="button primary" href="/login?next=/me">
                    立即登录
                  </Link>
                </div>
              </>
            )}
          </section>
          {user && summary && accountProfile && (
            <section className="me-profile" id="profile">
              <h2 className="me-profile__title">个人主页概览</h2>
              <ProfileCard
                profile={accountProfile}
                uploads={summary.uploads}
                listings={summary.marketListings ?? []}
                editable
                followingUsers={followingUsers}
                followersUsers={followersUsers}
                followTab={followTab}
                followLoading={followLoading}
                followMessage={followMessage}
                onFollowTabChange={setFollowTab}
                onProfileUpdated={(next) => setAccountProfile(next)}
              />
            </section>
          )}
          {user && summary && (
            <>
              <MeSecuritySection
                userEmail={user.email}
                adminQq={ADMIN_QQ}
                passwordForm={passwordForm} pwdLoading={pwdLoading} pwdMessage={pwdMessage}
                emailResetForm={emailResetForm} resetCaptcha={resetCaptcha} resetCaptchaCode={resetCaptchaCode}
                emailResetLoading={emailResetLoading} emailResetCooldown={emailResetCooldown} emailResetMessage={emailResetMessage}
                onPasswordFormChange={(patch) => setPasswordForm((prev) => ({ ...prev, ...patch }))}
                onEmailResetFormChange={(patch) => setEmailResetForm((prev) => ({ ...prev, ...patch }))}
                onResetCaptchaCodeChange={setResetCaptchaCode}
                onPasswordSubmit={submitPasswordChange}
                onEmailResetSubmit={confirmEmailReset}
                onFetchResetCaptcha={fetchResetCaptcha}
                onSendEmailResetCode={sendEmailResetCode}
              />
              <MeAccountSections
                adminQq={ADMIN_QQ}
                bindForm={bindForm} bindVerified={bindVerified} bindLoading={bindLoading} bindCooldown={bindCooldown}
                bindMessage={bindMessage} currentEmail={user.email} freeDownloadsLeft={freeDownloadsLeft}
                onBindFormChange={(patch) => setBindForm((prev) => ({ ...prev, ...patch }))}
                onSendBindCode={sendBindCode}
                onConfirmBindEmail={confirmBindEmail}
              />
              <MeContentSections
                uploads={sortedUploads} visibleUploads={visibleUploads} uploadsExpanded={uploadsExpanded}
                canExpandUploads={canExpandUploads} uploadTimeOrder={uploadTimeOrder}
                purchases={purchases}
                visiblePurchases={visiblePurchases}
                purchasesExpanded={purchasesExpanded}
                canExpandPurchases={canExpandPurchases}
                marketWants={marketWants}
                visibleMarketWants={visibleMarketWants}
                wantsExpanded={wantsExpanded}
                canExpandMarketWants={canExpandMarketWants}
                marketListings={marketListings}
                visibleMarketListings={visibleMarketListings}
                listingsExpanded={listingsExpanded}
                canExpandMarketListings={canExpandMarketListings}
                renderUpload={renderUpload}
                renderPurchase={renderPurchase}
                renderMarketWant={renderMarketWant}
                renderMarketListing={renderMarketListing}
                onUploadsExpandedChange={setUploadsExpanded} onUploadTimeOrderChange={setUploadTimeOrder}
                onPurchasesExpandedChange={setPurchasesExpanded}
                onWantsExpandedChange={setWantsExpanded}
                onListingsExpandedChange={setListingsExpanded}
              />
              <MePayoutSection totalEarnings={totalEarnings} />
            {adminNotes.length > 0 && (
              <section className="card" id="admin-notes">
                <div className="card-title">管理员留言</div>
                <ul className="note-list">
                  {adminNotes.map((note) => (
                    <li key={note.id}>
                      <p>{note.message}</p>
                      <span>
                        {note.adminNickname || note.adminUsername || '管理员'} · {formatDateTime(note.createdAt)}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            </>
          )}
        {toast && <div className={`alert ${toast.type}`}>{toast.message}</div>}
        </div>
        </div>
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<MePageProps> = async (ctx) => {
  const session = readSession(ctx.req);
  const origin = getRequestOrigin(ctx.req);
  if (!session.user) {
    return {
      redirect: {
        destination: '/login?next=/me',
        permanent: false,
      },
    };
  }
  let summary: ProfileSummary | null = null;
  let account: UserAccountProfile | null = null;
  if (session.token) {
    try {
      summary = await fetchProfile(session.token, origin);
    } catch (error) {
      summary = {
        purchases: [],
        uploads: [],
        marketWants: [],
        marketListings: [],
        adminNotes: [],
        freeDownloadStatus: { remaining: 0, unlimited: false },
        hasNewAlerts: false,
        totalDownloads: 0,
        uniqueDownloaders: 0,
        totalEarnings: 0,
      };
    }
    try {
      account = await fetchAccountProfile(session.token, origin);
    } catch (error) {
      account = null;
    }
  }
  return {
    props: {
      user: session.user,
      summary,
      account,
    },
  };
};
