import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { FormEvent, useMemo, useState } from 'react';
import MaterialCard from '../../components/MaterialCard';
import MaterialSortSelect from '../../components/materials/MaterialSortSelect';
import NavBar from '../../components/NavBar';
import MobileFilterDrawer, { MobileMaterialFilterState } from '../../components/mobile/MobileFilterDrawer';
import {
  COURSE_CATEGORY_VALUES,
  GRADE_STAGE_OPTIONS,
  SUPPORTED_COLLEGES,
  SUPPORTED_MAJORS,
  SUPPORTED_SCHOOL,
} from '../../constants/metadata';
import { fetchMaterials, MaterialListStats } from '../../lib/api';
import { getRequestOrigin } from '../../lib/apiBase';
import { readSession } from '../../lib/auth';
import { formatNumber } from '../../lib/format';
import { normalizeMaterialSort } from '../../constants/materialSort';
import { MaterialListItem, PaginationMeta } from '../../types/material';
import { SessionUser } from '../../types/user';

const MATERIALS_PAGE_SIZE = 18;
const DEFAULT_TAG_OPTIONS = ['期末真题', '期末速成', '日常学习笔记', '教材答案', '一页纸', '开卷资料'];

interface MaterialsPageProps {
  user: SessionUser | null;
  materials: MaterialListItem[];
  meta: PaginationMeta;
  filters: MobileMaterialFilterState;
  stats: MaterialListStats | null;
  tagOptions: string[];
}

const sanitizeFilter = (value: string | string[] | undefined) => {
  if (Array.isArray(value)) return value[0]?.trim() ?? '';
  return typeof value === 'string' ? value.trim() : '';
};

const sanitizeSchool = (value: string) => (value === SUPPORTED_SCHOOL ? value : '');
const sanitizeMetadataChoice = (value: string, allowed: readonly string[]) => (allowed.includes(value) ? value : '');
const sanitizeCourseCategory = (value: string) =>
  COURSE_CATEGORY_VALUES.includes(value as (typeof COURSE_CATEGORY_VALUES)[number]) ? value : '';

const toMaterialQuery = (filters: MobileMaterialFilterState, page = filters.page) => ({
  keyword: filters.keyword || undefined,
  school: filters.school || undefined,
  college: filters.college || undefined,
  major: filters.major || undefined,
  tag: filters.tag || undefined,
  gradeValue: filters.gradeValue || undefined,
  courseCategory: filters.courseCategory || undefined,
  price: filters.price || undefined,
  sort: filters.sort || 'latest',
  page,
  size: String(MATERIALS_PAGE_SIZE),
});

const normalizeLoadedMeta = (meta: PaginationMeta | undefined): PaginationMeta => ({
  page: Number(meta?.page) || 1,
  size: Math.min(Number(meta?.size) || MATERIALS_PAGE_SIZE, MATERIALS_PAGE_SIZE),
  total: Number(meta?.total) || 0,
});

export default function MaterialsPage({ user, materials, meta, filters, stats, tagOptions }: MaterialsPageProps) {
  const [filtersState, setFiltersState] = useState(filters);
  const [materialList, setMaterialList] = useState(materials);
  const [pageMeta, setPageMeta] = useState(meta);
  const [availableTags, setAvailableTags] = useState(tagOptions);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const quickTags = useMemo(() => {
    const source = availableTags.length > 0 ? availableTags : DEFAULT_TAG_OPTIONS;
    return source.slice(0, 8);
  }, [availableTags]);
  const activeFilterCount = [
    filtersState.keyword,
    filtersState.school,
    filtersState.college,
    filtersState.major,
    filtersState.tag,
    filtersState.gradeValue,
    filtersState.courseCategory,
    filtersState.price,
  ].filter(Boolean).length;
  const hasMore = pageMeta.page * pageMeta.size < pageMeta.total;

  const updateFilter = (key: keyof MobileMaterialFilterState, value: string) => {
    setFiltersState((prev) => ({ ...prev, [key]: value, page: '1', size: String(MATERIALS_PAGE_SIZE) }));
  };

  const loadPage = async (nextFilters: MobileMaterialFilterState, page: number, append = false) => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchMaterials(toMaterialQuery(nextFilters, String(page)));
      setMaterialList((prev) => (append ? [...prev, ...data.items] : data.items));
      setPageMeta(normalizeLoadedMeta(data.meta));
      setAvailableTags(data.availableTags || availableTags);
    } catch (err) {
      setError(err instanceof Error ? err.message : '资料加载失败，请稍后重试。');
    } finally {
      setLoading(false);
    }
  };

  const applyFilters = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    await loadPage({ ...filtersState, page: '1' }, 1);
    setDrawerOpen(false);
  };

  const resetFilters = async () => {
    const nextFilters: MobileMaterialFilterState = {
      keyword: '',
      school: '',
      college: '',
      major: '',
      tag: '',
      gradeValue: '',
      courseCategory: '',
      price: '',
      sort: 'latest',
      page: '1',
      size: String(MATERIALS_PAGE_SIZE),
    };
    setFiltersState(nextFilters);
    await loadPage(nextFilters, 1);
    setDrawerOpen(false);
  };

  const handleQuickTag = async (tag: string) => {
    const nextTag = filtersState.tag === tag ? '' : tag;
    const nextFilters = { ...filtersState, tag: nextTag, page: '1' };
    setFiltersState(nextFilters);
    await loadPage(nextFilters, 1);
  };

  const handlePrice = async (price: string) => {
    const nextFilters = { ...filtersState, price, page: '1' };
    setFiltersState(nextFilters);
    await loadPage(nextFilters, 1);
  };

  const handleLoadMore = async () => {
    if (loading || !hasMore) return;
    await loadPage({ ...filtersState, page: String(pageMeta.page + 1) }, pageMeta.page + 1, true);
  };

  return (
    <>
      <NavBar user={user} />
      <main className="container mobile-materials-page">
        <section className="mobile-library-hero">
          <span className="mobile-library-hero__eyebrow">Materials</span>
          <h1>资料库</h1>
          <p>搜索课程、老师、知识点或资料类型，快速找到适合你的学习资料。</p>
          <form className="mobile-library-search" onSubmit={applyFilters}>
            <input
              value={filtersState.keyword}
              onChange={(event) => updateFilter('keyword', event.target.value)}
              placeholder="搜课程 / 资料名 / 标签"
              aria-label="搜索资料"
            />
            <button className="button primary" type="submit" disabled={loading}>
              搜索
            </button>
          </form>
          <div className="mobile-library-actions">
            <button type="button" className="button ghost" onClick={() => setDrawerOpen(true)}>
              更多筛选{activeFilterCount > 0 ? ` · ${activeFilterCount}` : ''}
            </button>
            <Link className="button ghost" href="/requests/new" prefetch={false}>
              找不到？发求购
            </Link>
          </div>
        </section>

        {stats && (
          <section className="mobile-stat-grid" aria-label="资料库概览">
            <div>
              <span>已上架</span>
              <strong>{formatNumber(stats.totalMaterials)}</strong>
            </div>
            <div>
              <span>免费资料</span>
              <strong>{formatNumber(stats.freeMaterials)}</strong>
            </div>
            <div>
              <span>下载次数</span>
              <strong>{formatNumber(stats.totalDownloads)}</strong>
            </div>
            <div>
              <span>用户个数</span>
              <strong>{formatNumber(stats.userCount)}</strong>
            </div>
          </section>
        )}

        <section className="mobile-filter-strip" aria-label="快捷筛选">
          <button
            type="button"
            className={`mobile-filter-chip${!filtersState.price ? ' is-active' : ''}`}
            onClick={() => handlePrice('')}
          >
            全部
          </button>
          <button
            type="button"
            className={`mobile-filter-chip${filtersState.price === 'free' ? ' is-active' : ''}`}
            onClick={() => handlePrice('free')}
          >
            免费
          </button>
          <button
            type="button"
            className={`mobile-filter-chip${filtersState.price === 'paid' ? ' is-active' : ''}`}
            onClick={() => handlePrice('paid')}
          >
            付费
          </button>
          {quickTags.map((tag) => (
            <button
              key={tag}
              type="button"
              className={`mobile-filter-chip${filtersState.tag === tag ? ' is-active' : ''}`}
              onClick={() => handleQuickTag(tag)}
            >
              #{tag}
            </button>
          ))}
        </section>

        <section className="card mobile-library-list">
          <div className="mobile-library-list__header">
            <div>
              <h2>全部资料</h2>
              <p>共 {pageMeta.total} 条结果，当前显示 {materialList.length} 条。</p>
            </div>
            <MaterialSortSelect
              value={filtersState.sort || 'latest'}
              disabled={loading}
              onChange={async (value) => {
                const nextFilters = { ...filtersState, sort: normalizeMaterialSort(value), page: '1' };
                setFiltersState(nextFilters);
                await loadPage(nextFilters, 1);
              }}
            />
          </div>
          {error && <p className="error-text">{error}</p>}
          {materialList.length === 0 ? (
            <div className="empty-state">暂无符合筛选条件的资料。</div>
          ) : (
            <ul className="materials-list mobile-resource-list">
              {materialList.map((item) => (
                <MaterialCard key={item.id} material={item} />
              ))}
            </ul>
          )}
          <div className="mobile-load-more">
            {hasMore ? (
              <button className="button primary" type="button" onClick={handleLoadMore} disabled={loading}>
                {loading ? '加载中...' : '加载更多'}
              </button>
            ) : (
              <span>已显示全部资料</span>
            )}
          </div>
        </section>
      </main>
      <MobileFilterDrawer
        open={drawerOpen}
        filters={filtersState}
        availableTagOptions={availableTags}
        onChange={updateFilter}
        onClose={() => setDrawerOpen(false)}
        onReset={resetFilters}
        onApply={() => {
          void applyFilters();
        }}
      />
    </>
  );
}

export const getServerSideProps: GetServerSideProps<MaterialsPageProps> = async (ctx) => {
  const session = readSession(ctx.req);
  const rawSchool = sanitizeFilter(ctx.query.school);
  const rawCollege = sanitizeFilter(ctx.query.college);
  const rawMajor = sanitizeFilter(ctx.query.major);
  const filters: MobileMaterialFilterState = {
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
  let materials: MaterialListItem[] = [];
  let meta: PaginationMeta = { page: Number(filters.page) || 1, size: MATERIALS_PAGE_SIZE, total: 0 };
  let stats: MaterialListStats | null = null;
  let tagOptions: string[] = [];
  try {
    const data = await fetchMaterials(toMaterialQuery(filters), session.token || undefined, getRequestOrigin(ctx.req));
    materials = data.items;
    meta = normalizeLoadedMeta(data.meta);
    stats = data.stats || null;
    tagOptions = data.availableTags || [];
  } catch (error) {
    // eslint-disable-next-line no-console
    console.warn('Failed to fetch materials page', error);
  }
  return {
    props: {
      user: session.user,
      materials,
      meta,
      filters,
      stats,
      tagOptions,
    },
  };
};
