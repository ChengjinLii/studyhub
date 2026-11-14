import { FolderOpen, LayoutGrid } from 'lucide-react';
import type { MaterialBrowseMode } from '../../lib/useMaterialSubjects';
import styles from '../../styles/MaterialSubjects.module.css';

export default function MaterialBrowseToggle({ value, onChange, variant = 'default' }: {
  value: MaterialBrowseMode;
  onChange: (mode: MaterialBrowseMode) => void;
  variant?: 'default' | 'minimal';
}) {
  return (
    <div
      className={`${styles.toggle}${variant === 'minimal' ? ` ${styles.minimalToggle}` : ''}`}
      role="group"
      aria-label="资料展示方式"
    >
      {([
        { mode: 'materials', label: '按资料', Icon: LayoutGrid },
        { mode: 'subjects', label: '按学科', Icon: FolderOpen },
      ] as const).map(({ mode, label, Icon }) => (
        <button key={mode} type="button" aria-pressed={value === mode} onClick={() => onChange(mode)}>
          {variant === 'default' ? <Icon size={17} aria-hidden="true" /> : null}
          <span>{label}</span>
        </button>
      ))}
    </div>
  );
}
