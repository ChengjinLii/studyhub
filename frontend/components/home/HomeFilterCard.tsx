import Link from 'next/link';
import { FormEvent, RefObject } from 'react';
import {
  SUPPORTED_SCHOOL,
  COURSE_CATEGORY_OPTIONS,
  GRADE_STAGE_OPTIONS,
  getCollegeOptions,
  getMajorOptionsForCollege,
} from '../../constants/metadata';
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
            width="18"
            height="18"
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
          <button
            type="button"
            className={`${minStyles.filterTrigger}${showAdvanced || activeFilterCount > 0 ? ` ${minStyles.filterTriggerActive}` : ''}`}
            onClick={onToggleAdvancedFilters}
            aria-expanded={showAdvanced}
            aria-label={
              activeFilterCount > 0
                ? `${advancedActionLabel}，已启用 ${activeFilterCount} 项条件`
                : advancedActionLabel
            }
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <path d="M4 7h16M7 12h10M10 17h4" />
            </svg>
            <span>高级筛选</span>
            {activeFilterCount > 0 ? (
              <span className={minStyles.filterCountBadge} aria-hidden="true">
                {activeFilterCount}
              </span>
            ) : null}
          </button>
          {/* The search button closes the box, at the right of the filter trigger. */}
          <button className={minStyles.searchGo} type="submit" aria-label="搜索资料">
            <span>搜索</span>
            <svg
              className={minStyles.searchGoArrow}
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </button>
        </div>

        {/* The filters open over the content below the box, so the first screen keeps its layout. */}
        {showAdvanced ? (
          <div className={minStyles.advancedPanel}>
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
              <fieldset className={minStyles.choiceFieldset}>
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
                  全部
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
                    {option.label}
                  </label>
                ))}
              </fieldset>
            </div>

            <div className={minStyles.choiceRow}>
              <fieldset className={minStyles.choiceFieldset}>
                <legend className={minStyles.choiceLegend}>价格</legend>
                <label
                  className={`${minStyles.choicePill}${!filtersState.price || filtersState.price === 'all' ? ` ${minStyles.choicePillActive}` : ''}`}
                >
                  <input
                    type="radio"
                    name="price"
                    value=""
                    checked={!filtersState.price || filtersState.price === 'all'}
                    onChange={(event) => onFilterChange('price', event.target.value)}
                  />
                  全部
                </label>
                <label
                  className={`${minStyles.choicePill}${filtersState.price === 'free' ? ` ${minStyles.choicePillActive}` : ''}`}
                >
                  <input
                    type="radio"
                    name="price"
                    value="free"
                    checked={filtersState.price === 'free'}
                    onChange={(event) => onFilterChange('price', event.target.value)}
                  />
                  免费
                </label>
                <label
                  className={`${minStyles.choicePill}${filtersState.price === 'paid' ? ` ${minStyles.choicePillActive}` : ''}`}
                >
                  <input
                    type="radio"
                    name="price"
                    value="paid"
                    checked={filtersState.price === 'paid'}
                    onChange={(event) => onFilterChange('price', event.target.value)}
                  />
                  付费
                </label>
              </fieldset>

              <button type="button" className={minStyles.resetLink} onClick={onResetFilters}>
                重置条件
              </button>
            </div>
          </div>
        ) : null}

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
