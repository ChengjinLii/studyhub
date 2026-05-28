import { FormEvent, RefObject } from 'react';
import {
  SUPPORTED_SCHOOL,
  SUPPORTED_COLLEGES,
  SUPPORTED_MAJORS,
  COURSE_CATEGORY_OPTIONS,
  GRADE_STAGE_OPTIONS,
} from '../../constants/metadata';

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

interface HomeFilterCardProps {
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
  return (
    <section className="card filter-card" ref={filterRef}>
      <div className="filter-header">
        <div>
          <h2 className="card-title">
            筛选资料
            <svg className="title-icon" viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="1.6" />
              <path d="M20 20l-3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </h2>
        </div>
      </div>
      <form className="filter-form compact" onSubmit={onSubmit}>
        <div className="filter-quick-row">
          <div className="form-item filter-keyword">
            <label htmlFor="keyword">关键词</label>
            <div className="filter-keyword__input">
              <input
                id="keyword"
                name="keyword"
                value={filtersState.keyword}
                onChange={(event) => onFilterChange('keyword', event.target.value)}
                placeholder="课程名 / 知识点 / 讲义"
              />
            </div>
          </div>
          <div className="filter-actions quick">
            <button type="button" className="button ghost small" onClick={onToggleAdvancedFilters} aria-expanded={showAdvanced}>
              {showAdvanced ? '收起高级筛选' : '更多筛选'}
            </button>
            <button className="button primary" type="submit">
              应用筛选
            </button>
          </div>
        </div>
        <div className={`filter-advanced ${showAdvanced ? 'open' : ''}`}>
          <div className="advanced-grid">
            <div className="form-item">
              <label htmlFor="school">学校</label>
              <select id="school" name="school" value={filtersState.school} onChange={(event) => onFilterChange('school', event.target.value)}>
                <option value="">全部</option>
                <option value={SUPPORTED_SCHOOL}>{SUPPORTED_SCHOOL}</option>
              </select>
            </div>
            <div className="form-item">
              <label htmlFor="college">学院</label>
              <select id="college" name="college" value={filtersState.college} onChange={(event) => onFilterChange('college', event.target.value)}>
                <option value="">全部</option>
                {SUPPORTED_COLLEGES.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-item">
              <label htmlFor="major">专业</label>
              <select id="major" name="major" value={filtersState.major} onChange={(event) => onFilterChange('major', event.target.value)}>
                <option value="">全部</option>
                {SUPPORTED_MAJORS.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-item">
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
            <div className="form-item">
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
              {!availableTagOptions.length && <p className="help-text">暂无热门标签，等待更多投稿。</p>}
            </div>
            <div
              className="form-item full price-sort-row"
              style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', alignItems: 'center', gap: 12 }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
                <div className="form-item price-group" style={{ margin: 0 }}>
                  <label>价格</label>
                  <div className="choice-group">
                    <label className="choice">
                      <input
                        type="radio"
                        name="price"
                        value=""
                        checked={!filtersState.price || filtersState.price === 'all'}
                        onChange={(event) => onFilterChange('price', event.target.value)}
                      />
                      全部
                    </label>
                    <label className="choice">
                      <input
                        type="radio"
                        name="price"
                        value="free"
                        checked={filtersState.price === 'free'}
                        onChange={(event) => onFilterChange('price', event.target.value)}
                      />
                      免费
                    </label>
                    <label className="choice">
                      <input
                        type="radio"
                        name="price"
                        value="paid"
                        checked={filtersState.price === 'paid'}
                        onChange={(event) => onFilterChange('price', event.target.value)}
                      />
                      付费
                    </label>
                  </div>
                </div>
                <div className="form-item sort-group" style={{ margin: 0 }}>
                  <label htmlFor="sort">排序</label>
                  <select
                    id="sort"
                    name="sort"
                    value={filtersState.sort || 'latest'}
                    onChange={(event) => onFilterChange('sort', event.target.value)}
                    style={{ minWidth: 160 }}
                  >
                    <option value="latest">默认（综合）</option>
                    <option value="price">价格</option>
                    <option value="sales">销量</option>
                  </select>
                </div>
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button type="button" className="button primary" onClick={onResetFilters} style={{ minWidth: 100 }}>
                  重置筛选
                </button>
              </div>
            </div>
          </div>
          <div className="form-item full course-type-advanced">
            <label>课程类型</label>
            <div className="course-type-options compact">
              <label className={`choice-pill ${!filtersState.courseCategory ? 'active' : ''}`}>
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
                <label key={option.value} className={`choice-pill ${filtersState.courseCategory === option.value ? 'active' : ''}`}>
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
            </div>
          </div>
        </div>
      </form>
    </section>
  );
}
