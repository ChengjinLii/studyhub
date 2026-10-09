import { FolderOpen, LayoutGrid } from 'lucide-react';
import type { MaterialBrowseMode } from '../../lib/useMaterialSubjects';
import styles from '../../styles/MaterialSubjects.module.css';

export default function MaterialBrowseToggle({ value, onChange }: {
  value: MaterialBrowseMode;
  onChange: (mode: MaterialBrowseMode) => void;
}) {
  return (
    <div className={styles.toggle} role="group" aria-label="资料展示方式">
      {([
        { mode: 'materials', label: '按资料', Icon: LayoutGrid },
        { mode: 'subjects', label: '按学科', Icon: FolderOpen },
      ] as const).map(({ mode, label, Icon }) => (
        <button key={mode} type="button" aria-pressed={value === mode} onClick={() => onChange(mode)}>
          <Icon size={17} aria-hidden="true" />
          <span>{label}</span>
        </button>
      ))}
    </div>
  );
}
