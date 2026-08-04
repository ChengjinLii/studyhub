import {
  COURSE_CATEGORY_OPTIONS,
  GRADE_STAGE_OPTIONS,
  SUPPORTED_COLLEGES,
  SUPPORTED_MAJORS,
  SUPPORTED_SCHOOL,
} from '../../constants/metadata';
import { MATERIAL_SORT_OPTIONS } from '../../constants/materialSort';

export interface MobileMaterialFilterState {
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

interface MobileFilterDrawerProps {
  open: boolean;
  filters: MobileMaterialFilterState;
  availableTagOptions: string[];
  onChange: (key: keyof MobileMaterialFilterState, value: string) => void;
  onClose: () => void;
  onReset: () => void;
  onApply: () => void;
}

const PRICE_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'free', label: '免费' },
  { value: 'paid', label: '付费' },
];

export default function MobileFilterDrawer({
  open,
  filters,
  availableTagOptions,
  onChange,
  onClose,
  onReset,
  onApply,
}: MobileFilterDrawerProps) {
  return (
    <div className={`mobile-filter-drawer${open ? ' is-open' : ''}`} aria-hidden={!open}>
      <button className="mobile-filter-drawer__mask" type="button" aria-label="关闭筛选" onClick={onClose} />
      <section className="mobile-filter-drawer__panel" role="dialog" aria-modal="true" aria-label="筛选资料">
        <div className="mobile-filter-drawer__header">
          <div>
            <span>Filter</span>
            <h2>筛选资料</h2>
          </div>
          <button type="button" className="mobile-filter-drawer__close" onClick={onClose} aria-label="关闭筛选">
            ×
          </button>
        </div>
        <div className="mobile-filter-drawer__body">
          <label className="form-item">
            <span>学校</span>
            <select value={filters.school} onChange={(event) => onChange('school', event.target.value)}>
              <option value="">全部</option>
              <option value={SUPPORTED_SCHOOL}>{SUPPORTED_SCHOOL}</option>
            </select>
          </label>
          <label className="form-item">
            <span>学院</span>
            <select value={filters.college} onChange={(event) => onChange('college', event.target.value)}>
              <option value="">全部</option>
              {SUPPORTED_COLLEGES.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="form-item">
            <span>专业</span>
            <select value={filters.major} onChange={(event) => onChange('major', event.target.value)}>
              <option value="">全部</option>
              {SUPPORTED_MAJORS.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="form-item">
            <span>年级</span>
            <select value={filters.gradeValue} onChange={(event) => onChange('gradeValue', event.target.value)}>
              <option value="">全部</option>
              {GRADE_STAGE_OPTIONS.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="form-item">
            <span>标签</span>
            <select value={filters.tag} onChange={(event) => onChange('tag', event.target.value)}>
              <option value="">全部</option>
              {availableTagOptions.map((name) => (
                <option key={name} value={name}>
                  #{name}
                </option>
              ))}
            </select>
          </label>
          <label className="form-item">
            <span>课程类型</span>
            <select value={filters.courseCategory} onChange={(event) => onChange('courseCategory', event.target.value)}>
              <option value="">全部</option>
              {COURSE_CATEGORY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <div className="mobile-filter-group">
            <span>价格</span>
            <div className="mobile-filter-chip-row">
              {PRICE_OPTIONS.map((option) => (
                <button
                  key={option.value || 'all'}
                  type="button"
                  className={`mobile-filter-chip${filters.price === option.value || (!filters.price && !option.value) ? ' is-active' : ''}`}
                  onClick={() => onChange('price', option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <label className="form-item">
            <span>排序</span>
            <select value={filters.sort || 'latest'} onChange={(event) => onChange('sort', event.target.value)}>
              {MATERIAL_SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="mobile-filter-drawer__footer">
          <button type="button" className="button ghost" onClick={onReset}>
            重置
          </button>
          <button type="button" className="button primary" onClick={onApply}>
            搜索
          </button>
        </div>
      </section>
    </div>
  );
}
