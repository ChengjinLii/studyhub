import { FolderOpen, LayoutGrid } from 'lucide-react';
import { APPLE_SPRINGS, APPLE_TAP, m, SegmentedPill } from '../../lib/motion';
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
      data-motion-toggle="true"
      role="group"
      aria-label="资料展示方式"
    >
      {([
        { mode: 'materials', label: '按资料', Icon: LayoutGrid },
        { mode: 'subjects', label: '按学科', Icon: FolderOpen },
      ] as const).map(({ mode, label, Icon }) => {
        const active = value === mode;
        return (
          <m.button
            key={mode}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(mode)}
            whileTap={APPLE_TAP.button}
            transition={APPLE_SPRINGS.snappy}
          >
            {active ? (
              <SegmentedPill
                layoutId={`browse-toggle-pill-${variant}`}
                className={styles.togglePill}
              />
            ) : null}
            <span className={styles.toggleButtonContent}>
              {variant === 'default' ? <Icon size={17} aria-hidden="true" /> : null}
              <span>{label}</span>
            </span>
          </m.button>
        );
      })}
    </div>
  );
}
