import Link from 'next/link';
import { FormEvent } from 'react';
import MaterialCard from '../MaterialCard';
import { MaterialListItem } from '../../types/material';

const ACTIONS = [
  {
    href: '/materials',
    label: '找资料',
    variant: 'materials',
    paths: ['M5 4h10a4 4 0 0 1 4 4v12H7a2 2 0 0 1-2-2V4z', 'M7 16h12M9 8h6M9 11h5'],
  },
  {
    href: '/upload',
    label: '去投稿',
    variant: 'upload',
    paths: ['M12 4v10M8 8l4-4 4 4', 'M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4'],
  },
  {
    href: '/requests/new',
    label: '发求购',
    variant: 'request',
    paths: ['M12 5v14M5 12h14', 'M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16'],
  },
  {
    href: '/more',
    label: '更多',
    variant: 'more',
    paths: ['M5 6h14M5 12h14M5 18h14'],
  },
];

function MobileResourceSection({ title, eyebrow, hrefLabel, items }: { title: string; eyebrow: string; hrefLabel: string; items: MaterialListItem[] }) {
  return (
    <section className="card mobile-home-preview" aria-label={`移动端${title}`}>
      <div className="mobile-section-head">
        <div>
          <span>{eyebrow}</span>
          <h2>{title}</h2>
        </div>
        <Link href="/materials" prefetch={false}>{hrefLabel}</Link>
      </div>
      {items.length > 0 ? (
        <ul className="materials-list mobile-resource-list">
          {items.map((item) => <MaterialCard key={item.id} material={item} />)}
        </ul>
      ) : (
        <div className="empty-state">暂无资料。</div>
      )}
    </section>
  );
}

interface MobileHomeSectionsProps {
  mobileSearch: string;
  recommendedItems: MaterialListItem[];
  latestItems: MaterialListItem[];
  onMobileSearchChange: (value: string) => void;
  onMobileSearchSubmit: (event: FormEvent<HTMLFormElement>) => void;
}

export default function MobileHomeSections({
  mobileSearch,
  recommendedItems,
  latestItems,
  onMobileSearchChange,
  onMobileSearchSubmit,
}: MobileHomeSectionsProps) {
  return (
    <>
      <section className="card mobile-home-task-panel" aria-label="移动端快捷入口">
        <div className="mobile-home-task-panel__head">
          <span>StudyHub</span>
          <h2>找资料、投稿、求购</h2>
        </div>
        <form className="mobile-home-search" onSubmit={onMobileSearchSubmit}>
          <input value={mobileSearch} onChange={(event) => onMobileSearchChange(event.target.value)} placeholder="空格分隔：概率论 期末" aria-label="搜索资料" />
          <button className="button primary" type="submit">搜索</button>
        </form>
        <div className="mobile-home-actions">
          {ACTIONS.map((item) => (
            <Link key={item.href} className={`mobile-home-action mobile-home-action--${item.variant}`} href={item.href} prefetch={false}>
              <span className="mobile-home-action__icon" aria-hidden="true">
                <svg viewBox="0 0 24 24">
                  {item.paths.map((path) => <path key={path} d={path} fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />)}
                </svg>
              </span>
              <span>{item.label}</span>
            </Link>
          ))}
        </div>
      </section>
      <MobileResourceSection title="为你推荐" eyebrow="Recommend" hrefLabel="更多" items={recommendedItems} />
      <MobileResourceSection title="最新资料" eyebrow="Latest" hrefLabel="全部资料" items={latestItems} />
    </>
  );
}
