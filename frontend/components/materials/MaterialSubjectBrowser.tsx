import { ArrowLeft, ChevronRight } from 'lucide-react';
import { ReactNode, useRef } from 'react';
import type { MaterialSubjectFolder } from '../../lib/materialSubjects';
import type { MaterialListItem } from '../../types/material';
import PaginationBar from '../PaginationBar';
import MaterialSubjectFolders from './MaterialSubjectFolders';
import styles from '../../styles/MaterialSubjects.module.css';

export default function MaterialSubjectBrowser({
  folders, subjectId, page, onSubjectChange, onPageChange, renderMaterial, gridClassName, backLabel = '全部学科',
}: {
  folders: MaterialSubjectFolder[];
  subjectId: string | null;
  page: number;
  onSubjectChange: (id: string | null) => void;
  onPageChange: (page: number) => void;
  renderMaterial: (material: MaterialListItem) => ReactNode;
  gridClassName: string;
  backLabel?: string;
}) {
  const folder = folders.find((item) => item.id === subjectId);
  const topRef = useRef<HTMLDivElement>(null);
  const safePage = folder ? Math.min(page, Math.max(1, Math.ceil(folder.materials.length / 24))) : 1;
  if (!folders.length) return <p className={styles.loading}>暂无符合筛选条件的学科资料。</p>;
  return (
    <div ref={topRef}>
      {folder ? (
        <>
          <div className={styles.breadcrumb}>
            <button type="button" onClick={() => onSubjectChange(null)}><ArrowLeft size={17} />{backLabel}</button>
            <ChevronRight size={15} aria-hidden="true" />
            <h3>{folder.name}</h3>
            <span>{folder.materials.length} 份资料</span>
          </div>
          <ul className={gridClassName}>
            {folder.materials.slice((safePage - 1) * 24, safePage * 24).map(renderMaterial)}
          </ul>
          {folder.materials.length > 24 && <PaginationBar
            currentPage={safePage}
            totalItems={folder.materials.length}
            pageSize={24}
            loading={false}
            onPageChange={(next) => {
              onPageChange(next);
              topRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' });
            }}
          />}
        </>
      ) : (
        <MaterialSubjectFolders folders={folders} onOpen={onSubjectChange} />
      )}
    </div>
  );
}
