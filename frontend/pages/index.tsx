import type React from 'react';
import { GetServerSideProps } from 'next';
import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import NavBar from '../components/NavBar';
import AppImage from '../components/AppImage';
import MaterialIconSprite from '../components/MaterialIconSprite';
import PaginationBar from '../components/PaginationBar';
import { MaterialListItem, PaginationMeta } from '../types/material';
import { SessionUser, RoleMask } from '../types/user';
import { ProfileSummary } from '../types/profile';
import { readSession, hasRole } from '../lib/auth';
import {
  fetchMaterials,
  MaterialListStats,
  MaterialListResponse,
  fetchProfile,
  fetchContributorRanks,
  fetchRecommendations,
  fetchMaterialRequests,
  fetchRequestLeaderboard,
} from '../lib/api';
import { fetchBackend } from '../lib/apiBase';
import { getRequestOrigin } from '../lib/apiBase';
import { ensureApiSuccess, unwrapApiResponse } from '../lib/apiEnvelope';
import { toErrorMessage } from '../lib/errors';
import { formatDate, formatNumber } from '../lib/format';
import { materialPath } from '../lib/slug';
import { copyToClipboard, isLikelyMobile, tryNativeShare } from '../lib/share';
import {
  SUPPORTED_SCHOOL,
  SUPPORTED_COLLEGES,
  SUPPORTED_MAJORS,
  COURSE_CATEGORY_OPTIONS,
  COURSE_CATEGORY_VALUES,
  GRADE_STAGE_OPTIONS,
} from '../constants/metadata';
import { getTierLabel } from '../constants/request';
import { ContributorRank, LeaderboardPeriod } from '../types/contributor';
import { MaterialRequestItem } from '../types/request';

const MATERIALS_PAGE_SIZE = 18;
const Snowfall = dynamic(() => import('react-snowfall'), { ssr: false });
const MaterialCard = dynamic(() => import('../components/MaterialCard'));
const HomeFilterCard = dynamic(() => import('../components/home/HomeFilterCard'));
const HomeLeaderboard = dynamic(() => import('../components/home/HomeLeaderboard'));
const HomeRequestPanels = dynamic(() => import('../components/home/HomeRequestPanels'));
const ShareSheet = dynamic(() => import('../components/ShareSheet'), { ssr: false });

const ROLE_LABELS = [
  { mask: RoleMask.DEVELOPER, label: '开发者' },
  { mask: RoleMask.ADMIN, label: '管理员' },
  { mask: RoleMask.REVIEWER, label: '审核员' },
  { mask: RoleMask.CONTRIBUTOR, label: '投稿者' },
  { mask: RoleMask.USER, label: '普通用户' },
];

const DEFAULT_TAG_OPTIONS = [
  '日常学习笔记',
  '期末速成',
  '期末真题',
  '期末真题标答',
  '期末答案（自制解析）',
  '期中速成',
  '期中真题',
  '期中真题标答',
  '期中答案（自制解析）',
  '一页纸',
  '开卷资料',
];

interface FilterState {
  keyword: string;
  school: string;
  college: string;
  major: string;
  tag: string;
  gradeValue: string;
  courseCategory: string;
  price: string;
  sort: string;
  page: string;
  size: string;
}

interface HomeProps {
  materials: MaterialListItem[];
  meta: PaginationMeta;
  filters: FilterState;
  user: SessionUser | null;
  officialQQ?: string;
  stats: MaterialListStats | null;
  tagOptions: string[];
  profileSummary: ProfileSummary | null;
  recommendations: MaterialListItem[];
  requests: MaterialRequestItem[];
  requestLeaderboard: MaterialRequestItem[];
  contributors: ContributorRank[];
}

export default function Home({
  materials: initialMaterials,
  meta,
  filters: initialFilters,
  user,
  officialQQ,
  stats,
  tagOptions,
  profileSummary,
  recommendations,
  requests,
  requestLeaderboard,
  contributors: initialContributors,
}: HomeProps) {
  const router = useRouter();
  const isAdmin = Boolean(user && hasRole(user.roleMask, RoleMask.ADMIN));
  const [materialList, setMaterialList] = useState(initialMaterials);
  const [pageMeta, setPageMeta] = useState(meta);
  const [statsState, setStatsState] = useState(stats);
  const [tagOptionsState, setTagOptionsState] = useState(tagOptions);
  const [loadingPage, setLoadingPage] = useState(false);
  const [paginationError, setPaginationError] = useState('');
  const [paginationNotice, setPaginationNotice] = useState('');
  const filterRef = useRef<HTMLDivElement>(null);
  const materialsRef = useRef<HTMLDivElement>(null);
  const normalizeFilters = useCallback(
    (input: FilterState): FilterState => ({
      keyword: input.keyword || '',
      school: input.school || '',
      college: input.college || '',
      major: input.major || '',
      tag: input.tag || '',
      gradeValue: input.gradeValue || '',
      courseCategory: input.courseCategory || '',
      price: input.price || '',
      sort: input.sort || 'latest',
      page: input.page || '1',
      size: input.size || String(MATERIALS_PAGE_SIZE),
    }),
    []
  );
  const [filtersState, setFiltersState] = useState<FilterState>(() => normalizeFilters(initialFilters));
  useEffect(() => {
    setFiltersState(normalizeFilters(initialFilters));
  }, [initialFilters, normalizeFilters]);
  const buildQuery = useCallback((input: FilterState) => {
    const query: Record<string, string> = {};
    Object.entries(input).forEach(([key, value]) => {
      if (!value) return;
      query[key] = value;
    });
    return query;
  }, []);
  const buildQueryString = useCallback((params: Record<string, string | number>) => {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null || value === '') return;
      search.set(key, String(value));
    });
    const qs = search.toString();
    return qs ? `?${qs}` : '';
  }, []);
  const applyFilters = useCallback(
    async (nextFilters: FilterState, options?: { scrollTarget?: 'filters' | 'materials' }) => {
      const normalized = normalizeFilters(nextFilters);
      setLoadingPage(true);
      setPaginationError('');
      setPaginationNotice('');
      setBatchError('');
      setBatchInfo('');
      setFiltersState(normalized);
      const query = buildQuery(normalized);
      try {
        const resp = await fetchBackend(`/materials${buildQueryString({ ...query, size: MATERIALS_PAGE_SIZE })}`);
        const data = await unwrapApiResponse<MaterialListResponse>(resp, '筛选加载失败');
        setMaterialList(data.items);
        setPageMeta(data.meta);
        if (data.stats) setStatsState(data.stats);
        if (data.availableTags) setTagOptionsState(data.availableTags);
        await router.replace({ pathname: '/', query }, undefined, { shallow: true, scroll: false });
        requestAnimationFrame(() => {
          if (options?.scrollTarget === 'filters') {
            filterRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            return;
          }
          if (options?.scrollTarget === 'materials') {
            materialsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        });
      } catch (error: unknown) {
        setPaginationError(toErrorMessage(error, '筛选加载失败'));
      } finally {
        setLoadingPage(false);
      }
    },
    [buildQuery, buildQueryString, normalizeFilters, router]
  );
  const updateFilter = useCallback((key: keyof FilterState, value: string) => {
    setFiltersState((prev) => ({ ...prev, [key]: value }));
  }, []);
  const applyCourseCategory = (value: string | null) => {
    const nextFilters = {
      ...filtersState,
      courseCategory: value || '',
      page: '1',
    };
    applyFilters(nextFilters, { scrollTarget: 'filters' });
  };
  const [bannerVisible, setBannerVisible] = useState(false);
  const freeCount = useMemo(() => materialList.filter((item) => item.free).length, [materialList]);
  const statSource = statsState || stats || null;
  const statValues = {
    total: statSource?.totalMaterials ?? pageMeta.total ?? 0,
    free: statSource?.freeMaterials ?? freeCount,
    downloads: statSource?.totalDownloads ?? 0,
    users: statSource?.userCount ?? 0,
  };
  const recommendedItems = useMemo(() => recommendations ?? [], [recommendations]);
  const recommendationHint = '';
  const recommendationEmpty = user
    ? '暂无推荐资料，先在“我的”里完善学校/学院/专业。'
    : (
      <>
        暂无推荐资料，<a className="login-link" href={`/login?next=${encodeURIComponent(router.asPath)}`}>登录</a>后可获得对口推荐。
      </>
    );
  const availableTagOptions = useMemo(() => {
    const unique = new Set<string>();
    DEFAULT_TAG_OPTIONS.forEach((tag) => unique.add(tag));
    (tagOptionsState || tagOptions).forEach((tag) => {
      if (tag) {
        unique.add(tag);
      }
    });
    if (filtersState.tag && !unique.has(filtersState.tag)) {
      unique.add(filtersState.tag);
    }
    return Array.from(unique);
  }, [tagOptions, tagOptionsState, filtersState.tag]);
  const gradeStageOptions = GRADE_STAGE_OPTIONS;
  const hasAdvancedFilters = useMemo(() => {
    const priceActive = filtersState.price && filtersState.price !== 'all';
    const sortActive = filtersState.sort && filtersState.sort !== 'latest';
    return Boolean(
      filtersState.school ||
        filtersState.college ||
        filtersState.tag ||
        filtersState.courseCategory ||
        priceActive ||
        sortActive
    );
  }, [
    filtersState.school,
    filtersState.college,
    filtersState.tag,
    filtersState.courseCategory,
    filtersState.price,
    filtersState.sort,
  ]);
  const [isMobile, setIsMobile] = useState(false);
  const [reduceMotion, setReduceMotion] = useState(false);
  const [seasonalEffectsReady, setSeasonalEffectsReady] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [batchError, setBatchError] = useState('');
  const [batchInfo, setBatchInfo] = useState('');
  const [shareSheetOpen, setShareSheetOpen] = useState(false);
  const [shareSheetText, setShareSheetText] = useState('');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [contributors, setContributors] = useState<ContributorRank[]>(initialContributors);
  const [leaderboardPeriod, setLeaderboardPeriod] = useState<LeaderboardPeriod>('all');
  const didRunInitialLeaderboardEffect = useRef(false);
  const [leaderboardLoading, setLeaderboardLoading] = useState(false);
  const [leaderboardError, setLeaderboardError] = useState('');
  const snowCountFar = isMobile ? 16 : 26;
  const snowCountNear = isMobile ? 8 : 14;
  const snowfallCanvasStyle: React.CSSProperties = {
    position: 'absolute',
    inset: 0,
    width: '100%',
    height: '100%',
  };
  const [meteorSeed, setMeteorSeed] = useState(0);
  const [meteorStyles, setMeteorStyles] = useState<React.CSSProperties[]>([]);
  const randomizeMeteors = useCallback(() => {
    const count = Math.random() < 0.5 ? 2 : 3;
    const styles = Array.from({ length: count }, (_, index) => {
      const top = Math.random() * 28 - 8;
      const left = Math.random() * 45 + 5;
      const delay = index * 0.7 + Math.random() * 0.35;
      return {
        top: `${top}%`,
        left: `${left}%`,
        animationDelay: `${delay}s`,
      };
    });
    setMeteorStyles(styles);
    setMeteorSeed((prev) => prev + 1);
  }, []);
  const [requestItems] = useState<MaterialRequestItem[]>(requests || []);
  const [leaderboardItems] = useState<MaterialRequestItem[]>(requestLeaderboard || []);
  const requestLoading = false;
  const requestError = '';
  const requestNotice: { type: 'success' | 'error'; text: string } | null = null;
  const [leaderboardFollowed, setLeaderboardFollowed] = useState<Record<number, boolean>>({});
  const [leaderboardFollowLoading, setLeaderboardFollowLoading] = useState<Record<number, boolean>>({});
  const [leaderboardFollowNotice, setLeaderboardFollowNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [supportModalOpen, setSupportModalOpen] = useState(false);
  const showSeasonalEffects = seasonalEffectsReady && (!reduceMotion || isMobile);
  useEffect(() => {
    setMaterialList(initialMaterials);
    setPageMeta(meta);
    setStatsState(stats);
    setTagOptionsState(tagOptions);
  }, [initialMaterials, meta, stats, tagOptions]);
  useEffect(() => {
    if (!showSeasonalEffects) {
      setMeteorStyles([]);
      return;
    }
    randomizeMeteors();
    const interval = window.setInterval(randomizeMeteors, 10000);
    return () => window.clearInterval(interval);
  }, [showSeasonalEffects, randomizeMeteors]);
  const pageSize = pageMeta.size || MATERIALS_PAGE_SIZE;
  const currentPage = pageMeta.page || 1;
  const totalPages = useMemo(
    () => Math.max(1, Math.ceil((pageMeta.total || 0) / pageSize)),
    [pageMeta.total, pageSize]
  );
  const totalItems = pageMeta.total ?? 0;
  const userRoleBadges = useMemo(() => {
    if (!user) return [];
    return ROLE_LABELS.filter((role) => hasRole(user.roleMask, role.mask)).map((role) => role.label);
  }, [user]);
  const userMetrics = useMemo(() => {
    const uploads = profileSummary?.uploads ?? [];
    const listings = profileSummary?.marketListings ?? [];
    return {
      downloadTotal: uploads.reduce((sum, item) => sum + (item.downloadCount ?? item.salesCount ?? 0), 0),
      commentTotal: uploads.reduce((sum, item) => sum + (item.commentCount ?? 0), 0),
      likeTotal: uploads.reduce((sum, item) => sum + (item.likeCount ?? 0), 0),
      marketWantTotal: listings.reduce((sum, item) => sum + (item.wantCount ?? 0), 0),
    };
  }, [profileSummary]);
  const topContributors = useMemo(() => contributors.slice(0, 50), [contributors]);
  const leaderboardLabels: Record<LeaderboardPeriod, string> = {
    all: '总榜',
    week: '周榜',
    month: '月榜',
  };
  const leaderboardPeriods: LeaderboardPeriod[] = ['all', 'week', 'month'];
  const leaderboardRangeHint =
    leaderboardPeriod === 'week'
      ? '统计本周（周一 00:00 - 周日 24:00）'
      : leaderboardPeriod === 'month'
      ? '统计本月（月初 00:00 - 月末 24:00）'
      : '';
  const leaderboardEmptyHint =
    leaderboardPeriod === 'week'
      ? '本周暂无贡献记录，欢迎率先投稿。'
      : leaderboardPeriod === 'month'
      ? '本月暂无贡献记录，欢迎率先投稿。'
      : '暂无贡献记录，欢迎率先投稿。';
  useEffect(() => {
    if (!officialQQ) return;
    const dismissed = window.localStorage.getItem('qq-banner-dismissed');
    setBannerVisible(!dismissed);
  }, [officialQQ]);

  useEffect(() => {
    const checkViewport = () => {
      const mobile = typeof window !== 'undefined' && window.innerWidth <= 640;
      setIsMobile(mobile);
    };
    checkViewport();
    window.addEventListener('resize', checkViewport);
    return () => window.removeEventListener('resize', checkViewport);
  }, []);

  useEffect(() => {
    if (typeof document === 'undefined') return undefined;
    document.body.classList.add('theme-xmas');
    return () => document.body.classList.remove('theme-xmas');
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    const enableEffects = () => {
      timeoutId = setTimeout(() => setSeasonalEffectsReady(true), 0);
    };
    if (document.readyState === 'complete') {
      enableEffects();
    } else {
      window.addEventListener('load', enableEffects, { once: true });
    }
    return () => {
      window.removeEventListener('load', enableEffects);
      if (timeoutId !== null) clearTimeout(timeoutId);
    };
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const updateMotion = () => setReduceMotion(media.matches);
    updateMotion();
    if (media.addEventListener) {
      media.addEventListener('change', updateMotion);
      return () => media.removeEventListener('change', updateMotion);
    }
    media.addListener(updateMotion);
    return () => media.removeListener(updateMotion);
  }, []);


  useEffect(() => {
    setShowAdvanced(false);
  }, []);

  useEffect(() => {
    setSelectedIds([]);
    setBatchError('');
    setBatchInfo('');
  }, [materialList]);

  useEffect(() => {
    if (!user) {
      setLeaderboardFollowed({});
      return;
    }
    let cancelled = false;
    const loadFollowing = async () => {
      try {
        const resp = await fetchBackend(`/users/${user.id}/following`);
        const data = await unwrapApiResponse<Array<{ id?: number }>>(resp, '关注列表加载失败');
        if (cancelled) return;
        const next: Record<number, boolean> = {};
        data.forEach((item) => {
          if (typeof item?.id === 'number') {
            next[item.id] = true;
          }
        });
        setLeaderboardFollowed(next);
      } catch {
        if (!cancelled) {
          setLeaderboardFollowed({});
        }
      }
    };
    loadFollowing();
    return () => {
      cancelled = true;
    };
  }, [user]);

  const dismissBanner = () => {
    setBannerVisible(false);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('qq-banner-dismissed', '1');
    }
  };

  useEffect(() => {
    if (!didRunInitialLeaderboardEffect.current) {
      didRunInitialLeaderboardEffect.current = true;
      return;
    }
    let cancelled = false;
    setLeaderboardLoading(true);
    setLeaderboardError('');
    const origin = typeof window !== 'undefined' ? window.location.origin : undefined;
    fetchContributorRanks({ limit: 50, period: leaderboardPeriod, origin })
      .then((data) => {
        if (!cancelled) setContributors(data);
      })
      .catch(() => {
        if (!cancelled) setLeaderboardError('贡献榜单加载失败，请稍后再试。');
      })
      .finally(() => {
        if (!cancelled) setLeaderboardLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [leaderboardPeriod]);

  const selectedMaterials = useMemo(
    () => materialList.filter((item) => selectedIds.includes(item.id)),
    [materialList, selectedIds]
  );
  const selectedCount = selectedMaterials.length;

  const ensureLoggedIn = useCallback(() => {
    if (user) return true;
    void router.push({ pathname: '/login', query: { next: router.asPath } });
    return false;
  }, [router, user]);

  const handleFollowContributor = useCallback(
    async (userId: number) => {
      if (!ensureLoggedIn()) return;
      if (!userId) return;
      if (leaderboardFollowed[userId]) return;
      if (user && user.id === userId) {
        setLeaderboardFollowNotice({ type: 'error', text: '不能关注自己' });
        return;
      }
      setLeaderboardFollowNotice(null);
      setLeaderboardFollowLoading((prev) => ({ ...prev, [userId]: true }));
      try {
        const resp = await fetchBackend(`/users/${userId}/follow`, { method: 'PUT' });
        await ensureApiSuccess(resp, '关注失败');
        setLeaderboardFollowed((prev) => ({ ...prev, [userId]: true }));
        setLeaderboardFollowNotice(null);
      } catch (error: unknown) {
        setLeaderboardFollowNotice({ type: 'error', text: toErrorMessage(error, '关注失败') });
      } finally {
        setLeaderboardFollowLoading((prev) => ({ ...prev, [userId]: false }));
      }
    },
    [ensureLoggedIn, leaderboardFollowed, user]
  );

  const buildUploadLink = (item: MaterialRequestItem) => {
    const params = new URLSearchParams();
    params.set('requestId', String(item.id));
    if (item.course) params.set('course', item.course);
    if (item.keyword) params.set('keyword', item.keyword);
    if (item.budget != null) params.set('budget', String(item.budget));
    if (item.previewRequirement) params.set('previewRequirement', item.previewRequirement);
    return `/upload?${params.toString()}`;
  };

  const handleFollowRequest = useCallback(
    async (item: MaterialRequestItem) => {
      if (!ensureLoggedIn()) return;
      if (!item?.id) return;
      void router.push(`/requests/${item.id}/follow`);
    },
    [ensureLoggedIn, router]
  );

  const toggleSelection = (materialId: number) => {
    setSelectedIds((prev) => {
      const exists = prev.includes(materialId);
      const next = exists ? prev.filter((id) => id !== materialId) : [...prev, materialId];
      return next;
    });
    setBatchError('');
    setBatchInfo('');
  };

  const handleSelectAll = () => {
    if (!materialList.length) return;
    setSelectedIds((prev) => (prev.length === materialList.length ? [] : materialList.map((item) => item.id)));
    setBatchError('');
    setBatchInfo('');
  };

  const clearSelection = () => {
    setSelectedIds([]);
    setBatchError('');
    setBatchInfo('');
  };

  const handleJumpToLeaderboard = useCallback(() => {
    if (typeof document === 'undefined') return;
    const section = document.getElementById('leaderboard');
    if (section) {
      section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, []);

  const toggleAdvancedFilters = () => {
    setShowAdvanced((prev) => !prev);
  };

  const handleResetFilters = () => {
    setSelectedIds([]);
    setBatchError('');
    setBatchInfo('');
    const nextFilters = normalizeFilters({} as FilterState);
    applyFilters(nextFilters, { scrollTarget: 'filters' });
  };

  const handleViewModeChange = (mode: 'grid' | 'list') => {
    setViewMode(mode);
  };

  const handleBatchShare = async () => {
    if (!selectedCount) return;
    const origin = typeof window !== 'undefined' ? window.location.origin : '';
    const links = selectedMaterials.map((item) => `${origin}${materialPath(item.id, item.title)}`);
    const text = links.join('\n');
    setBatchError('');
    setBatchInfo('');
    if (isLikelyMobile()) {
      const shared = await tryNativeShare({ title: 'StudyHub 资料合集', text });
      if (shared) {
        setBatchInfo('已唤起系统分享。');
        return;
      }
      setShareSheetText(text);
      setShareSheetOpen(true);
      return;
    }
    const copied = await copyToClipboard(text);
    if (copied) {
      setBatchInfo(`已复制 ${selectedCount} 条资料链接`);
      return;
    }
    setBatchError('复制失败，请手动复制。');
  };

  const handlePageChange = async (targetPage: number) => {
    const safeTarget = Number.isNaN(targetPage) ? currentPage : targetPage;
    if (targetPage === currentPage) return;
    if (safeTarget < 1) {
      setPaginationNotice('已经是第一页了');
      return;
    }
    if (totalPages <= 0) {
      setPaginationNotice('暂无更多页码');
      return;
    }
    if (safeTarget > totalPages) {
      setPaginationNotice('已经是最后一页了');
      return;
    }
    const nextFilters = {
      ...filtersState,
      page: String(safeTarget),
    };
    await applyFilters(nextFilters, { scrollTarget: 'materials' });
  };

  const handleFilterSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextFilters = {
      ...filtersState,
      page: '1',
    };
    await applyFilters(nextFilters, { scrollTarget: 'materials' });
  };

  return (
    <>
      <MaterialIconSprite />
      <NavBar user={user} />
      <main className="container page-grid home-page theme-xmas">
        {officialQQ && bannerVisible && (
          <div className="qq-banner">
            <span>加入官方 QQ 群：{officialQQ}</span>
            <button type="button" onClick={dismissBanner}>
              ×
            </button>
          </div>
        )}
        <section className="hero card hero-magazine">
          {showSeasonalEffects && (
            <div className="xmas-snowfall" aria-hidden="true">
              <Snowfall
                snowflakeCount={snowCountFar}
                color="rgba(243, 248, 255, 0.55)"
                radius={[0.6, 2.2]}
                speed={[0.6, 1.6]}
                wind={[-0.2, 1.2]}
                style={snowfallCanvasStyle}
              />
              <Snowfall
                snowflakeCount={snowCountNear}
                color="rgba(255, 255, 255, 0.45)"
                radius={[1.6, 3.4]}
                speed={[1.2, 2.4]}
                wind={[-0.4, 1.6]}
                style={snowfallCanvasStyle}
              />
            </div>
          )}
          {showSeasonalEffects && (
            <div className="hero-meteors" aria-hidden="true">
              {meteorStyles.map((style, index) => (
                <span key={`${meteorSeed}-${index}`} className="hero-meteor" style={style} />
              ))}
            </div>
          )}
          <div className="hero-copy">
            <div className="hero-kicker">StudyHub · 校园资料集</div>
            <h2>贡献资料 · 获取所需</h2>
            <p className="hero-subtitle">你分享的每一份资料，都能让别人少走弯路。</p>
            <div className="hero-actions">
              <div className="hero-action-buttons">
                <Link className="button primary" href="/upload" prefetch={false}>
                  我要投稿
                </Link>
                <Link className="button ghost" href="/join" prefetch={false}>
                  关于我们
                </Link>
                <button className="button ghost" type="button" onClick={handleJumpToLeaderboard}>
                  贡献榜单
                </button>
              </div>
            </div>
          </div>
          <aside className="hero-panel" aria-label="平台数据概览">
            <div className="hero-panel-title">平台概览</div>
            <div className="hero-stats">
              {[
                { label: '已上架', value: statValues.total },
                { label: '免费资料', value: statValues.free },
                { label: '下载次数', value: statValues.downloads },
                { label: '用户个数', value: statValues.users },
              ].map((stat) => (
                <div key={stat.label} className="hero-stat">
                  <span>{stat.label}</span>
                  <strong>{formatNumber(Number(stat.value))}</strong>
                </div>
              ))}
            </div>
          </aside>
        </section>
        <HomeRequestPanels
          requestItems={requestItems}
          requestLoading={requestLoading}
          requestError={requestError}
          requestNotice={requestNotice}
          leaderboardItems={leaderboardItems}
          recommendedItems={recommendedItems}
          recommendationHint={recommendationHint}
          recommendationEmpty={recommendationEmpty}
          buildUploadLink={buildUploadLink}
          onFollowRequest={handleFollowRequest}
        />

        <HomeFilterCard
          filterRef={filterRef}
          filtersState={filtersState}
          showAdvanced={showAdvanced}
          availableTagOptions={availableTagOptions}
          onFilterChange={updateFilter}
          onCourseCategoryChange={applyCourseCategory}
          onToggleAdvancedFilters={toggleAdvancedFilters}
          onResetFilters={handleResetFilters}
          onSubmit={handleFilterSubmit}
        />

        <section className="card" ref={materialsRef} style={{ gridColumn: '1 / -1' }}>
          <div className="materials-header">
            <div>
              <h2 className="card-title">
                资料列表
                <svg className="title-icon" viewBox="0 0 24 24" aria-hidden="true">
                  <rect x="4" y="5" width="16" height="14" rx="2" fill="none" stroke="currentColor" strokeWidth="1.6" />
                  <path d="M8 9h8M8 12h8M8 15h5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
              </h2>
            </div>
            <div className="materials-header__actions">
              <p className="help-text">
                当前第 {pageMeta.page} / {totalPages} 页 · 每页 {pageSize} 条 · 共 {pageMeta.total} 条结果
              </p>
              <div className="view-toggle" role="group" aria-label="列表视图切换">
                <button
                  type="button"
                  className={viewMode === 'grid' ? 'active' : ''}
                  onClick={() => handleViewModeChange('grid')}
                >
                  卡片
                </button>
                <button
                  type="button"
                  className={viewMode === 'list' ? 'active' : ''}
                  onClick={() => handleViewModeChange('list')}
                >
                  列表
                </button>
              </div>
            </div>
          </div>
          <PaginationBar
            currentPage={currentPage}
            totalItems={totalItems}
            pageSize={pageSize}
            loading={loadingPage}
            onPageChange={handlePageChange}
          />
          {paginationError && <p className="error-text">{paginationError}</p>}
          {paginationNotice && !paginationError && <p className="help-text">{paginationNotice}</p>}
          {materialList.length === 0 ? (
            <div className="empty-state">暂无符合筛选条件的资料。</div>
          ) : (
            <>
              <ul className={`materials-list ${viewMode === 'grid' ? 'materials-grid' : 'list-view'}`}>
                {materialList.map((item, idx) => (
                  <MaterialCard
                    key={item.id}
                    material={item}
                    selectable
                    checked={selectedIds.includes(item.id)}
                    onToggle={toggleSelection}
                    variant={viewMode}
                    orderLabel={viewMode === 'list' ? `${(currentPage - 1) * pageSize + idx + 1}` : undefined}
                  />
                ))}
              </ul>
            </>
          )}
        </section>
        <HomeLeaderboard
          user={user}
          topContributors={topContributors}
          leaderboardPeriod={leaderboardPeriod}
          leaderboardLabels={leaderboardLabels}
          leaderboardPeriods={leaderboardPeriods}
          leaderboardRangeHint={leaderboardRangeHint}
          leaderboardEmptyHint={leaderboardEmptyHint}
          leaderboardLoading={leaderboardLoading}
          leaderboardError={leaderboardError}
          leaderboardFollowNotice={leaderboardFollowNotice}
          leaderboardFollowed={leaderboardFollowed}
          leaderboardFollowLoading={leaderboardFollowLoading}
          onPeriodChange={setLeaderboardPeriod}
          onFollowContributor={handleFollowContributor}
        />
        <section className="card support-card" style={{ gridColumn: '1 / -1' }}>
          <div>
            <h3 className="card-title" style={{ margin: 0 }}>
              支持 StudyHub
            </h3>
            <p style={{ marginTop: 8, marginBottom: 4 }}>
              您的支持是我们继续运营的动力😁
            </p>
            <p className="help-text">所有打赏将用于服务器、带宽与内容审核支出，感谢你的信任。</p>
          </div>
          <button className="button primary" type="button" onClick={() => setSupportModalOpen(true)}>
            打赏
          </button>
        </section>
        {supportModalOpen && (
          <div className="modal-mask" onClick={() => setSupportModalOpen(false)}>
            <div
              className="modal-card support-modal"
              role="dialog"
              aria-modal="true"
              aria-label="打赏二维码"
              onClick={(event) => event.stopPropagation()}
            >
              <button
                className="modal-close"
                type="button"
                aria-label="关闭"
                onClick={() => setSupportModalOpen(false)}
              >
                ×
              </button>
              <div className="lazy-image-box qr-large">
                <AppImage
                  className="lazy-blur"
                  src="/payments/support.png"
                  alt="打赏二维码"
                  loading="lazy"
                  decoding="async"
                  onLoad={(event) => event.currentTarget.classList.add('is-loaded')}
                />
              </div>
            </div>
          </div>
        )}
        {selectedCount > 0 && (
          <div className="batch-action-bar">
            <div>
              <strong>批量分享</strong>
              <span className="status-text muted">已选择 {selectedCount} 条资料。</span>
              {batchInfo && <span className="status-text success">{batchInfo}</span>}
              {batchError && <span className="status-text error">{batchError}</span>}
            </div>
            <div className="inline-group">
              <button className="button ghost small" type="button" onClick={clearSelection}>
                清空
              </button>
              <button className="button primary" type="button" onClick={handleBatchShare}>
                批量分享
              </button>
            </div>
          </div>
        )}
        <ShareSheet
          open={shareSheetOpen}
          title="批量分享"
          text={shareSheetText}
          onClose={() => setShareSheetOpen(false)}
        />
      </main>
    </>
  );
}

const sanitizeFilter = (value: string | string[] | undefined) => {
  if (Array.isArray(value)) return value[0]?.trim() ?? '';
  return typeof value === 'string' ? value.trim() : '';
};

const sanitizeSchool = (value: string) => (value === SUPPORTED_SCHOOL ? value : '');
const sanitizeMetadataChoice = (value: string, allowed: readonly string[]) => (allowed.includes(value) ? value : '');
const sanitizeCourseCategory = (value: string) =>
  COURSE_CATEGORY_VALUES.includes(value as (typeof COURSE_CATEGORY_VALUES)[number]) ? value : '';

export const getServerSideProps: GetServerSideProps<HomeProps> = async (ctx) => {
  const session = readSession(ctx.req);
  const rawSchool = sanitizeFilter(ctx.query.school);
  const rawCollege = sanitizeFilter(ctx.query.college);
  const rawMajor = sanitizeFilter(ctx.query.major);
  const origin = getRequestOrigin(ctx.req);
  const filters: FilterState = {
    keyword: sanitizeFilter(ctx.query.keyword),
    school: sanitizeSchool(rawSchool),
    college: sanitizeMetadataChoice(rawCollege, SUPPORTED_COLLEGES),
    major: sanitizeMetadataChoice(rawMajor, SUPPORTED_MAJORS),
    tag: sanitizeFilter(ctx.query.tag),
    gradeValue: sanitizeMetadataChoice(sanitizeFilter(ctx.query.gradeValue), GRADE_STAGE_OPTIONS),
    courseCategory: sanitizeCourseCategory(sanitizeFilter(ctx.query.courseCategory)),
    price: sanitizeFilter(ctx.query.price),
    sort: sanitizeFilter(ctx.query.sort) || 'latest',
    page: sanitizeFilter(ctx.query.page) || '1',
    size: String(MATERIALS_PAGE_SIZE),
  };
  const defaultMeta: PaginationMeta = { page: Number(filters.page) || 1, size: MATERIALS_PAGE_SIZE, total: 0 };
  const materialsPromise = fetchMaterials({ ...filters, size: MATERIALS_PAGE_SIZE }, session.token || undefined, origin)
    .then((data) => ({
      materials: data.items,
      meta: { ...data.meta, size: Math.min(data.meta?.size ?? MATERIALS_PAGE_SIZE, MATERIALS_PAGE_SIZE) },
      stats: data.stats || null,
      tagOptions: data.availableTags || [],
    }))
    .catch((error) => {
      // eslint-disable-next-line no-console
      console.warn('Failed to fetch materials', error);
      return {
        materials: [] as MaterialListItem[],
        meta: defaultMeta,
        stats: null,
        tagOptions: [] as string[],
      };
    });
  const profilePromise: Promise<ProfileSummary | null> = session.user && session.token
    ? fetchProfile(session.token, origin).catch((error) => {
        // eslint-disable-next-line no-console
        console.warn('Failed to fetch profile summary', error);
        return null;
      })
    : Promise.resolve(null);
  const recommendationsPromise: Promise<MaterialListItem[]> = fetchRecommendations(
    session.token || undefined,
    origin
  ).catch((error) => {
    // eslint-disable-next-line no-console
    console.warn('Failed to fetch recommendations', error);
    return [] as MaterialListItem[];
  });
  const requestsPromise: Promise<MaterialRequestItem[]> = fetchMaterialRequests(
    { sort: 'hot', limit: 0 },
    session.token || undefined,
    origin
  ).catch((error) => {
    // eslint-disable-next-line no-console
    console.warn('Failed to fetch requests', error);
    return [] as MaterialRequestItem[];
  });
  const requestLeaderboardPromise: Promise<MaterialRequestItem[]> = fetchRequestLeaderboard(
    5,
    session.token || undefined,
    origin
  ).catch((error) => {
    // eslint-disable-next-line no-console
    console.warn('Failed to fetch request leaderboard', error);
    return [] as MaterialRequestItem[];
  });
  const contributorsPromise: Promise<ContributorRank[]> = fetchContributorRanks({
    limit: 50,
    period: 'all',
    origin,
  }).catch((error) => {
    // eslint-disable-next-line no-console
    console.warn('Failed to fetch contributors', error);
    return [] as ContributorRank[];
  });
  const [{ materials, meta, stats, tagOptions }, profileSummary, recommendations, requests, requestLeaderboard, contributors] =
    await Promise.all([
      materialsPromise,
      profilePromise,
      recommendationsPromise,
      requestsPromise,
      requestLeaderboardPromise,
      contributorsPromise,
    ]);
  const officialQQ = process.env.NEXT_PUBLIC_OFFICIAL_QQ || process.env.OFFICIAL_QQ || '';

  return {
    props: {
      materials,
      meta,
      filters,
      user: session.user,
      officialQQ,
      stats,
      tagOptions,
      profileSummary,
      recommendations,
      requests,
      requestLeaderboard,
      contributors,
    },
  };
};
