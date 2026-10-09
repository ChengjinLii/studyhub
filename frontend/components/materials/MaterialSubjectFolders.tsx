import { ChevronRight } from 'lucide-react';
import type { MaterialSubjectFolder } from '../../lib/materialSubjects';
import styles from '../../styles/MaterialSubjects.module.css';

export default function MaterialSubjectFolders({ folders, onOpen, label = '学科文件夹' }: {
  folders: MaterialSubjectFolder[];
  onOpen: (id: string) => void;
  label?: string;
}) {
  return (
    <ul className={styles.folders} aria-label={label}>
      {folders.map((item) => (
        <li key={item.id}>
          <button type="button" aria-label={`${item.name} ${item.materials.length} 份资料`} onClick={() => onOpen(item.id)}>
            <span className={styles.folderArt} aria-hidden="true">
              {/* Fluent Emoji folder paths; attribution is in THIRD_PARTY_NOTICES.md. */}
              <svg width="48" height="48" viewBox="0 0 32 32" fill="none" focusable="false">
                <path className={styles.folderBack} d="M15.385 7.39062L12.9075 4.915C12.3219 4.32875 11.5275 4 10.6987 4H4.125C2.95125 4 2 4.95125 2 6.125V13.5H12.985H30V10.1375C30 8.96375 29.0488 8.0125 27.875 8.0125H16.8875C16.3237 8.0125 15.7838 7.78875 15.385 7.39062Z M27.875 30H4.125C2.95125 30 2 29.0545 2 27.8878V13.1122C2 11.9455 2.95125 11 4.125 11H27.875C29.0488 11 30 11.9455 30 13.1122V27.8878C30 29.0545 29.0488 30 27.875 30Z" fill="#547EC8" />
                <rect x="6" y="12" width="20" height="15" rx="1.2" fill="#fff" stroke="#dbe5f3" strokeWidth="0.6" />
                <path className={styles.folderFront} d="M27.875 30H4.125C2.95125 30 2 29.0545 2 27.8878L2 13.1122C2 11.9455 2.95125 11 4.125 11H27.875C29.0488 11 30 11.9455 30 13.1122L30 27.8878C30 29.0545 29.0488 30 27.875 30Z" fill="#9FBFEF" />
              </svg>
            </span>
            <span className={styles.folderInfo}>
              <strong>{item.name}</strong>
              <span className={styles.folderCount}><span>{item.materials.length}</span> 份资料</span>
            </span>
            <ChevronRight className={styles.folderArrow} size={17} aria-hidden="true" />
          </button>
        </li>
      ))}
    </ul>
  );
}
