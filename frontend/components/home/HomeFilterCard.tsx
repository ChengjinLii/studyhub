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
            资料搜索
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
                placeholder="课程名 / 知识点 / 资料类型"
              />
            </div>
            <p className="help-text">多个关键词可以用空格分开。</p>
          </div>
          <div className="filter-actions quick">
            <button type="button" className="button ghost small" onClick={onToggleAdvancedFilters} aria-expanded={showAdvanced}>
              {showAdvanced ? '收起高级筛选' : '更多筛选'}
            </button>
            <button className="button primary" type="submit">
              搜索
            </button>
          </div>
        </div>
        <div className={`filter-advanced ${showAdvanced ? 'open' : ''}`}>
          <div className="filter-advanced__header">
            <div>
              <strong>高级筛选</strong>
              <span>按学校、专业和资料属性缩小结果范围</span>
            </div>
            <button type="button" className="button ghost small filter-advanced__reset" onClick={onResetFilters}>
              重置条件
            </button>
          </div>
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
          </div>
          <div className="filter-advanced__choices">
            <fieldset className="form-item course-type-advanced">
              <legend>课程类型</legend>
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
            </fieldset>
            <fieldset className="form-item price-group">
              <legend>价格</legend>
              <div className="choice-group">
                <label className={`choice-pill price-choice ${!filtersState.price || filtersState.price === 'all' ? 'active' : ''}`}>
                  <input
                    type="radio"
                    name="price"
                    value=""
                    checked={!filtersState.price || filtersState.price === 'all'}
                    onChange={(event) => onFilterChange('price', event.target.value)}
                  />
                  全部
                </label>
                <label className={`choice-pill price-choice ${filtersState.price === 'free' ? 'active' : ''}`}>
                  <input
                    type="radio"
                    name="price"
                    value="free"
                    checked={filtersState.price === 'free'}
                    onChange={(event) => onFilterChange('price', event.target.value)}
                  />
                  免费
                </label>
                <label className={`choice-pill price-choice ${filtersState.price === 'paid' ? 'active' : ''}`}>
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
            </fieldset>
          </div>
        </div>
      </form>
    </section>
  );
}
