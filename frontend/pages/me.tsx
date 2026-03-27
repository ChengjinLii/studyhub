import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { FormEvent, useEffect, useState } from 'react';
import NavBar from '../components/NavBar';
import ProfileCard from '../components/ProfileCard';
import { readSession } from '../lib/auth';
import { fetchAccountProfile, fetchProfile } from '../lib/api';
import { fetchBackend, getRequestOrigin } from '../lib/apiBase';
import { formatDateTime } from '../lib/format';
import { marketPath, materialPath } from '../lib/slug';
import { SessionUser } from '../types/user';
import { UserAccountProfile, UserFollowItem } from '../types/userProfile';
import {
  ProfileSummary,
  PurchaseItem,
  UploadItem,
  MarketWantItem,
  MarketListingItem,
} from '../types/profile';

const ADMIN_QQ = '245934740';

interface MePageProps {
  user: SessionUser | null;
  summary: ProfileSummary | null;
  account: UserAccountProfile | null;
}

interface CaptchaState {
  captchaId: string;
  imageBase64: string;
}

export default function MePage({ user, summary, account }: MePageProps) {
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
  const [payoutApp, setPayoutApp] = useState<any>(null);
  const [payoutLoading, setPayoutLoading] = useState(false);
  const [payoutMessage, setPayoutMessage] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [payoutForm, setPayoutForm] = useState({
    alipayAccount: '',
    alipayName: '',
    realName: '',
    idCardNo: '',
    contactType: 'WECHAT',
    contactValue: '',
    notes: '',
  });
  const [followTab, setFollowTab] = useState<'following' | 'followers'>('following');
  const [followingUsers, setFollowingUsers] = useState<UserFollowItem[]>([]);
  const [followersUsers, setFollowersUsers] = useState<UserFollowItem[]>([]);
  const [followLoading, setFollowLoading] = useState(false);
  const [followMessage, setFollowMessage] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [activeSection, setActiveSection] = useState('profile');
  const [purchasesExpanded, setPurchasesExpanded] = useState(false);
  const [wantsExpanded, setWantsExpanded] = useState(false);
  const [uploadsExpanded, setUploadsExpanded] = useState(false);
  const [listingsExpanded, setListingsExpanded] = useState(false);
  const purchases = summary?.purchases ?? [];
  const marketWants = summary?.marketWants ?? [];
  const uploads = summary?.uploads ?? [];
  const marketListings = summary?.marketListings ?? [];
  const visiblePurchases = purchasesExpanded ? purchases : purchases.slice(0, 5);
  const visibleMarketWants = wantsExpanded ? marketWants : marketWants.slice(0, 5);
  const visibleUploads = uploadsExpanded ? uploads : uploads.slice(0, 5);
  const visibleMarketListings = listingsExpanded ? marketListings : marketListings.slice(0, 5);
  const canExpandPurchases = purchases.length > 5;
  const canExpandMarketWants = marketWants.length > 5;
  const canExpandUploads = uploads.length > 5;
  const canExpandMarketListings = marketListings.length > 5;

  const navGroups = [
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
    const loadPayout = async () => {
      setPayoutLoading(true);
      try {
        const resp = await fetchBackend('/creator-payout-applications/me');
        const json = await resp.json();
        if (resp.ok && json.ok) {
          setPayoutApp(json.data);
          if (json.data?.contactType) {
            setPayoutForm((prev) => ({ ...prev, contactType: json.data.contactType, contactValue: json.data.contactValue || '' }));
          }
        }
      } catch (e: any) {
        setPayoutMessage({ type: 'error', message: e.message || '加载收益申请失败' });
      } finally {
        setPayoutLoading(false);
      }
    };
    if (user) {
      loadPayout();
    }
  }, [user]);

  useEffect(() => {
    const loadFollowLists = async () => {
      if (!user?.id) return;
      setFollowLoading(true);
      setFollowMessage(null);
      try {
        const loadList = async (path: string) => {
          const resp = await fetchBackend(path);
          const json = await resp.json();
          if (!resp.ok || !json.ok || !Array.isArray(json.data)) {
            throw new Error(json.msg || '加载关注列表失败');
          }
          return json.data as UserFollowItem[];
        };
        const [following, followers] = await Promise.all([
          loadList(`/users/${user.id}/following`),
          loadList(`/users/${user.id}/followers`),
        ]);
        setFollowingUsers(following);
        setFollowersUsers(followers);
      } catch (e: any) {
        setFollowMessage({ type: 'error', message: e.message || '加载关注列表失败' });
      } finally {
        setFollowLoading(false);
      }
    };
    loadFollowLists();
  }, [user?.id]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const ids = navGroups.flatMap((group) => group.items.map((item) => item.id));
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
  const quickNavItems = [
    { id: 'profile', label: '个人主页', icon: 'profile' },
    { id: 'download-quota', label: '下载次数', icon: 'download' },
    { id: 'purchases', label: '最近购买', icon: 'bag' },
    { id: 'wants', label: '我的想要', icon: 'star' },
    { id: 'uploads', label: '我的投稿', icon: 'upload' },
    { id: 'payout', label: '创作者收益', icon: 'wallet' },
    { id: 'listings', label: '校园好物', icon: 'shop' },
    { id: 'security', label: '安全设置', icon: 'lock' },
  ];
  const quickNavIcons: Record<string, JSX.Element> = {
    profile: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="8" r="4" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path
          d="M4 20a8 8 0 0 1 16 0"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
        />
      </svg>
    ),
    download: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 4v10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" fill="none" />
        <path d="M7 11l5 5 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" fill="none" />
        <path d="M5 20h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" fill="none" />
      </svg>
    ),
    bag: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M6 8h12l-1 12H7L6 8z"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
          fill="none"
        />
        <path d="M9 8a3 3 0 0 1 6 0" stroke="currentColor" strokeWidth="1.8" fill="none" />
      </svg>
    ),
    star: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M12 4l2.3 4.7 5.2.8-3.8 3.7.9 5.3-4.6-2.4-4.6 2.4.9-5.3-3.8-3.7 5.2-.8L12 4z"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
          fill="none"
        />
      </svg>
    ),
    upload: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 19V9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" fill="none" />
        <path d="M7 12l5-5 5 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" fill="none" />
        <path d="M5 19h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" fill="none" />
      </svg>
    ),
    wallet: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M4 7h14a3 3 0 0 1 3 3v6a1 1 0 0 1-1 1H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
          fill="none"
        />
        <path d="M16 12h4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" fill="none" />
      </svg>
    ),
    shop: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M4 10h16l-1 9H5l-1-9z"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
          fill="none"
        />
        <path d="M7 10a5 5 0 0 1 10 0" stroke="currentColor" strokeWidth="1.6" fill="none" />
      </svg>
    ),
    lock: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="5" y="11" width="14" height="9" rx="2" stroke="currentColor" strokeWidth="1.6" fill="none" />
        <path d="M8 11V8a4 4 0 0 1 8 0v3" stroke="currentColor" strokeWidth="1.6" fill="none" />
      </svg>
    ),
  };

  const notifyQuotaLimit = (message?: string) => {
    if (typeof window === 'undefined') return;
    window.alert(message || '下载次数已用完，如需继续下载请联系管理员重置额度。');
  };

  const handleDownload = async (materialId: number) => {
    setToast(null);
    try {
      const resp = await fetchBackend(`/materials/${materialId}/download`);
      const json = await resp.json();
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
    } catch (error: any) {
      setToast({ type: 'error', message: error.message || '下载失败' });
    }
  };


  const submitPayout = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setPayoutMessage(null);
    setPayoutLoading(true);
    try {
      const payload = {
        ...payoutForm,
        alipayName: payoutForm.realName || payoutForm.alipayName,
      };
      const resp = await fetchBackend('/creator-payout-applications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '提交失败');
      }
      setPayoutApp(json.data);
      if (json.data?.status === 'KYC_FAILED') {
        setPayoutMessage({ type: 'error', message: '实名核验失败，请核对姓名与身份证号后重试。' });
      } else if (json.data?.status === 'KYC_PENDING') {
        setPayoutMessage({ type: 'error', message: '核验中断，请稍后再试（1 分钟后可重试）。' });
      } else {
        setPayoutMessage({ type: 'success', message: '提交成功' });
      }
    } catch (err: any) {
      setPayoutMessage({ type: 'error', message: err.message || '提交失败' });
    } finally {
      setPayoutLoading(false);
    }
  };

  const fetchResetCaptcha = async () => {
    try {
      const resp = await fetchBackend('/auth/captcha');
      const json = await resp.json();
      if (!resp.ok || !json.ok || !json.data) {
        throw new Error(json.msg || '获取验证码失败');
      }
      setResetCaptcha(json.data);
      setResetCaptchaCode('');
    } catch (err: any) {
      setEmailResetMessage({ type: 'error', message: err.message || '获取验证码失败' });
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
      const resp = await fetchBackend('/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          identifier: emailResetForm.identifier,
          newPassword: emailResetForm.newPassword,
          captchaId: resetCaptcha.captchaId,
          captchaCode: resetCaptchaCode,
        }),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '发送验证码失败');
      }
      setEmailResetCooldown(json.data?.resendAfterSeconds ?? 60);
      setEmailResetMessage({ type: 'success', message: '验证码已发送至邮箱，请在 5 分钟内完成验证。' });
    } catch (error: any) {
      setEmailResetMessage({ type: 'error', message: error.message || '发送验证码失败' });
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
      const resp = await fetchBackend('/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          identifier: emailResetForm.identifier,
          newPassword: emailResetForm.newPassword,
          code: emailResetForm.code,
        }),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '重置密码失败');
      }
      setEmailResetMessage({ type: 'success', message: '重置成功，请使用新密码登录。' });
      setEmailResetCooldown(0);
      setEmailResetForm((prev) => ({ ...prev, newPassword: '', confirm: '', code: '' }));
    } catch (error: any) {
      setEmailResetMessage({ type: 'error', message: error.message || '重置密码失败' });
    } finally {
      setEmailResetLoading(false);
    }
  };

  const renderPayoutStatus = () => {
    if (!payoutApp) return null;
    const status = payoutApp.status;
    const next = payoutApp.cycleEndDate || payoutApp.cycleKey;
    const earnings = payoutApp.earnings?.payoutAmount ?? 0;
    const unclaimed = payoutApp.earnings?.unclaimedPayoutTotal ?? 0;
    const parts: string[] = [];
    if (status === 'KYC_FAILED') parts.push('实名核验未通过，请核对信息后重新提交');
    if (status === 'KYC_PENDING') parts.push('实名核验中断，请稍后再试');
    if (status === 'PENDING') parts.push(`已提交，等待审核。下次可在 ${next || '-'} 后申请`);
    if (status === 'APPROVED') parts.push(`已通过审核，待结算。预计实得 ¥${(earnings / 100).toFixed(2)}，下次结算日 ${next || '-'}`);
    if (status === 'REJECTED') parts.push(`已拒绝：${payoutApp.reviewNotes || ''}。下次可在 ${next || '-'} 后再试`);
    if (status === 'SETTLED') parts.push(`本周期已结算（至 ${payoutApp.cycleKey || '-'}），下个结算日 ${next || '-'}`);
    if (unclaimed > 0) parts.push(`历史未结算累计：¥${(unclaimed / 100).toFixed(2)}`);
    return parts.join('；');
  };

  const formatPrice = (value: number) => `¥${value.toFixed(2)}`;

  const sendBindCode = async () => {
    setBindLoading(true);
    setBindMessage(null);
    try {
      const resp = await fetchBackend('/auth/bind-email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: bindForm.email }),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '发送验证码失败');
      }
      const resendAfter = json.data?.resendAfterSeconds ?? 30;
      setBindCooldown(resendAfter);
      setBindMessage({ type: 'success', message: '验证码已发送至邮箱，请在 5 分钟内完成绑定。' });
    } catch (error: any) {
      setBindMessage({ type: 'error', message: error.message || '发送验证码失败' });
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
      const resp = await fetchBackend('/auth/bind-email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: bindForm.email, code: bindForm.code }),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '绑定失败');
      }
      setBindVerified(true);
      setBindMessage({ type: 'success', message: '邮箱绑定成功' });
      setBindForm((prev) => ({ ...prev, code: '' }));
    } catch (error: any) {
      setBindMessage({ type: 'error', message: error.message || '绑定失败' });
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
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '操作失败');
      }
      setToast({ type: 'success', message: status === 'SOLD' ? '已标记为已售' : '状态已更新' });
      router.replace(router.asPath);
    } catch (error: any) {
      setToast({ type: 'error', message: error.message || '操作失败' });
    }
  };

  const handleDeleteUpload = async (materialId: number) => {
    if (!window.confirm('确定删除该资料吗？删除后将从列表隐藏，管理员可协助恢复。')) return;
    setToast(null);
    setDeletingMaterialId(materialId);
    try {
      const resp = await fetchBackend(`/materials/${materialId}`, { method: 'DELETE' });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '删除失败');
      }
      setToast({ type: 'success', message: '资料已删除' });
      router.replace(router.asPath);
    } catch (error: any) {
      setToast({ type: 'error', message: error.message || '删除失败' });
    } finally {
      setDeletingMaterialId((prev) => (prev === materialId ? null : prev));
    }
  };

  const handleDeleteListing = async (itemId: number) => {
    if (!window.confirm('确定删除该商品吗？删除后不可恢复。')) return;
    setToast(null);
    setDeletingListingId(itemId);
    try {
      const resp = await fetchBackend(`/market/${itemId}`, { method: 'DELETE' });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '删除失败');
      }
      setToast({ type: 'success', message: '商品已删除' });
      router.replace(router.asPath);
    } catch (error: any) {
      setToast({ type: 'error', message: error.message || '删除失败' });
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
      const resp = await fetchBackend('/auth/password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ oldPassword: passwordForm.oldPassword, newPassword: passwordForm.newPassword }),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '修改密码失败');
      }
      setPwdMessage({ type: 'success', message: '密码修改成功，下次登录请使用新密码。' });
      setPasswordForm({ oldPassword: '', newPassword: '', confirm: '' });
    } catch (error: any) {
      setPwdMessage({ type: 'error', message: error.message || '修改密码失败' });
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
            {navGroups.map((group) => (
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
              </>
            ) : (
              <>
                <div className="me-hero__eyebrow">我的 StudyHub</div>
                <h1 className="me-hero__title">欢迎来到 StudyHub。</h1>
                <p className="me-hero__subtitle">
                  您当前为游客，<a className="login-link" href="/login?next=/me">登录</a>后可查看订单、收藏、投稿与结算信息。
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
              <section className="card" id="security">
                <div className="card-title">修改密码</div>
                <div className="security-block">
                  <h4>已记得旧密码</h4>
                  <form className="form-grid" onSubmit={submitPasswordChange}>
                    <div className="form-item full">
                      <label htmlFor="oldPassword">旧密码</label>
                      <input
                        id="oldPassword"
                        type="password"
                        value={passwordForm.oldPassword}
                        onChange={(e) => setPasswordForm((prev) => ({ ...prev, oldPassword: e.target.value }))}
                        required
                      />
                    </div>
                    <div className="form-item full">
                      <label htmlFor="newPassword">新密码</label>
                      <input
                        id="newPassword"
                        type="password"
                        value={passwordForm.newPassword}
                        onChange={(e) => setPasswordForm((prev) => ({ ...prev, newPassword: e.target.value }))}
                        placeholder="不少于 6 位"
                        required
                      />
                    </div>
                    <div className="form-item full">
                      <label htmlFor="confirmPassword">确认新密码</label>
                      <input
                        id="confirmPassword"
                        type="password"
                        value={passwordForm.confirm}
                        onChange={(e) => setPasswordForm((prev) => ({ ...prev, confirm: e.target.value }))}
                        required
                      />
                    </div>
                    <div className="form-item">
                      <button className="button primary" type="submit" disabled={pwdLoading}>
                        {pwdLoading ? '提交中...' : '更新密码'}
                      </button>
                    </div>
                  </form>
                  <p className="help-text">推荐常规方式修改；若遗忘旧密码，可尝试下方邮箱验证。</p>
                  {pwdMessage && (
                    <p className={pwdMessage.type === 'error' ? 'error-text' : 'success-text'}>{pwdMessage.message}</p>
                  )}
                </div>
                <div className="divider" style={{ margin: '16px 0', borderTop: '1px dashed #e0e4ef' }} />
                <div className="security-block">
                  <h4>忘记旧密码（邮箱验证）</h4>
                  <form className="form-grid" onSubmit={confirmEmailReset}>
                    <div className="form-item full">
                      <label htmlFor="reset-identifier">账号 / 邮箱</label>
                      <input
                        id="reset-identifier"
                        value={emailResetForm.identifier}
                        onChange={(e) => setEmailResetForm((prev) => ({ ...prev, identifier: e.target.value }))}
                        placeholder="请输入已绑定的邮箱或账号"
                        required
                      />
                      <p className="help-text">
                        {user?.email ? `验证码将发送至：${user.email}` : '需先绑定邮箱后才可通过邮箱重置密码。'}
                      </p>
                    </div>
                    <div className="form-item full">
                      <label htmlFor="reset-new-password">新密码</label>
                      <input
                        id="reset-new-password"
                        type="password"
                        value={emailResetForm.newPassword}
                        onChange={(e) => setEmailResetForm((prev) => ({ ...prev, newPassword: e.target.value }))}
                        placeholder="不少于 6 位"
                        required
                      />
                    </div>
                    <div className="form-item full">
                      <label htmlFor="reset-confirm-password">确认新密码</label>
                      <input
                        id="reset-confirm-password"
                        type="password"
                        value={emailResetForm.confirm}
                        onChange={(e) => setEmailResetForm((prev) => ({ ...prev, confirm: e.target.value }))}
                        required
                      />
                    </div>
                    <div className="form-item full">
                      <label htmlFor="reset-captcha">图形验证码</label>
                      <div className="captcha-row">
                        <input
                          id="reset-captcha"
                          value={resetCaptchaCode}
                          onChange={(e) => setResetCaptchaCode(e.target.value)}
                          placeholder="请输入图形验证码"
                          required
                        />
                        {resetCaptcha.imageBase64 ? (
                          <img
                            src={resetCaptcha.imageBase64}
                            alt="验证码"
                            className="captcha-image"
                            onClick={fetchResetCaptcha}
                            role="button"
                            aria-label="点击刷新验证码"
                          />
                        ) : (
                          <button
                            className="button ghost"
                            type="button"
                            onClick={fetchResetCaptcha}
                            disabled={emailResetLoading}
                          >
                            获取验证码
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="form-item full">
                      <label htmlFor="reset-code">邮箱验证码</label>
                      <div className="captcha-row">
                        <input
                          id="reset-code"
                          value={emailResetForm.code}
                          onChange={(e) => setEmailResetForm((prev) => ({ ...prev, code: e.target.value }))}
                          placeholder="输入邮箱验证码"
                          required
                        />
                        <button
                          className="button ghost"
                          type="button"
                          disabled={emailResetLoading || emailResetCooldown > 0 || !emailResetForm.identifier}
                          onClick={sendEmailResetCode}
                        >
                          {emailResetCooldown > 0 ? `重新发送 (${emailResetCooldown}s)` : '发送验证码'}
                        </button>
                      </div>
                    </div>
                    <div className="form-item">
                      <button className="button primary" type="submit" disabled={emailResetLoading}>
                        {emailResetLoading ? '提交中...' : '通过邮箱重置'}
                      </button>
                    </div>
                  </form>
                  <p className="help-text">若邮箱无法使用，仍可联系管理员协助处理（QQ群 {ADMIN_QQ}）。</p>
                  {emailResetMessage && (
                    <p className={emailResetMessage.type === 'error' ? 'error-text' : 'success-text'}>
                      {emailResetMessage.message}
                    </p>
                  )}
                </div>
              </section>
              <section className="card" id="email-binding">
              <div className="card-title">邮箱绑定</div>
              <form className="form-grid" onSubmit={confirmBindEmail}>
                <div className="form-item full">
                  <label htmlFor="bind-email">邮箱地址</label>
                  <input
                    id="bind-email"
                    type="email"
                    value={bindForm.email}
                    onChange={(e) => setBindForm((prev) => ({ ...prev, email: e.target.value }))}
                    placeholder="输入要绑定的邮箱"
                    required
                  />
                  <p className="help-text">
                    状态：{bindVerified ? '已验证' : '未验证'} {user?.email ? `(当前：${user.email})` : ''}
                  </p>
                </div>
                <div className="form-item full">
                  <label htmlFor="bind-code">邮箱验证码</label>
                  <div className="captcha-row">
                    <input
                      id="bind-code"
                      value={bindForm.code}
                      onChange={(e) => setBindForm((prev) => ({ ...prev, code: e.target.value }))}
                      placeholder="输入邮箱验证码"
                      required
                    />
                    <button
                      className="button ghost"
                      type="button"
                      disabled={bindLoading || bindCooldown > 0}
                      onClick={sendBindCode}
                    >
                      {bindCooldown > 0 ? `重新发送 (${bindCooldown}s)` : '发送验证码'}
                    </button>
                  </div>
                </div>
                <div className="form-item">
                  <button className="button primary" type="submit" disabled={bindLoading}>
                    {bindLoading ? '处理中...' : '确认绑定'}
                  </button>
                </div>
              </form>
              {bindMessage && (
                <p className={bindMessage.type === 'error' ? 'error-text' : 'success-text'}>{bindMessage.message}</p>
              )}
            </section>
              <section className="card" id="download-quota">
                <div className="card-title">下载次数额度</div>
                <p>
                  剩余：<strong>{freeDownloadsLeft}</strong> 次 / 200 次上限（含免费与付费资料）。
                </p>
                <p className="help-text">如需重置请联系管理员（QQ群 {ADMIN_QQ}）。</p>
                <div className="inline-group" style={{ marginTop: 8 }}>
                  <Link className="button ghost" href="/">
                    去下载资料
                  </Link>
                  <Link className="button ghost" href="/join">
                    关于我们
                  </Link>
                </div>
              </section>
              <section className="card" id="uploads">
                <div className="card-title">我的投稿</div>
                {uploads.length === 0 ? (
                  <p className="help-text">
                    还没有投稿，<Link href="/upload">前往投稿</Link> 提供优质资料吧。
                  </p>
                ) : (
                  <>
                    <ul className="materials-list">{visibleUploads.map(renderUpload)}</ul>
                    {canExpandUploads && (
                      <button
                        type="button"
                        className="profile-card__expand"
                        onClick={() => setUploadsExpanded((prev) => !prev)}
                        data-expanded={uploadsExpanded}
                      >
                        {uploadsExpanded ? '收起' : '展开全部'}
                      </button>
                    )}
                  </>
                )}
              </section>
              <section className="card" id="purchases">
                <div className="card-title">最近购买</div>
                {purchases.length === 0 ? (
                  <p className="help-text">暂无购买记录，去首页看看吧。</p>
                ) : (
                  <>
                    <ul className="materials-list">{visiblePurchases.map(renderPurchase)}</ul>
                    {canExpandPurchases && (
                      <button
                        type="button"
                        className="profile-card__expand"
                        onClick={() => setPurchasesExpanded((prev) => !prev)}
                        data-expanded={purchasesExpanded}
                      >
                        {purchasesExpanded ? '收起' : '展开全部'}
                      </button>
                    )}
                  </>
                )}
              </section>
              <section className="card" id="wants">
                <div className="card-title">我想要的校园好物</div>
                {marketWants.length === 0 ? (
                  <p className="help-text">
                    还没有关注校园好物，<Link href="/market">去集市逛逛</Link>。
                  </p>
                ) : (
                  <>
                    <ul className="materials-list">{visibleMarketWants.map(renderMarketWant)}</ul>
                    {canExpandMarketWants && (
                      <button
                        type="button"
                        className="profile-card__expand"
                        onClick={() => setWantsExpanded((prev) => !prev)}
                        data-expanded={wantsExpanded}
                      >
                        {wantsExpanded ? '收起' : '展开全部'}
                      </button>
                    )}
                  </>
                )}
              </section>
              <section className="card" id="listings">
                <div className="card-title">我发布的校园好物</div>
                {marketListings.length === 0 ? (
                  <p className="help-text">
                    还没有发布校园好物，<Link href="/market/sell">去集市发布</Link>。
                  </p>
                ) : (
                  <>
                    <ul className="materials-list">{visibleMarketListings.map(renderMarketListing)}</ul>
                    {canExpandMarketListings && (
                      <button
                        type="button"
                        className="profile-card__expand"
                        onClick={() => setListingsExpanded((prev) => !prev)}
                        data-expanded={listingsExpanded}
                      >
                        {listingsExpanded ? '收起' : '展开全部'}
                      </button>
                    )}
                  </>
                )}
              </section>
              <section className="card" id="payout">
                <div className="card-title">创作者收益申请</div>
                <form className="form-grid" onSubmit={submitPayout}>
                <div className="form-item">
                  <label htmlFor="payout-alipay-account">支付宝账号</label>
                  <input
                    id="payout-alipay-account"
                    value={payoutForm.alipayAccount}
                    onChange={(e) => setPayoutForm((prev) => ({ ...prev, alipayAccount: e.target.value }))}
                    placeholder="用于收款的支付宝账号"
                    required
                  />
                </div>
                <div className="form-item">
                  <label htmlFor="payout-real-name">
                    收款人姓名（需与支付宝实名一致）
                    <Link
                      href="/identity-info"
                      className="identity-help-link"
                      title="为了向创作者支付收益并依法办理个人所得税扣缴申报，我们需要采集收款人姓名、身份证号等身份信息，并做同名支付宝校验。信息仅用于提现审核、税务申报与风控合规，严格加密与脱敏。"
                      aria-label="为什么需要身份信息"
                    >
                      ？为什么需要我的身份信息
                    </Link>
                  </label>
                  <input
                    id="payout-real-name"
                    value={payoutForm.realName}
                    onChange={(e) =>
                      setPayoutForm((prev) => ({
                        ...prev,
                        realName: e.target.value,
                        alipayName: e.target.value,
                      }))
                    }
                    placeholder="将用于实名核验"
                    required
                  />
                </div>
                <div className="form-item">
                  <label htmlFor="payout-id-card">身份证号</label>
                  <input
                    id="payout-id-card"
                    value={payoutForm.idCardNo}
                    onChange={(e) => setPayoutForm((prev) => ({ ...prev, idCardNo: e.target.value }))}
                    placeholder="仅用于实名核验"
                    required
                  />
                </div>
                <div className="form-item full">
                  <p className="help-text">实名信息仅用于核验与打款，同名校验不通过将无法结算。</p>
                </div>
                <div className="form-item">
                  <label htmlFor="payout-contact-type">联系方式类型</label>
                  <select
                    id="payout-contact-type"
                    value={payoutForm.contactType}
                    onChange={(e) => setPayoutForm((prev) => ({ ...prev, contactType: e.target.value }))}
                  >
                    <option value="WECHAT">微信</option>
                    <option value="QQ">QQ</option>
                    <option value="PHONE">手机号</option>
                    <option value="OTHER">其他</option>
                  </select>
                </div>
                <div className="form-item">
                  <label htmlFor="payout-contact-value">联系方式</label>
                  <input
                    id="payout-contact-value"
                    value={payoutForm.contactValue}
                    onChange={(e) => setPayoutForm((prev) => ({ ...prev, contactValue: e.target.value }))}
                    placeholder="请输入联系账号，便于结算沟通"
                    required
                  />
                </div>
                <div className="form-item full">
                  <p className="help-text">最低提现金额为 10 元。</p>
                </div>
                <div className="form-item full">
                  <label htmlFor="payout-notes">备注（可选）</label>
                  <textarea
                    id="payout-notes"
                    value={payoutForm.notes}
                    onChange={(e) => setPayoutForm((prev) => ({ ...prev, notes: e.target.value }))}
                    rows={3}
                    placeholder="补充结算说明"
                  />
                </div>
                <div className="form-item">
                  <button className="button primary" type="submit" disabled={payoutLoading}>
                    {payoutLoading ? '提交中...' : '提交收益申请'}
                  </button>
                </div>
              </form>
              {payoutMessage && (
                <p className={payoutMessage.type === 'error' ? 'error-text' : 'success-text'}>{payoutMessage.message}</p>
              )}
              {payoutApp && (
                <div className="help-text" style={{ marginTop: 8 }}>
                  <div>状态：{payoutApp.status || '未提交'}</div>
                  <div>周期：{payoutApp.cycleKey || '-'}</div>
                  <div>说明：{renderPayoutStatus()}</div>
                </div>
              )}
            </section>
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
