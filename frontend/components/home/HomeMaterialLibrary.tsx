import { RefObject } from 'react';
import { MaterialListItem, PaginationMeta } from '../../types/material';
import { MaterialBrowseMode, useMaterialSubjects } from '../../lib/useMaterialSubjects';
import MaterialCard from '../MaterialCard';
import PaginationBar from '../PaginationBar';
import MaterialBrowseToggle from '../materials/MaterialBrowseToggle';
import MaterialSearchEmpty from '../materials/MaterialSearchEmpty';
import MaterialSortSelect from '../materials/MaterialSortSelect';
import MaterialSubjectBrowser from '../materials/MaterialSubjectBrowser';

interface Props {
  materialsRef: RefObject<HTMLDivElement>;
  materials: MaterialListItem[];
  meta: PaginationMeta;
  keyword: string;
  sort: string;
  loading: boolean;
  error: string;
  notice: string;
  mode: MaterialBrowseMode;
  onModeChange: (mode: MaterialBrowseMode) => void;
  onSortChange: (value: string) => void;
  onPageChange: (page: number) => void;
  subjects: ReturnType<typeof useMaterialSubjects>;
  subjectId: string | null;
  subjectPage: number;
  onSubjectChange: (id: string | null) => void;
  onSubjectPageChange: (page: number) => void;
  selectedIds: number[];
  onToggle: (id: number) => void;
  onReset: () => void;
  onEditKeyword: () => void;
}

export default function HomeMaterialLibrary(props: Props) {
  const { meta, mode, materials, subjects, selectedIds } = props;
  const pageSize = meta.size || 24;
  const totalPages = Math.max(1, Math.ceil(meta.total / pageSize));
  const renderMaterial = (item: MaterialListItem) => <MaterialCard
    key={item.id} material={item} selectable checked={selectedIds.includes(item.id)} onToggle={props.onToggle}
  />;
  return (
    <section className="card materials-library-card" id="materials-list" ref={props.materialsRef}>
      <div className="materials-header materials-library-header">
        <div className="materials-library-header__summary">
          <h2 className="card-title">
            资料列表
            <svg className="title-icon" viewBox="0 0 24 24" aria-hidden="true">
              <rect x="4" y="5" width="16" height="14" rx="2" fill="none" stroke="currentColor" strokeWidth="1.6" />
              <path d="M8 9h8M8 12h8M8 15h5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </h2>
          <p className="help-text">
            {mode === 'materials'
              ? `当前第 ${meta.page} / ${totalPages} 页 · 每页 ${pageSize} 条 · 共 ${meta.total} 条结果`
              : `${subjects.folders.length} 个学科 · ${subjects.items.length} 份资料 · 整理于 ${subjects.updatedAt.slice(0, 10)}`}
          </p>
          {props.keyword.trim() && <p className="materials-search-context">当前搜索：<strong>{props.keyword.trim()}</strong></p>}
        </div>
        <div className="materials-library-header__actions">
          <MaterialSortSelect value={props.sort} disabled={props.loading} onChange={props.onSortChange} />
          <MaterialBrowseToggle value={mode} onChange={props.onModeChange} />
        </div>
      </div>
      {mode === 'materials' && <PaginationBar
        currentPage={meta.page} totalItems={meta.total} pageSize={pageSize} loading={props.loading} onPageChange={props.onPageChange}
      />}
      {props.error && <p className="error-text">{props.error}</p>}
      {props.notice && !props.error && <p className="help-text">{props.notice}</p>}
      {mode === 'subjects' ? <MaterialSubjectBrowser
        folders={subjects.folders}
        subjectId={props.subjectId} page={props.subjectPage}
        onSubjectChange={props.onSubjectChange} onPageChange={props.onSubjectPageChange}
        gridClassName="materials-list materials-grid" renderMaterial={renderMaterial}
      /> : !materials.length ? <MaterialSearchEmpty onReset={props.onReset} onEditKeyword={props.onEditKeyword} /> : (
        <ul className="materials-list materials-grid">{materials.map(renderMaterial)}</ul>
      )}
    </section>
  );
}
