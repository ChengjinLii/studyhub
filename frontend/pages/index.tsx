import type React from 'react';
import { GetServerSideProps } from 'next';
import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/router';
import NavBar from '../components/NavBar';
import AppImage from '../components/AppImage';
import MaterialIconSprite from '../components/MaterialIconSprite';
import HomeFilterCard from '../components/home/HomeFilterCard';
import HomeMaterialLibrary from '../components/home/HomeMaterialLibrary';
import HomePortal from '../components/home/HomePortal';
import { materialBrowseScope } from '../lib/materialBrowseSession';
import { MaterialBrowseMode, MaterialSubjectScope, useMaterialSubjects } from '../lib/useMaterialSubjects';
import { computeHomeRevealTail, easeHomeRevealProgress, rankHomeSubjects } from '../lib/homeDiscovery';
import discoveryStyles from '../styles/HomeDiscovery.module.css';
import minStyles from '../styles/HomeMinimal.module.css';
import type { SubjectSearchAliases } from '../lib/materialSubjects';
import { readMaterialSubjectAliases } from '../lib/server/materialSubjectAliases';
import { useMaterialBrowseReturn } from '../lib/useMaterialBrowseReturn';
import { MaterialListItem, PaginationMeta } from '../types/material';
import { SessionUser, RoleMask } from '../types/user';
import { ProfileSummary } from '../types/profile';
import { readSession, hasRole } from '../lib/auth';
import {
  fetchMaterials,
  MaterialListStats,
  MaterialListResponse,
  fetchContributorRanks,
  fetchMaterialRequests,
  fetchRequestLeaderboard,
} from '../lib/api';
import { fetchBackend } from '../lib/apiBase';
import { getRequestOrigin } from '../lib/apiBase';
import { ensureApiSuccess, unwrapApiResponse } from '../lib/apiEnvelope';
import { toErrorMessage } from '../lib/errors';
import { formatDate, formatNumber } from '../lib/format';
import { fetchHomeProfileContext } from '../lib/homeProfileContext';
import {
  SUPPORTED_SCHOOL,
  SUPPORTED_COLLEGES,
  SUPPORTED_MAJORS,
  COURSE_CATEGORY_OPTIONS,
  COURSE_CATEGORY_VALUES,
  GRADE_STAGE_OPTIONS,
} from '../constants/metadata';
import { getTierLabel } from '../constants/request';
import { normalizeMaterialSort } from '../constants/materialSort';
import { ContributorRank, LeaderboardPeriod } from '../types/contributor';
import { MaterialRequestItem } from '../types/request';

const MATERIALS_PAGE_SIZE = 24;
const HOME_REQUEST_PREVIEW_LIMIT = 8;
const HOME_POPULAR_PREVIEW_LIMIT = 20;
// Home page, desktop: the content under the first screen stays closed until the reader has
// scrolled this far (px). The navbar is 64px high.
const HOME_REVEAL_DISTANCE = 280;
const HOME_MOBILE_REVEAL_DISTANCE = 120;
const HOME_REVEAL_SETTLE_MS = 180;
const HOME_REVEAL_FADE_CLEANUP_MS = 860;
const HOME_NAVBAR_HEIGHT = 64;
const HOME_MOBILE_NAVBAR_HEIGHT = 58;
const HOME_PHONE_MAX_WIDTH = 768;

const clearHomeRevealVars = () => {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.style.removeProperty('--home-reveal');
  root.style.removeProperty('--home-reveal-tail');
  delete root.dataset.homeRevealComplete;
};
// True from the first opening until a full reload, so a return to the home page inside the app
// does not close the content again.
let homeContentOpened = false;
type HomeRevealMotion = 'rise' | 'none';

/** Scrolls the content under the first screen up to the navbar. */
const glideToHomeContent = () => {
  const content = document.getElementById('home-content');
  if (!content) return;
  const headerHeight =
    window.innerWidth <= HOME_PHONE_MAX_WIDTH ? HOME_MOBILE_NAVBAR_HEIGHT : HOME_NAVBAR_HEIGHT;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  window.scrollTo({
    top: window.scrollY + content.getBoundingClientRect().top - headerHeight,
    behavior: reduceMotion ? 'auto' : 'smooth',
  });
};

const HomeLeaderboard = dynamic(() => import('../components/home/HomeLeaderboard'));
const MobileHomeSections = dynamic(() => import('../components/home/MobileHomeSections'));
// Phone only: the search portal is not shown at phone width, so the discovery card and the
// cooperation card stay in the page flow there.
const HomeDiscoveryCard = dynamic(() =>
  import('../components/home/HomeRequestPanels').then((mod) => mod.HomeDiscoveryCard)
);
const HomeCooperationCard = dynamic(() =>
  import('../components/home/HomeRequestPanels').then((mod) => mod.HomeCooperationCard)
);

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
  subjectSearchAliases?: SubjectSearchAliases;
  materials: MaterialListItem[];
  meta: PaginationMeta;
  filters: FilterState;
  user: SessionUser | null;
  officialQQ?: string;
  stats: MaterialListStats | null;
  tagOptions: string[];
  profileSummary: ProfileSummary | null;
  profileMissingFields: string[];
  popularMaterials: MaterialListItem[];
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
  profileMissingFields,
  popularMaterials,
  requests,
  requestLeaderboard,
  contributors: initialContributors,
  subjectSearchAliases,
}: HomeProps) {
  const router = useRouter();
  const isAdmin = Boolean(user && hasRole(user.roleMask, RoleMask.ADMIN));
  const [materialList, setMaterialList] = useState(initialMaterials);
  const [mobileSearch, setMobileSearch] = useState(initialFilters.keyword || '');
  const [pageMeta, setPageMeta] = useState(meta);
  const [statsState, setStatsState] = useState(stats);
  const [tagOptionsState, setTagOptionsState] = useState(tagOptions);
  const [loadingPage, setLoadingPage] = useState(false);
  const [paginationError, setPaginationError] = useState('');
  const [paginationNotice, setPaginationNotice] = useState('');
  const filterRef = useRef<HTMLDivElement>(null);
  const materialsRef = useRef<HTMLDivElement>(null);
  const [contentRevealed, setContentRevealed] = useState(() => homeContentOpened);
  const [revealMotion, setRevealMotion] = useState<HomeRevealMotion>('none');
  const revealSettleTimerRef = useRef<number | null>(null);
  const revealCleanupTimerRef = useRef<number | null>(null);
  const clearRevealTimers = useCallback(() => {
    for (const ref of [revealSettleTimerRef, revealCleanupTimerRef]) {
      if (ref.current !== null) {
        window.clearTimeout(ref.current);
        ref.current = null;
      }
    }
  }, []);
  useEffect(() => {
    return () => {
      clearRevealTimers();
      clearHomeRevealVars();
    };
  }, [clearRevealTimers]);
  // Opens the content under the first screen. The attributes change at once, so a scroll to the
  // content in the same task finds it laid out; the state follows. The cards rise into place
  // only when the reader's scroll opens them ('rise'): a jump to a section measures the place
  // of that section, and a card in motion would give a wrong place.
  const revealContent = useCallback((motion: HomeRevealMotion = 'none') => {
    homeContentOpened = true;
    clearRevealTimers();
    const content = document.getElementById('home-content');
    content?.setAttribute('data-reveal-motion', motion);
    content?.setAttribute('data-revealed', 'true');
    if (motion === 'rise') {
      const root = document.documentElement;
      root.style.setProperty('--home-reveal', '1');
      root.style.setProperty('--home-reveal-tail', '1');
      root.dataset.homeRevealComplete = 'true';
      revealCleanupTimerRef.current = window.setTimeout(() => {
        revealCleanupTimerRef.current = null;
        clearHomeRevealVars();
      }, HOME_REVEAL_FADE_CLEANUP_MS);
    } else {
      clearHomeRevealVars();
    }
    setRevealMotion(motion);
    setContentRevealed(true);
  }, [clearRevealTimers]);
  const scrollToContent = useCallback(() => {
    revealContent('rise');
    glideToHomeContent();
  }, [revealContent]);
  // The content opens when the reader has scrolled HOME_REVEAL_DISTANCE on the first screen.
  // The line on the strip of the first screen fills over that distance (--home-reveal).
  useEffect(() => {
    const getRevealDistance = () =>
      window.innerWidth <= HOME_PHONE_MAX_WIDTH ? HOME_MOBILE_REVEAL_DISTANCE : HOME_REVEAL_DISTANCE;
    // A restored scroll position, a search in the address, or a link to a section opens at once.
    if (
      !contentRevealed &&
      (window.scrollY >= getRevealDistance() || window.location.search || window.location.hash)
    ) {
      revealContent();
      return undefined;
    }
    let frame: number | null = null;
    let wheelDistance = 0;
    let wheelResetTimer: number | null = null;
    let wheelTriggered = false;
    const clearWheelCue = () => {
      document.documentElement.style.removeProperty('--home-wheel-progress');
      delete document.documentElement.dataset.homeWheelActive;
      wheelDistance = 0;
      wheelTriggered = false;
    };
    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.deltaY === 0 || window.scrollY >= getRevealDistance() || wheelTriggered) return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (target.closest('[role="dialog"], [role="listbox"], [data-radix-popper-content-wrapper]')) return;
      const wheelList = target.closest<HTMLElement>('[data-edge]');
      if (wheelList) {
        const maxScroll = wheelList.scrollHeight - wheelList.clientHeight;
        if ((event.deltaY > 0 && wheelList.scrollTop < maxScroll - 1) ||
            (event.deltaY < 0 && wheelList.scrollTop > 1)) return;
      }
      if (event.deltaY < 0 && wheelDistance === 0) return;
      event.preventDefault();
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? window.innerHeight : 1);
      wheelDistance = Math.max(0, Math.min(220, wheelDistance + delta));
      const root = document.documentElement;
      root.dataset.homeWheelActive = 'true';
      root.style.setProperty('--home-wheel-progress', String(wheelDistance / 220));
      if (wheelResetTimer !== null) window.clearTimeout(wheelResetTimer);
      if (wheelDistance >= 220) {
        wheelTriggered = true;
        scrollToContent();
        wheelResetTimer = window.setTimeout(clearWheelCue, 1500);
      } else {
        wheelResetTimer = window.setTimeout(clearWheelCue, 2000);
      }
    };
    const onScroll = () => {
      if (contentRevealed) return;
      if (frame !== null) return;
      frame = window.requestAnimationFrame(() => {
        frame = null;
        const root = document.documentElement;
        const revealScale =
          window.innerWidth <= HOME_PHONE_MAX_WIDTH ? HOME_REVEAL_DISTANCE / HOME_MOBILE_REVEAL_DISTANCE : 1;
        const raw = Math.min(1, Math.max(0, (window.scrollY / HOME_REVEAL_DISTANCE) * revealScale));
        if (raw < 1) {
          const progress = easeHomeRevealProgress(raw);
          delete root.dataset.homeRevealComplete;
          root.style.setProperty('--home-reveal', progress.toFixed(3));
          root.style.setProperty('--home-reveal-tail', computeHomeRevealTail(progress).toFixed(3));
          return;
        }
        window.removeEventListener('scroll', onScroll);
        root.style.setProperty('--home-reveal', '1');
        root.style.setProperty('--home-reveal-tail', '1');
        root.dataset.homeRevealComplete = 'true';
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
          revealContent('rise');
          glideToHomeContent();
          return;
        }
        clearRevealTimers();
        revealSettleTimerRef.current = window.setTimeout(() => {
          revealSettleTimerRef.current = null;
          revealContent('rise');
          glideToHomeContent();
        }, HOME_REVEAL_SETTLE_MS);
      });
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('wheel', onWheel);
      if (wheelResetTimer !== null) window.clearTimeout(wheelResetTimer);
      clearWheelCue();
      if (frame !== null) window.cancelAnimationFrame(frame);
      if (!homeContentOpened) {
        clearHomeRevealVars();
      }
    };
  }, [clearRevealTimers, contentRevealed, revealContent, scrollToContent]);
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
  const [appliedFilters, setAppliedFilters] = useState<FilterState>(() => normalizeFilters(initialFilters));
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
    async (nextFilters: FilterState, options?: { scrollTarget?: 'filters' | 'materials'; preserveSubject?: boolean }) => {
      const normalized = normalizeFilters(nextFilters);
      setLoadingPage(true);
      setPaginationError('');
      setPaginationNotice('');
      setFiltersState(normalized);
      const query = buildQuery(normalized);
      try {
        const resp = await fetchBackend(`/materials${buildQueryString({ ...query, size: MATERIALS_PAGE_SIZE })}`);
        const data = await unwrapApiResponse<MaterialListResponse>(resp, '筛选加载失败');
        setMaterialList(data.items);
        setPageMeta(data.meta);
        setAppliedFilters(normalized);
        if (!options?.preserveSubject) {
          setSubjectId(null);
          setSubjectScope('filtered');
        }
        setSubjectPage(1);
        if (data.stats) setStatsState(data.stats);
        if (data.availableTags) setTagOptionsState(data.availableTags);
        await router.replace({ pathname: '/', query }, undefined, { shallow: true, scroll: false });
        requestAnimationFrame(() => {
          if (options?.scrollTarget === 'materials') revealContent();
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
    [buildQuery, buildQueryString, normalizeFilters, revealContent, router]
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
  const freeCount = useMemo(() => materialList.filter((item) => item.free).length, [materialList]);
  const statSource = statsState || stats || null;
  const statValues = {
    total: statSource?.totalMaterials ?? pageMeta.total ?? 0,
    free: statSource?.freeMaterials ?? freeCount,
    downloads: statSource?.totalDownloads ?? 0,
    users: statSource?.userCount ?? 0,
  };
  const mobileOverviewStats = [
    { label: '已上架', value: formatNumber(Number(statValues.total)) },
    { label: '免费资料', value: formatNumber(Number(statValues.free)) },
    { label: '下载次数', value: formatNumber(Number(statValues.downloads)) },
    { label: '用户个数', value: formatNumber(Number(statValues.users)) },
  ];
  const mobileLatestItems = useMemo(() => materialList.slice(0, 5), [materialList]);
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
    return Boolean(
      filtersState.school ||
        filtersState.college ||
        filtersState.tag ||
        filtersState.courseCategory ||
        priceActive
    );
  }, [
    filtersState.school,
    filtersState.college,
    filtersState.tag,
    filtersState.courseCategory,
    filtersState.price,
  ]);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [browseMode, setBrowseMode] = useState<MaterialBrowseMode>('materials');
  const [subjectId, setSubjectId] = useState<string | null>(null);
  const [subjectPage, setSubjectPage] = useState(1);
  const [subjectScope, setSubjectScope] = useState<MaterialSubjectScope>('filtered');
  const subjects = useMaterialSubjects({ ...appliedFilters }, subjectSearchAliases);
  const subjectRanks = useMemo(() => rankHomeSubjects(subjects.catalogueFolders), [subjects.catalogueFolders]);
  const effectivePopularMaterials = useMemo(() => {
    if (popularMaterials.some((item) => (item.downloadCount ?? 0) > 1)) {
      return popularMaterials;
    }
    const byId = new Map<number, MaterialListItem>();
    subjects.catalogueFolders.forEach((folder) => {
      folder.materials.forEach((item) => {
        if (!byId.has(item.id)) {
          byId.set(item.id, item);
        }
      });
    });
    materialList.forEach((item) => {
      if (!byId.has(item.id)) {
        byId.set(item.id, item);
      }
    });
    const sorted = Array.from(byId.values())
      .sort((a, b) => (b.downloadCount ?? 0) - (a.downloadCount ?? 0) || b.id - a.id)
      .slice(0, HOME_POPULAR_PREVIEW_LIMIT);
    return sorted.length ? sorted : popularMaterials;
  }, [popularMaterials, subjects.catalogueFolders, materialList]);
  const scrollToMaterials = useCallback(() => {
    revealContent();
    requestAnimationFrame(() => {
      const root = document.documentElement;
      const previous = root.style.scrollBehavior;
      root.style.scrollBehavior = 'auto';
      // Immediate positioning prevents anchor drift when opening a detail right away.
      materialsRef.current?.scrollIntoView({ block: 'start', behavior: 'auto' });
      root.style.scrollBehavior = previous;
    });
  }, [revealContent]);
  const handleSubjectChange = useCallback((id: string | null, scope: MaterialSubjectScope) => {
    setSubjectId(id);
    setSubjectScope(scope);
    setSubjectPage(1);
    // User-initiated opening only; history restoration must retain its saved position.
    if (id) scrollToMaterials();
  }, [scrollToMaterials]);
  const browseAllSubjects = useCallback(() => {
    setBrowseMode('subjects');
    setSubjectScope('all');
    setSubjectId(null);
    setSubjectPage(1);
    scrollToMaterials();
  }, [scrollToMaterials]);
  const browseAllMaterials = useCallback(() => {
    setBrowseMode('materials');
    setSubjectScope('filtered');
    setSubjectId(null);
    scrollToMaterials();
  }, [scrollToMaterials]);
  const [contributors, setContributors] = useState<ContributorRank[]>(initialContributors);
  const [leaderboardPeriod, setLeaderboardPeriod] = useState<LeaderboardPeriod>('all');
  const loadedLeaderboardPeriodRef = useRef<LeaderboardPeriod>('all');
  const [leaderboardLoading, setLeaderboardLoading] = useState(false);
  const [leaderboardError, setLeaderboardError] = useState('');
  const [requestItems] = useState<MaterialRequestItem[]>(requests || []);
  const [leaderboardItems] = useState<MaterialRequestItem[]>(requestLeaderboard || []);
  const requestLoading = false;
  const requestError = '';
  const requestNotice: { type: 'success' | 'error'; text: string } | null = null;
  const [leaderboardFollowed, setLeaderboardFollowed] = useState<Record<number, boolean>>({});
  const [leaderboardFollowLoading, setLeaderboardFollowLoading] = useState<Record<number, boolean>>({});
  const [leaderboardFollowNotice, setLeaderboardFollowNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [supportModalOpen, setSupportModalOpen] = useState(false);
  useEffect(() => {
    setMaterialList(initialMaterials);
    setPageMeta(meta);
    setStatsState(stats);
    setTagOptionsState(tagOptions);
  }, [initialMaterials, meta, stats, tagOptions]);
  useMaterialBrowseReturn({
    source: '/',
    scope: materialBrowseScope(user),
    state: {
      filters: { ...filtersState },
      appliedFilters: { ...appliedFilters },
      materials: materialList,
      meta: pageMeta,
      availableTags: tagOptionsState,
      mode: browseMode,
      subjectId,
      subjectPage,
      subjectScope,
      selectedIds: [],
      showAdvanced,
    },
    onRestore: (snapshot) => {
      setFiltersState(normalizeFilters({ ...initialFilters, ...snapshot.filters }));
      setAppliedFilters(normalizeFilters({ ...initialFilters, ...(snapshot.appliedFilters || snapshot.filters) }));
      setMaterialList(snapshot.materials);
      setPageMeta(snapshot.meta);
      setTagOptionsState(snapshot.availableTags);
      setBrowseMode(snapshot.mode);
      setSubjectId(snapshot.subjectId);
      setSubjectPage(snapshot.subjectPage);
      setSubjectScope(snapshot.subjectScope || 'filtered');
      setShowAdvanced(snapshot.showAdvanced || false);
    },
  });
  const pageSize = pageMeta.size || MATERIALS_PAGE_SIZE;
  const currentPage = pageMeta.page || 1;
  const totalPages = useMemo(
    () => Math.max(1, Math.ceil((pageMeta.total || 0) / pageSize)),
    [pageMeta.total, pageSize]
  );
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
    setShowAdvanced(false);
  }, []);

  const currentUserId = user?.id ?? null;
  useEffect(() => {
    if (!currentUserId) {
      setLeaderboardFollowed({});
      return;
    }
    let cancelled = false;
    const loadFollowing = async () => {
      try {
        const resp = await fetchBackend(`/users/${currentUserId}/following`);
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
  }, [currentUserId]);

  useEffect(() => {
    if (loadedLeaderboardPeriodRef.current === leaderboardPeriod) {
      return;
    }
    let cancelled = false;
    setLeaderboardLoading(true);
    setLeaderboardError('');
    const origin = typeof window !== 'undefined' ? window.location.origin : undefined;
    fetchContributorRanks({ limit: 50, period: leaderboardPeriod, origin })
      .then((data) => {
        if (!cancelled) {
          loadedLeaderboardPeriodRef.current = leaderboardPeriod;
          setContributors(data);
        }
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

  const handleJumpToLeaderboard = useCallback(() => {
    if (typeof document === 'undefined') return;
    revealContent();
    const section = document.getElementById('leaderboard');
    if (section) {
      section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [revealContent]);

  const toggleAdvancedFilters = () => {
    setShowAdvanced((prev) => !prev);
  };

  const handleResetFilters = () => {
    const nextFilters = normalizeFilters({} as FilterState);
    applyFilters(nextFilters, { scrollTarget: 'filters' });
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

  const handleMaterialSortChange = async (sort: string) => {
    const nextFilters = {
      ...filtersState,
      sort: normalizeMaterialSort(sort),
      page: '1',
    };
    await applyFilters(nextFilters, { scrollTarget: 'materials', preserveSubject: true });
  };

  const handleMobileSearchSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const keyword = mobileSearch.trim();
    void router.push(keyword ? `/materials?keyword=${encodeURIComponent(keyword)}` : '/materials');
  };

  return (
    <>
      <MaterialIconSprite />
      <NavBar user={user} />
      {/* First screen: the search portal. The sections under it start in <main>. */}
      <HomePortal
        search={
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
        }
        popularItems={effectivePopularMaterials}
        subjectRanks={subjectRanks}
        stats={{
          users: mobileOverviewStats[3].value,
          materials: mobileOverviewStats[0].value,
          free: mobileOverviewStats[1].value,
          downloads: mobileOverviewStats[2].value,
          subjects: subjectRanks.length > 0 ? formatNumber(subjectRanks.length) : '—',
        }}
        officialQQ={officialQQ}
        onOpenSubject={(id) => { setBrowseMode('subjects'); handleSubjectChange(id, 'all'); }}
        onBrowseSubjects={browseAllSubjects}
        onBrowseMaterials={browseAllMaterials}
        onJumpToLeaderboard={handleJumpToLeaderboard}
        onScrollDown={scrollToContent}
      />
      <main
        id="home-content"
        className={`container page-grid home-page ${minStyles.page}`}
        data-revealed={contentRevealed ? 'true' : 'false'}
        data-reveal-motion={revealMotion}
      >
        <MobileHomeSections
          mobileSearch={mobileSearch}
          stats={mobileOverviewStats}
          latestItems={mobileLatestItems}
          onMobileSearchChange={setMobileSearch}
          onMobileSearchSubmit={handleMobileSearchSubmit}
          onJumpToLeaderboard={handleJumpToLeaderboard}
        />
        {/* Under the first screen: the classic cards of the main branch, one under the other. */}
        <div className={`home-desktop-library${browseMode === 'subjects' || subjectId ? ` ${discoveryStyles.mobileSubjects}` : ''}`}>
          <HomeMaterialLibrary
            materialsRef={materialsRef} materials={materialList} meta={pageMeta}
            keyword={appliedFilters.keyword} sort={filtersState.sort} loading={loadingPage}
            error={paginationError} notice={paginationNotice} mode={browseMode}
            onModeChange={(mode) => { setBrowseMode(mode); setSubjectScope('filtered'); setSubjectId(null); setSubjectPage(1); }}
            onSortChange={(value) => void handleMaterialSortChange(value)} onPageChange={handlePageChange}
            subjects={subjects} subjectId={subjectId} subjectPage={subjectPage} subjectScope={subjectScope}
            onSubjectChange={(id) => handleSubjectChange(id, subjectScope)} onSubjectPageChange={setSubjectPage}
            onReset={handleResetFilters}
            onEditKeyword={() => filterRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
          />
        </div>
        <div className={minStyles.phoneOnly} data-home-phone-discovery="">
          <HomeDiscoveryCard
            requestItems={requestItems}
            requestLoading={requestLoading}
            requestError={requestError}
            requestNotice={requestNotice}
            leaderboardItems={leaderboardItems}
            popularItems={effectivePopularMaterials}
            subjectRanks={subjectRanks}
            subjectsUpdatedAt={subjects.updatedAt}
            onOpenSubject={(id) => { setBrowseMode('subjects'); handleSubjectChange(id, 'all'); }}
            onBrowseSubjects={browseAllSubjects}
            onBrowseMaterials={browseAllMaterials}
            buildUploadLink={buildUploadLink}
            onFollowRequest={handleFollowRequest}
          />
        </div>
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
        <div className={minStyles.phoneOnly} data-home-phone-cooperation="">
          <HomeCooperationCard profileMissingFields={profileMissingFields} />
        </div>
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
    sort: normalizeMaterialSort(sanitizeFilter(ctx.query.sort)),
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
  const profileContextPromise = session.user && session.token
    ? fetchHomeProfileContext(session.token, origin)
    : Promise.resolve({ summary: null, missingFields: [] });
  const requestsPromise: Promise<MaterialRequestItem[]> = fetchMaterialRequests(
    { sort: 'hot', limit: HOME_REQUEST_PREVIEW_LIMIT },
    session.token || undefined,
    origin
  ).catch((error) => {
    // eslint-disable-next-line no-console
    console.warn('Failed to fetch requests', error);
    return [] as MaterialRequestItem[];
  });
  const popularMaterialsPromise: Promise<MaterialListItem[]> = fetchMaterials(
    { sort: 'recent_downloads', page: 1, size: HOME_POPULAR_PREVIEW_LIMIT },
    session.token || undefined,
    origin
  )
    .then((data) => data.items.slice(0, HOME_POPULAR_PREVIEW_LIMIT))
    .catch((error) => {
      // eslint-disable-next-line no-console
      console.warn('Failed to fetch popular materials', error);
      return [] as MaterialListItem[];
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
  const [
    { materials, meta, stats, tagOptions },
    profileContext,
    popularMaterials,
    requests,
    requestLeaderboard,
    contributors,
  ] =
    await Promise.all([
      materialsPromise,
      profileContextPromise,
      popularMaterialsPromise,
      requestsPromise,
      requestLeaderboardPromise,
      contributorsPromise,
    ]);
  const officialQQ = process.env.NEXT_PUBLIC_OFFICIAL_QQ || process.env.OFFICIAL_QQ || '';

  return {
    props: {
      subjectSearchAliases: readMaterialSubjectAliases(),
      materials,
      meta,
      filters,
      user: session.user,
      officialQQ,
      stats,
      tagOptions,
      profileSummary: profileContext.summary,
      profileMissingFields: profileContext.missingFields,
      popularMaterials,
      requests,
      requestLeaderboard,
      contributors,
    },
  };
};
