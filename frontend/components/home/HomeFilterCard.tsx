import Link from 'next/link';
import { FormEvent, ReactNode, RefObject, useLayoutEffect, useRef } from 'react';
import {
  SUPPORTED_SCHOOL,
  COURSE_CATEGORY_OPTIONS,
  GRADE_STAGE_OPTIONS,
  getCollegeOptions,
  getMajorOptionsForCollege,
} from '../../constants/metadata';
import {
  animate,
  AnimatePresence,
  APPLE_SPRINGS,
  APPLE_TAP,
  m,
  SegmentedPill,
  usePresence,
  useReducedMotion,
} from '../../lib/motion';
import minStyles from '../../styles/HomeMinimal.module.css';

export interface HomeFilterState {
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

export interface HomeOverviewStat {
  label: string;
  value: string;
}

interface HomeFilterCardProps {
  className?: string;
  filterRef: RefObject<HTMLDivElement>;
  filtersState: HomeFilterState;
  showAdvanced: boolean;
  availableTagOptions: string[];
  onFilterChange: (key: keyof HomeFilterState, value: string) => void;
  onCourseCategoryChange: (value: string | null) => void;
  onToggleAdvancedFilters: () => void;
  onResetFilters: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}

interface PopoverOrigin {
  dx: number;
  dy: number;
  sx: number;
  sy: number;
  restRadius: string;
}

const DEFAULT_ORIGIN: PopoverOrigin = {
  dx: 160,
  dy: -190,
  sx: 0.14,
  sy: 0.18,
  restRadius: '22px',
};

function AdvancedFilterPopover({
  triggerRef,
  children,
}: {
  triggerRef: RefObject<HTMLButtonElement>;
  children: ReactNode;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const originRef = useRef<PopoverOrigin>(DEFAULT_ORIGIN);
  const animsRef = useRef<Array<{ stop: () => void }>>([]);
  const [isPresent, safeToRemove] = usePresence();
  const prefersReducedMotion = useReducedMotion();

  useLayoutEffect(() => {
    const card = cardRef.current;
    const content = contentRef.current;
    if (!card || !content) return;

    const stopAll = () => {
      animsRef.current.forEach((ctrl) => ctrl.stop());
      animsRef.current = [];
    };

    const measureOrigin = (): PopoverOrigin => {
      const trigger = triggerRef.current;
      if (!trigger) return originRef.current;
      const prevTransform = card.style.transform;
      card.style.transform = '';
      const panelRect = card.getBoundingClientRect();
      const triggerRect = trigger.getBoundingClientRect();
      const restRadius = window.getComputedStyle(card).borderRadius || '22px';
      card.style.transform = prevTransform;
      if (!panelRect.width || !panelRect.height || !triggerRect.width || !triggerRect.height) {
        return originRef.current;
      }
      const dx =
        triggerRect.left + triggerRect.width / 2 - (panelRect.left + panelRect.width / 2);
      const dy =
        triggerRect.top + triggerRect.height / 2 - (panelRect.top + panelRect.height / 2);
      const sx = Math.min(0.45, Math.max(0.08, triggerRect.width / panelRect.width));
      const sy = Math.min(0.45, Math.max(0.12, triggerRect.height / panelRect.height));
      return { dx, dy, sx, sy, restRadius };
    };

    stopAll();

    if (prefersReducedMotion) {
      if (isPresent) {
        card.style.opacity = '1';
        card.style.transform = '';
        content.style.opacity = '1';
        content.style.transform = '';
      } else {
        safeToRemove();
      }
      return stopAll;
    }

    if (isPresent) {
      const origin = measureOrigin();
      originRef.current = origin;
      const { dx, dy, sx, sy, restRadius } = origin;

      const cardCtrl = animate(
        card,
        {
          x: [dx, dx * 0.36, -dx * 0.025, dx * 0.008, 0],
          y: [dy, dy * 0.24, 6, -2, 0],
          scaleX: [sx, sx + (1 - sx) * 0.42, 1.022, 0.994, 1],
          scaleY: [sy, sy + (1 - sy) * 0.6, 1.032, 0.992, 1],
          opacity: [0, 1, 1, 1, 1],
          borderRadius: ['999px', '42px', restRadius, restRadius, restRadius],
        },
        {
          duration: 0.52,
          times: [0, 0.16, 0.56, 0.8, 1],
          ease: [
            [0.2, 0.9, 0.3, 1],
            [0.16, 1, 0.3, 1],
            [0.33, 1, 0.68, 1],
            [0.22, 1, 0.36, 1],
          ],
          onComplete: () => {
            card.style.transform = '';
            card.style.opacity = '1';
            card.style.borderRadius = '';
          },
        }
      );

      const contentCtrl = animate(
        content,
        {
          opacity: [0, 0, 1, 1],
          y: [-6, -6, 1, 0],
          scale: [0.96, 0.96, 1.004, 1],
        },
        {
          duration: 0.44,
          times: [0, 0.22, 0.68, 1],
          ease: ['linear', [0.16, 1, 0.3, 1], [0.22, 1, 0.36, 1]],
          onComplete: () => {
            content.style.transform = '';
            content.style.opacity = '1';
          },
        }
      );

      animsRef.current = [cardCtrl, contentCtrl];
    } else {
      const origin = measureOrigin();
      originRef.current = origin;
      const { dx, dy, sx, sy, restRadius } = origin;

      const contentExitCtrl = animate(
        content,
        { opacity: 0, y: -4, scale: 0.96 },
        { duration: 0.1, ease: [0.4, 0, 1, 1] }
      );

      const cardExitCtrl = animate(
        card,
        {
          x: [0, dx * 0.26, dx],
          y: [0, dy * 0.2, dy],
          scaleX: [1, 1 - (1 - sx) * 0.35, sx],
          scaleY: [1, 1 - (1 - sy) * 0.24, sy],
          opacity: [1, 0.94, 0],
          borderRadius: [restRadius, '40px', '999px'],
        },
        {
          duration: 0.26,
          times: [0, 0.38, 1],
          ease: [
            [0.4, 0, 1, 1],
            [0.22, 1, 0.36, 1],
          ],
          onComplete: () => {
            safeToRemove();
          },
        }
      );

      animsRef.current = [contentExitCtrl, cardExitCtrl];
    }

    return stopAll;
  }, [isPresent, prefersReducedMotion, safeToRemove, triggerRef]);

  return (
    <div className={minStyles.advancedPanel}>
      <div
        ref={cardRef}
        className={minStyles.advancedPanelCard}
        style={{ opacity: prefersReducedMotion ? 1 : 0 }}
      >
        <div ref={contentRef} className={minStyles.advancedPanelContent}>
          {children}
        </div>
      </div>
    </div>
  );
}

export default function HomeFilterCard({
  className,
  filterRef,
  filtersState,
  showAdvanced,
  availableTagOptions,
  onFilterChange,
  onCourseCategoryChange,
  onToggleAdvancedFilters,
  onResetFilters,
  onSubmit,
}: HomeFilterCardProps) {
  const filterTriggerRef = useRef<HTMLButtonElement>(null);
  const collegeOptions = getCollegeOptions(filtersState.college);
  const majorOptions = getMajorOptionsForCollege(filtersState.college, filtersState.major);
  const activeFilterCount = [
    filtersState.school,
    filtersState.college,
    filtersState.major,
    filtersState.tag,
    filtersState.gradeValue,
    filtersState.courseCategory,
    filtersState.price && filtersState.price !== 'all' ? filtersState.price : '',
  ].filter(Boolean).length;
  const hasKeyword = filtersState.keyword.trim().length > 0;

  const advancedActionLabel = showAdvanced ? '收起高级筛选' : '高级筛选';

  return (
    <section
      className={`${minStyles.searchSection}${className ? ` ${className}` : ''}`}
      aria-label="资料搜索"
      ref={filterRef}
    >
      <form className={minStyles.searchForm} onSubmit={onSubmit} role="search">
        {/* StudyHub bot rests at the left of this box by default. */}
        <div className={minStyles.searchPill} data-search-pill="">
          <svg
            className={minStyles.searchIcon}
            width="21"
            height="21"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-3.5-3.5" />
          </svg>
          <label className={minStyles.srOnly} htmlFor="keyword">
            关键词
          </label>
          <input
            className={minStyles.searchInput}
            id="keyword"
            name="keyword"
            value={filtersState.keyword}
            onChange={(event) => onFilterChange('keyword', event.target.value)}
            placeholder="课程名 / 知识点 / 资料类型"
          />
          <m.button
            ref={filterTriggerRef}
            type="button"
            className={`${minStyles.filterTrigger}${showAdvanced || activeFilterCount > 0 ? ` ${minStyles.filterTriggerActive}` : ''}`}
            onClick={onToggleAdvancedFilters}
            whileTap={APPLE_TAP.button}
            transition={APPLE_SPRINGS.snappy}
            aria-expanded={showAdvanced}
            aria-label={
              activeFilterCount > 0
                ? `${advancedActionLabel}，已启用 ${activeFilterCount} 项条件`
                : advancedActionLabel
            }
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.85" strokeLinecap="round" aria-hidden="true">
              <path d="M4 7h16M7 12h10M10 17h4" />
            </svg>
            <span>高级筛选</span>
            {activeFilterCount > 0 ? (
              <m.span
                key={activeFilterCount}
                className={minStyles.filterCountBadge}
                initial={{ scale: 0.7, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={APPLE_SPRINGS.bouncy}
                aria-hidden="true"
              >
                {activeFilterCount}
              </m.span>
            ) : null}
          </m.button>
          {/* The search button closes the box, at the right of the filter trigger. */}
          <button
            className={`${minStyles.searchGo}${hasKeyword ? ` ${minStyles.searchGoReady}` : ''}`}
            type="submit"
            aria-label="搜索资料"
            title="搜索资料"
          >
            <span className={minStyles.searchGoAura} aria-hidden="true" />
            <span className={minStyles.searchGoRing} aria-hidden="true">
              <span className={minStyles.searchGoSheen} />
            </span>
            <span className={minStyles.searchGoGlass} aria-hidden="true" />
            <span className={minStyles.searchGoIconTrack} aria-hidden="true">
              <svg
                className={`${minStyles.searchGoArrow} ${minStyles.searchGoArrowPrimary}`}
                width="16"
                height="16"
                viewBox="0 0 20 20"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M4.25 10h11.5M10.75 5l5 5-5 5" />
              </svg>
              <svg
                className={`${minStyles.searchGoArrow} ${minStyles.searchGoArrowClone}`}
                width="16"
                height="16"
                viewBox="0 0 20 20"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M4.25 10h11.5M10.75 5l5 5-5 5" />
              </svg>
            </span>
          </button>
        </div>

        {/* The filters open over the content below the box, so the first screen keeps its layout. */}
        <AnimatePresence initial={false}>
        {showAdvanced ? (
          <AdvancedFilterPopover key="home-advanced-filter-panel" triggerRef={filterTriggerRef}>
            <div className={minStyles.advancedSelects}>
              <div className={minStyles.selectField}>
                <label htmlFor="school">学校</label>
                <select
                  id="school"
                  name="school"
                  value={filtersState.school}
                  onChange={(event) => onFilterChange('school', event.target.value)}
                >
                  <option value="">全部</option>
                  <option value={SUPPORTED_SCHOOL}>{SUPPORTED_SCHOOL}</option>
                </select>
              </div>
              <div className={minStyles.selectField}>
                <label htmlFor="college">学院</label>
                <select
                  id="college"
                  name="college"
                  value={filtersState.college}
                  onChange={(event) => {
                    const nextCollege = event.target.value;
                    onFilterChange('college', nextCollege);
                    if (filtersState.major && !getMajorOptionsForCollege(nextCollege).includes(filtersState.major)) {
                      onFilterChange('major', '');
                    }
                  }}
                >
                  <option value="">全部</option>
                  {collegeOptions.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
              <div className={minStyles.selectField}>
                <label htmlFor="major">专业</label>
                <select
                  id="major"
                  name="major"
                  value={filtersState.major}
                  onChange={(event) => onFilterChange('major', event.target.value)}
                >
                  <option value="">全部</option>
                  {majorOptions.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
              <div className={minStyles.selectField}>
                <label htmlFor="gradeValue">年级</label>
                <select
                  id="gradeValue"
                  name="gradeValue"
                  value={filtersState.gradeValue}
                  onChange={(event) => onFilterChange('gradeValue', event.target.value)}
                >
                  <option value="">全部</option>
                  {GRADE_STAGE_OPTIONS.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </div>
              <div className={minStyles.selectField}>
                <label htmlFor="tag">标签</label>
                <select
                  id="tag"
                  name="tag"
                  value={filtersState.tag}
                  onChange={(event) => onFilterChange('tag', event.target.value)}
                  disabled={!availableTagOptions.length}
                >
                  <option value="">全部</option>
                  {availableTagOptions.map((tag) => (
                    <option key={tag} value={tag}>
                      #{tag}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className={minStyles.choiceRow}>
              <fieldset className={minStyles.choiceFieldset} data-motion-pills="true">
                <legend className={minStyles.choiceLegend}>课程类型</legend>
                <label
                  className={`${minStyles.choicePill}${!filtersState.courseCategory ? ` ${minStyles.choicePillActive}` : ''}`}
                >
                  <input
                    type="radio"
                    name="courseCategory"
                    value=""
                    checked={!filtersState.courseCategory}
                    onChange={() => onCourseCategoryChange(null)}
                  />
                  {!filtersState.courseCategory ? (
                    <SegmentedPill layoutId="home-filter-course-pill" className={minStyles.choicePillHighlight} />
                  ) : null}
                  <span className={minStyles.choicePillText}>全部</span>
                </label>
                {COURSE_CATEGORY_OPTIONS.map((option) => (
                  <label
                    key={option.value}
                    className={`${minStyles.choicePill}${filtersState.courseCategory === option.value ? ` ${minStyles.choicePillActive}` : ''}`}
                  >
                    <input
                      type="radio"
                      name="courseCategory"
                      value={option.value}
                      checked={filtersState.courseCategory === option.value}
                      onChange={() => onCourseCategoryChange(option.value)}
                    />
                    {filtersState.courseCategory === option.value ? (
                      <SegmentedPill layoutId="home-filter-course-pill" className={minStyles.choicePillHighlight} />
                    ) : null}
                    <span className={minStyles.choicePillText}>{option.label}</span>
                  </label>
                ))}
              </fieldset>
            </div>

            <div className={minStyles.choiceRow}>
              <fieldset className={minStyles.choiceFieldset} data-motion-pills="true">
                <legend className={minStyles.choiceLegend}>价格</legend>
                {[
                  { value: '', label: '全部', active: !filtersState.price || filtersState.price === 'all' },
                  { value: 'free', label: '免费', active: filtersState.price === 'free' },
                  { value: 'paid', label: '付费', active: filtersState.price === 'paid' },
                ].map((priceOption) => (
                  <label
                    key={priceOption.value || 'all'}
                    className={`${minStyles.choicePill}${priceOption.active ? ` ${minStyles.choicePillActive}` : ''}`}
                  >
                    <input
                      type="radio"
                      name="price"
                      value={priceOption.value}
                      checked={priceOption.active}
                      onChange={(event) => onFilterChange('price', event.target.value)}
                    />
                    {priceOption.active ? (
                      <SegmentedPill layoutId="home-filter-price-pill" className={minStyles.choicePillHighlight} />
                    ) : null}
                    <span className={minStyles.choicePillText}>{priceOption.label}</span>
                  </label>
                ))}
              </fieldset>

              <button type="button" className={minStyles.resetLink} onClick={onResetFilters}>
                重置条件
              </button>
            </div>
          </AdvancedFilterPopover>
        ) : null}
        </AnimatePresence>

        <div className={minStyles.searchActions}>
          <Link className={minStyles.searchAction} href="/join" prefetch={false}>
            关于我们
          </Link>
          <Link className={minStyles.searchAction} href="/upload" prefetch={false}>
            我要投稿
          </Link>
        </div>
      </form>
    </section>
  );
}