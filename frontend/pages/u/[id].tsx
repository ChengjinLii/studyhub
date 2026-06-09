import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/router';
import AppImage from '../../components/AppImage';
import { useAppDialog } from '../../components/AppDialogProvider';
import NavBar from '../../components/NavBar';
import SafeMarkdown from '../../components/SafeMarkdown';
import ShareSheet from '../../components/ShareSheet';
import { readSession } from '../../lib/auth';
import { fetchUserProfile, reportTarget } from '../../lib/api';
import { fetchBackend, getRequestOrigin } from '../../lib/apiBase';
import { toErrorMessage } from '../../lib/errors';
import { formatDate } from '../../lib/format';
import { marketPath, materialPath, parseUserId, slugifyTitle, userPath } from '../../lib/slug';
import { copyToClipboard, isLikelyMobile, tryNativeShare } from '../../lib/share';
import { MarketListingItem, UploadItem } from '../../types/profile';
import { SessionUser } from '../../types/user';
import { PublicUserProfile } from '../../types/userProfile';

interface UserProfilePageProps {
  user: SessionUser | null;
  profile: PublicUserProfile | null;
}

const formatMarkdown = (value: string) => value.replace(/\r?\n/g, '  \n');
const EXPERIENCE_TAGS = new Set(['经验分享', '保研面经', '求职面经', '考研攻略', '留学指南', '考研心得', '留学心得']);

const normalizeUploadTags = (tags: UploadItem['tags']): string[] | null => {
  if (!Array.isArray(tags)) return null;
  return tags.filter((tag): tag is string => typeof tag === 'string' && tag.length > 0);
};

const isExperienceUpload = (item: UploadItem) => {
  const extended = item as UploadItem & {
    isExperience?: boolean;
    type?: string | null;
    contentType?: string | null;
  };
  const tags = normalizeUploadTags(item.tags) ?? [];
  if (tags.some((tag) => EXPERIENCE_TAGS.has(tag))) return true;
  if (extended.isExperience === true) return true;
  if (typeof extended.type === 'string' && /experience/i.test(extended.type)) return true;
  if (typeof extended.contentType === 'string' && /experience/i.test(extended.contentType)) return true;
  return false;
};

export default function UserProfilePage({ user, profile }: UserProfilePageProps) {
  const dialog = useAppDialog();
  const router = useRouter();
  const [activeSection, setActiveSection] = useState<
    'profile-overview' | 'profile-detail' | 'profile-materials' | 'profile-experience' | 'profile-market'
  >('profile-overview');
  const [uploads, setUploads] = useState<UploadItem[]>(profile?.recentUploads ?? []);
  const [listings, setListings] = useState<MarketListingItem[]>(profile?.recentMarketListings ?? []);
  const [materialsExpanded, setMaterialsExpanded] = useState(false);
  const [experienceExpanded, setExperienceExpanded] = useState(false);
  const [listingsExpanded, setListingsExpanded] = useState(false);
  const [uploadsLoading, setUploadsLoading] = useState(false);
  const [listingsLoading, setListingsLoading] = useState(false);
  const [isFollowing, setIsFollowing] = useState(profile?.isFollowing ?? false);
  const [followersCount, setFollowersCount] = useState(profile?.followersCount ?? 0);
  const [followingCount, setFollowingCount] = useState(profile?.followingCount ?? 0);
  const [followLoading, setFollowLoading] = useState(false);
  const [followNotice, setFollowNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [reportNotice, setReportNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [shareNotice, setShareNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [shareSheetOpen, setShareSheetOpen] = useState(false);
  const [shareSheetText, setShareSheetText] = useState('');
  const [shareSheetUrl, setShareSheetUrl] = useState('');

  useEffect(() => {
    setUploads(profile?.recentUploads ?? []);
    setListings(profile?.recentMarketListings ?? []);
    setMaterialsExpanded(false);
    setExperienceExpanded(false);
    setListingsExpanded(false);
    setIsFollowing(profile?.isFollowing ?? false);
    setFollowersCount(profile?.followersCount ?? 0);
    setFollowingCount(profile?.followingCount ?? 0);
    setFollowNotice(null);
    setReportNotice(null);
    setShareNotice(null);
  }, [profile]);

  const displayName = useMemo(() => {
    if (!profile) return 'StudyHub 用户';
    return profile.nickname || profile.username || 'StudyHub 用户';
  }, [profile]);
  const legendaryActive = useMemo(() => {
    if (!profile?.legendaryContributorUntil) return false;
    const ts = Date.parse(profile.legendaryContributorUntil);
    return Number.isFinite(ts) && ts > Date.now();
  }, [profile?.legendaryContributorUntil]);
  const avatarText = useMemo(() => displayName.slice(0, 1).toUpperCase(), [displayName]);
  const schoolParts = useMemo(
    () => (profile ? [profile.school, profile.college, profile.major].filter(Boolean) : []),
    [profile]
  );
  const schoolText = schoolParts.length > 0 ? schoolParts.join(' · ') : '未填写学校信息';
  const hasSchool = schoolParts.length > 0;
  const gradeStages = useMemo(() => (profile?.gradeStages ?? []).filter(Boolean), [profile]);
  const totalUploads = profile?.uploadCount ?? uploads.length;
  const totalListings = profile?.marketCount ?? listings.length;
  const purchaseCount = profile?.purchaseCount ?? 0;
  const saleCount = profile?.saleCount ?? 0;
  const signatureText = profile?.signature?.trim() ?? '';
  const signatureMarkdown = signatureText ? formatMarkdown(signatureText) : '';
  const sortedUploads = useMemo(() => {
    return [...uploads].sort((a, b) => {
      const countDiff = (b.downloadCount ?? 0) - (a.downloadCount ?? 0);
      if (countDiff !== 0) return countDiff;
      return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
    });
  }, [uploads]);
  const sortedListings = useMemo(() => {
    return [...listings].sort((a, b) => {
      const countDiff = (b.wantCount ?? 0) - (a.wantCount ?? 0);
      if (countDiff !== 0) return countDiff;
      return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
    });
  }, [listings]);
  const sortedExperienceUploads = useMemo(
    () => sortedUploads.filter((item) => isExperienceUpload(item)),
    [sortedUploads]
  );
  const sortedMaterialUploads = useMemo(
    () => sortedUploads.filter((item) => !isExperienceUpload(item)),
    [sortedUploads]
  );
  const visibleUploads = materialsExpanded ? sortedMaterialUploads : sortedMaterialUploads.slice(0, 5);
  const visibleExperienceUploads = experienceExpanded ? sortedExperienceUploads : sortedExperienceUploads.slice(0, 5);
  const visibleListings = listingsExpanded ? sortedListings : sortedListings.slice(0, 5);
  const canExpandUploads = sortedMaterialUploads.length > 5;
  const canExpandExperience = sortedExperienceUploads.length > 5;
  const canExpandListings = totalListings > 5;
  const isSelf = Boolean(user && profile && user.id === profile.id);

  const handleToggleFollow = async () => {
    if (!profile || isSelf) return;
    setFollowNotice(null);
    setFollowLoading(true);
    try {
      const resp = await fetchBackend(`/users/${profile.id}/follow`, {
        method: isFollowing ? 'DELETE' : 'PUT',
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '操作失败');
      }
      const next = !isFollowing;
      setIsFollowing(next);
      setFollowersCount((prev) => Math.max(0, prev + (next ? 1 : -1)));
    } catch (error: unknown) {
      setFollowNotice({ type: 'error', text: toErrorMessage(error, '操作失败') });
    } finally {
      setFollowLoading(false);
    }
  };

  useEffect(() => {
    if (!profile?.id) return;
    let cancelled = false;
    const hydrateUploads = async () => {
      setUploadsLoading(true);
      try {
        const resp = await fetchBackend(`/users/${profile.id}/uploads`);
        const json = await resp.json();
        if (cancelled) return;
        if (resp.ok && json?.ok && Array.isArray(json.data)) {
          setUploads(json.data as UploadItem[]);
        }
      } finally {
        if (!cancelled) setUploadsLoading(false);
      }
    };
    hydrateUploads();
    return () => {
      cancelled = true;
    };
  }, [profile?.id]);

  const handleToggleMaterials = () => setMaterialsExpanded((prev) => !prev);
  const handleToggleExperience = () => setExperienceExpanded((prev) => !prev);

  const handleToggleListings = async () => {
    if (!listingsExpanded && profile?.id && listings.length < totalListings) {
      setListingsLoading(true);
      try {
        const resp = await fetchBackend(`/users/${profile.id}/market`);
        const json = await resp.json();
        if (resp.ok && json.ok && Array.isArray(json.data)) {
          setListings(json.data as MarketListingItem[]);
        }
      } finally {
        setListingsLoading(false);
      }
    }
    setListingsExpanded((prev) => !prev);
  };

  const handleReportUser = async () => {
    if (!profile) return;
    if (!user) {
      router.push({ pathname: '/login', query: { next: router.asPath } });
      return;
    }
    if (isSelf) {
      setReportNotice({ type: 'error', text: '不能举报自己。' });
      return;
    }
    const reason = (
      await dialog.prompt({
        title: '举报用户',
        message: '请输入举报理由。',
        placeholder: '示例：不当言论、冒充等',
        multiline: true,
        confirmText: '提交举报',
      })
    )?.trim();
    if (!reason) return;
    setReportNotice(null);
    try {
      await reportTarget('USER', profile.id, reason);
      setReportNotice({ type: 'success', text: '已收到举报，我们会尽快处理。' });
    } catch (err: unknown) {
      setReportNotice({ type: 'error', text: toErrorMessage(err, '举报失败，请稍后再试。') });
    }
  };

  const handleShareProfile = async () => {
    if (!profile) return;
    setShareNotice(null);
    try {
      const sharePath = userPath(profile.id, displayName);
      const shareUrl =
        typeof window === 'undefined' ? sharePath : `${window.location.origin}${sharePath}`;
      const shareTitle = `${displayName} 的主页`;
      const shareText = `${shareTitle}\n${shareUrl}`;
      if (isLikelyMobile()) {
        const shared = await tryNativeShare({ title: shareTitle, text: shareText, url: shareUrl });
        if (shared) {
          setShareNotice({ type: 'success', text: '已唤起系统分享。' });
          return;
        }
        setShareSheetText(shareText);
        setShareSheetUrl(shareUrl);
        setShareSheetOpen(true);
        return;
      }
      const copied = await copyToClipboard(shareUrl);
      if (copied) {
        setShareNotice({ type: 'success', text: '主页链接已复制，可以直接分享给好友。' });
        return;
      }
      setShareNotice({ type: 'error', text: '复制失败，请手动复制链接。' });
    } catch (err: unknown) {
      setShareNotice({ type: 'error', text: toErrorMessage(err, '复制失败，请稍后重试。') });
    }
  };

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const sections = ['profile-overview', 'profile-detail', 'profile-materials', 'profile-experience', 'profile-market']
      .map((id) => document.getElementById(id))
      .filter((node): node is HTMLElement => Boolean(node));
    if (!sections.length) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible?.target?.id) {
          setActiveSection(
            visible.target.id as 'profile-overview' | 'profile-detail' | 'profile-materials' | 'profile-experience' | 'profile-market'
          );
        }
      },
      { rootMargin: '-18% 0px -58% 0px', threshold: [0.2, 0.45, 0.7] }
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  const profileNavItems = [
    { id: 'profile-overview', label: '个人概览' },
    { id: 'profile-detail', label: '个人信息' },
    { id: 'profile-materials', label: '资料' },
    { id: 'profile-experience', label: '经验分享' },
    { id: 'profile-market', label: '好物' },
  ] as const;

  return (
    <>
      <NavBar user={user} />
      <main className="container user-profile-page">
        <div className="profile-layout">
          <aside className="me-sidebar profile-sidebar">
            <div className="me-sidebar__brand">个人主页</div>
            <div className="me-sidebar__group">
              <div className="me-sidebar__label">页面导航</div>
              <nav className="me-sidebar__items" aria-label="个人主页导航">
                {profileNavItems.map((item) => (
                  <a
                    key={item.id}
                    href={`#${item.id}`}
                    className={`me-sidebar__item${activeSection === item.id ? ' active' : ''}`}
                    onClick={(event) => {
                      event.preventDefault();
                      setActiveSection(item.id);
                      document.getElementById(item.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }}
                  >
                    <span className="me-sidebar__indicator" />
                    <span className="me-sidebar__text">{item.label}</span>
                  </a>
                ))}
              </nav>
            </div>
          </aside>

          <div className="profile-main">
            {profile && (
          <section className="card profile-hero" id="profile-overview">
            <div className="profile-hero__content">
              <div className="profile-hero__avatar" aria-hidden="true">
                {avatarText}
              </div>
              <div className="profile-hero__body">
                <div className="profile-hero__top">
                  <div>
                    <div className="profile-hero__name-line">
                      <h1 className="profile-hero__name">{displayName}</h1>
                      {legendaryActive && <span className="legendary-badge">传奇贡献者</span>}
                    </div>
                    <div className="profile-hero__handle">@{profile.username}</div>
                  </div>
                  {profile && (
                    <div className="profile-hero__actions">
                      {!isSelf && (
                        <button
                          className={`button ${isFollowing ? 'ghost muted' : 'primary'} small`}
                          type="button"
                          onClick={handleToggleFollow}
                          disabled={followLoading}
                        >
                          {followLoading ? '处理中...' : isFollowing ? '取关' : '关注'}
                        </button>
                      )}
                      {!isSelf && (
                        <button className="button ghost small" type="button" onClick={handleReportUser}>
                          举报
                        </button>
                      )}
                      <button className="button ghost small profile-hero__share-btn" type="button" onClick={handleShareProfile}>
                        <span className="button-icon" aria-hidden="true">
                          <svg viewBox="0 0 24 24" aria-hidden="true">
                            <path
                              d="M7 12.5L16.6 7.8M7 11.5L16.6 16.2"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.6"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                            <circle
                              cx="6"
                              cy="12"
                              r="2.5"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.6"
                            />
                            <circle
                              cx="18"
                              cy="6"
                              r="2.5"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.6"
                            />
                            <circle
                              cx="18"
                              cy="18"
                              r="2.5"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="1.6"
                            />
                          </svg>
                        </span>
                        分享
                      </button>
                    </div>
                  )}
                </div>
                <div className="profile-hero__stats">
                  <div className="profile-hero__stat">
                    <span className="profile-hero__stat-value">{totalUploads}</span>
                    <span className="profile-hero__stat-label">资料</span>
                  </div>
                  <div className="profile-hero__stat">
                    <span className="profile-hero__stat-value">{totalListings}</span>
                    <span className="profile-hero__stat-label">好物</span>
                  </div>
                  <div className="profile-hero__stat">
                    <span className="profile-hero__stat-value">{sortedExperienceUploads.length}</span>
                    <span className="profile-hero__stat-label">经验分享</span>
                  </div>
                  <div className="profile-hero__stat">
                    <span className="profile-hero__stat-value">{saleCount}</span>
                    <span className="profile-hero__stat-label">售出</span>
                  </div>
                  <div className="profile-hero__stat">
                    <span className="profile-hero__stat-value">{followersCount}</span>
                    <span className="profile-hero__stat-label">粉丝</span>
                  </div>
                  <div className="profile-hero__stat">
                    <span className="profile-hero__stat-value">{followingCount}</span>
                    <span className="profile-hero__stat-label">关注</span>
                  </div>
                </div>
                {followNotice?.type === 'error' && <p className="error-text">{followNotice.text}</p>}
                {reportNotice && (
                  <p className={reportNotice.type === 'error' ? 'error-text' : 'success-text'}>
                    {reportNotice.text}
                  </p>
                )}
                {shareNotice && (
                  <p className={shareNotice.type === 'error' ? 'error-text' : 'success-text'}>
                    {shareNotice.text}
                  </p>
                )}
              </div>
            </div>
          </section>
        )}
        {profile && (
          <section className="card profile-info" id="profile-detail">
            <div className="profile-info__grid">
              <div className="profile-info__item profile-info__item--wide profile-info__item--signature">
                <span className="profile-info__label">个性签名</span>
                {signatureText ? (
                  <div className="profile-info__value profile-info__markdown profile-markdown">
                    <SafeMarkdown>{signatureMarkdown}</SafeMarkdown>
                  </div>
                ) : (
                  <div className="profile-info__value muted">这个人还没有写签名。</div>
                )}
              </div>
              <div className="profile-info__item">
                <span className="profile-info__label">学校信息</span>
                <span className={`profile-info__value ${hasSchool ? '' : 'muted'}`}>{schoolText}</span>
              </div>
              <div className="profile-info__item">
                <span className="profile-info__label">年级/阶段</span>
                {gradeStages.length > 0 ? (
                  <div className="profile-info__tags">
                    {gradeStages.map((stage) => (
                      <span key={stage} className="profile-info__tag">
                        {stage}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="profile-info__value muted">未填写</span>
                )}
              </div>
              <div className="profile-info__item">
                <span className="profile-info__label">邮箱</span>
                <span className={`profile-info__value ${profile.emailVisible ? '' : 'muted'}`}>
                  {profile.emailVisible ? profile.email || '-' : '已隐藏'}
                </span>
              </div>
              {profile.payoutQrUrl && (
                <div className="profile-info__item profile-info__item--wide profile-info__item--payout">
                  <span className="profile-info__label">个人收款码</span>
                  <a href={profile.payoutQrUrl} target="_blank" rel="noreferrer" title="点击查看大图">
                    <AppImage
                      className="profile-info__payout-preview"
                      src={profile.payoutQrUrl}
                      alt="个人收款码"
                      loading="lazy"
                    />
                  </a>
                  <span className="help-text">仅本人和超级管理员可见</span>
                </div>
              )}
            </div>
          </section>
        )}
        <section className="card profile-panel" id="profile-materials">
          <h2 className="card-title">资料</h2>
          <p className="profile-panel__hint">按下载热度排序，点击标题查看详情。</p>
          {visibleUploads.length === 0 ? (
            <p className="help-text">暂无发布资料。</p>
          ) : (
            <ul className="materials-list profile-content-list">
              {visibleUploads.map((item) => (
                <li key={item.materialId} className="material-row profile-content-row">
                  <Link href={materialPath(item.materialId, item.title)}>{item.title}</Link>
                  <span className="help-text">
                    下载 {item.downloadCount ?? 0} · {formatDate(item.createdAt)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {canExpandUploads && (
            <button type="button" className="profile-card__expand" onClick={handleToggleMaterials} disabled={uploadsLoading}>
              {materialsExpanded ? '收起' : uploadsLoading ? '加载中...' : '展开全部'}
            </button>
          )}
        </section>

        <section className="card profile-panel" id="profile-experience">
          <h2 className="card-title">经验分享</h2>
          <p className="profile-panel__hint">按下载热度排序，点击标题查看详情。</p>
          {visibleExperienceUploads.length === 0 ? (
            <p className="help-text">暂无经验分享内容。</p>
          ) : (
            <ul className="materials-list profile-content-list">
              {visibleExperienceUploads.map((item) => (
                <li key={`exp-${item.materialId}`} className="material-row profile-content-row">
                  <Link href={materialPath(item.materialId, item.title)}>{item.title}</Link>
                  <span className="help-text">
                    下载 {item.downloadCount ?? 0} · {formatDate(item.createdAt)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {canExpandExperience && (
            <button type="button" className="profile-card__expand" onClick={handleToggleExperience} disabled={uploadsLoading}>
              {experienceExpanded ? '收起' : uploadsLoading ? '加载中...' : '展开全部'}
            </button>
          )}
        </section>

        <section className="card profile-panel" id="profile-market">
          <h2 className="card-title">好物</h2>
          <p className="profile-panel__hint">按想要人数排序，点击标题查看详情。</p>
          {visibleListings.length === 0 ? (
            <p className="help-text">暂无发布好物。</p>
          ) : (
            <ul className="materials-list profile-content-list">
              {visibleListings.map((item) => (
                <li key={item.itemId} className="material-row profile-content-row">
                  <Link href={marketPath(item.itemId, item.title)}>{item.title}</Link>
                  <span className="help-text">
                    想要 {item.wantCount ?? 0} · {formatDate(item.createdAt)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {canExpandListings && (
            <button type="button" className="profile-card__expand" onClick={handleToggleListings} disabled={listingsLoading}>
              {listingsExpanded ? '收起' : listingsLoading ? '加载中...' : '展开全部'}
            </button>
          )}
        </section>
          </div>
        </div>
      </main>
      <ShareSheet
        open={shareSheetOpen}
        title="分享个人主页"
        text={shareSheetText}
        linkUrl={shareSheetUrl}
        onClose={() => setShareSheetOpen(false)}
      />
    </>
  );
}

export const getServerSideProps: GetServerSideProps<UserProfilePageProps> = async (ctx) => {
  const session = readSession(ctx.req);
  const rawId = Array.isArray(ctx.params?.id) ? ctx.params?.id[0] : ctx.params?.id;
  const origin = getRequestOrigin(ctx.req);
  const resolvedUrl = ctx.resolvedUrl || (rawId ? `/u/${rawId}` : '/u');
  if (!session.user) {
    return {
      redirect: {
        destination: `/login?next=${encodeURIComponent(resolvedUrl)}`,
        permanent: false,
      },
    };
  }
  if (!session.token || !rawId) {
    return { props: { user: session.user, profile: null } };
  }
  const userId = parseUserId(rawId);
  if (!userId) {
    return { notFound: true };
  }
  try {
    const profile = await fetchUserProfile(userId, session.token, origin);
    const slug = slugifyTitle(profile.nickname || profile.username || '');
    const canonicalId = slug ? `${profile.id}-${slug}` : String(profile.id);
    if (rawId !== canonicalId) {
      const queryString = resolvedUrl.includes('?') ? resolvedUrl.split('?')[1] : '';
      const encodedCanonicalId = encodeURIComponent(canonicalId);
      const destination = queryString ? `/u/${encodedCanonicalId}?${queryString}` : `/u/${encodedCanonicalId}`;
      return {
        redirect: {
          destination,
          permanent: true,
        },
      };
    }
    return { props: { user: session.user, profile } };
  } catch (error) {
    return { props: { user: session.user, profile: null } };
  }
};
