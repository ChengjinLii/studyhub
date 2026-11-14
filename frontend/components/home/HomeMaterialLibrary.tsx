import { RefObject } from 'react';
import { MaterialListItem, PaginationMeta } from '../../types/material';
import { MaterialBrowseMode, MaterialSubjectScope, useMaterialSubjects } from '../../lib/useMaterialSubjects';
import MaterialCard from '../MaterialCard';
import MaterialBrowseToggle from '../materials/MaterialBrowseToggle';
import MaterialSearchEmpty from '../materials/MaterialSearchEmpty';
import MaterialSortSelect from '../materials/MaterialSortSelect';
import MaterialSubjectBrowser from '../materials/MaterialSubjectBrowser';
import MaterialSubjectFolders from '../materials/MaterialSubjectFolders';
import subjectStyles from '../../styles/MaterialSubjects.module.css';
import minStyles from '../../styles/HomeMinimal.module.css';

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
  subjectScope: MaterialSubjectScope;
  onSubjectChange: (id: string | null) => void;
  onSubjectPageChange: (page: number) => void;
  selectedIds: number[];
  selectedCount?: number;
  batchInfo?: string;
  batchError?: string;
  onBatchShare?: () => void;
  onClearSelection?: () => void;
  onToggle: (id: number) => void;
  onReset: () => void;
  onEditKeyword: () => void;
}

export default function HomeMaterialLibrary(props: Props) {
  const { meta, mode, materials, subjects, selectedIds } = props;
  const subjectFolders = props.subjectScope === 'all' ? subjects.catalogueFolders : subjects.allFolders;
  const overviewFolders = props.subjectScope === 'all' ? subjects.catalogueFolders : subjects.folders;
  const openFolder = subjectFolders.find((folder) => folder.id === props.subjectId);
  const browsingFolder = Boolean(openFolder);
  const pageSize = meta.size || 24;
  const totalPages = Math.max(1, Math.ceil(meta.total / pageSize));
  const selectedCount = props.selectedCount ?? selectedIds.length;

  const renderMaterial = (item: MaterialListItem) => (
    <MaterialCard
      key={item.id}
      material={item}
      variant="minimal"
      selectable
      checked={selectedIds.includes(item.id)}
      onToggle={props.onToggle}
    />
  );

  return (
    <section
      className={`materials-library-card ${minStyles.librarySection}`}
      id="materials-list"
      ref={props.materialsRef}
    >
      <div className={minStyles.libraryHeader}>
        <div className={minStyles.librarySummary}>
          <h2 className={minStyles.libraryTitle}>资料列表</h2>
          <p className={minStyles.librarySub}>
            {openFolder
              ? `${openFolder.name} · ${openFolder.materials.length} 份资料`
              : mode === 'materials'
                ? `共 ${meta.total} 份资料 · 第 ${meta.page} / ${totalPages} 页`
                : `${overviewFolders.length} 个学科 · ${overviewFolders.reduce((count, folder) => count + folder.materials.length, 0)} 份资料 · 整理于 ${subjects.updatedAt.slice(0, 10)}`}
          </p>
          {props.subjectScope !== 'all' && props.keyword.trim() ? (
            <p className={minStyles.searchContext}>
              当前搜索：<strong>{props.keyword.trim()}</strong>
            </p>
          ) : null}
        </div>
        <div className={minStyles.libraryActions}>
          <MaterialBrowseToggle value={mode} onChange={props.onModeChange} variant="minimal" />
          <MaterialSortSelect value={props.sort} disabled={props.loading} onChange={props.onSortChange} />
        </div>
      </div>

      {props.error ? <p className="error-text">{props.error}</p> : null}
      {props.notice && !props.error ? <p className="help-text">{props.notice}</p> : null}

      {mode === 'subjects' || browsingFolder ? (
        <MaterialSubjectBrowser
          folders={browsingFolder ? subjectFolders : overviewFolders}
          subjectId={props.subjectId}
          page={props.subjectPage}
          backLabel={mode === 'materials' ? '返回搜索结果' : '全部学科'}
          onSubjectChange={props.onSubjectChange}
          onPageChange={props.onSubjectPageChange}
          gridClassName={`materials-list ${minStyles.minimalList}`}
          renderMaterial={renderMaterial}
        />
      ) : (
        <>
          {subjects.relatedFolders.length > 0 ? (
            <section className={subjectStyles.searchFolders} aria-label="相关学科">
              <h3>
                相关学科 <span>{subjects.relatedFolders.length}</span>
              </h3>
              <MaterialSubjectFolders
                folders={subjects.relatedFolders}
                onOpen={props.onSubjectChange}
                label="相关学科文件夹"
              />
            </section>
          ) : null}

          {!materials.length ? (
            <MaterialSearchEmpty onReset={props.onReset} onEditKeyword={props.onEditKeyword} />
          ) : (
            <ul className={`materials-list ${minStyles.minimalList}`}>{materials.map(renderMaterial)}</ul>
          )}

          <div className={minStyles.libraryFooter}>
            <div className={minStyles.batchInline}>
              <span>已选择 {selectedCount} 条资料。</span>
              {props.onBatchShare ? (
                <button
                  type="button"
                  className={minStyles.ghostPillBtn}
                  onClick={props.onBatchShare}
                  disabled={selectedCount === 0}
                >
                  批量分享
                </button>
              ) : null}
              {props.onClearSelection ? (
                <button
                  type="button"
                  className={minStyles.plainTextBtn}
                  onClick={props.onClearSelection}
                  disabled={selectedCount === 0}
                >
                  清空
                </button>
              ) : null}
              {props.batchInfo ? <span className={minStyles.batchStatusOk}>{props.batchInfo}</span> : null}
              {props.batchError ? <span className={minStyles.batchStatusErr}>{props.batchError}</span> : null}
            </div>

            {meta.total > 0 ? (
              <nav className={minStyles.pageNav} aria-label="分页">
                <button
                  type="button"
                  className={minStyles.ghostPillBtn}
                  disabled={props.loading || meta.page <= 1}
                  onClick={() => props.onPageChange(meta.page - 1)}
                  aria-label="上一页"
                >
                  上一页
                </button>
                <button
                  type="button"
                  className={minStyles.solidPillBtn}
                  disabled={props.loading || meta.page >= totalPages}
                  onClick={() => props.onPageChange(meta.page + 1)}
                  aria-label="下一页"
                >
                  下一页
                </button>
              </nav>
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}
