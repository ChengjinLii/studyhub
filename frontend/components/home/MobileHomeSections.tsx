import Link from 'next/link';
import { FormEvent } from 'react';
import MaterialCard from '../MaterialCard';
import SearchIconButton from '../SearchIconButton';
import { MaterialListItem } from '../../types/material';

const CTA_LINKS = [
  {
    href: '/upload',
    label: '我要投稿',
    variant: 'upload',
    paths: ['M12 4v10M8 8l4-4 4 4', 'M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4'],
  },
  {
    href: '/join',
    label: '关于我们',
    variant: 'more',
    paths: ['M12 6v.01', 'M11 10h1v7h1', 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18'],
  },
];

const LEADERBOARD_ICON_PATHS = [
  'M8 21h8',
  'M12 17v4',
  'M7 4h10',
  'M17 4v5a5 5 0 0 1-10 0V4',
  'M5 4h2v3a5 5 0 0 1-2 4',
  'M19 4h-2v3a5 5 0 0 0 2 4',
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
        <ul className="materials-list mobile-resource-list mobile-home-resource-grid">
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
  stats: Array<{ label: string; value: string }>;
  recommendedItems: MaterialListItem[];
  latestItems: MaterialListItem[];
  onMobileSearchChange: (value: string) => void;
  onMobileSearchSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onJumpToLeaderboard: () => void;
}

export default function MobileHomeSections({
  mobileSearch,
  stats,
  recommendedItems,
  latestItems,
  onMobileSearchChange,
  onMobileSearchSubmit,
  onJumpToLeaderboard,
}: MobileHomeSectionsProps) {
  return (
    <>
      <section className="card mobile-home-task-panel" aria-label="移动端搜索与概览">
        <div className="mobile-home-task-panel__head">
          <span>StudyHub</span>
          <h2>校园资料集</h2>
        </div>
        <div className="mobile-home-overview" aria-label="平台概览">
          {stats.map((stat) => (
            <div key={stat.label} className="mobile-home-overview__item">
              <span>{stat.label}</span>
              <strong>{stat.value}</strong>
            </div>
          ))}
        </div>
        <form className="mobile-home-search" onSubmit={onMobileSearchSubmit}>
          <input value={mobileSearch} onChange={(event) => onMobileSearchChange(event.target.value)} placeholder="空格分隔：概率论 期末" aria-label="搜索资料" />
          <SearchIconButton />
        </form>
        <div className="mobile-home-actions">
          {CTA_LINKS.map((item) => (
            <Link key={item.href} className={`mobile-home-action mobile-home-action--${item.variant}`} href={item.href} prefetch={false}>
              <span className="mobile-home-action__icon" aria-hidden="true">
                <svg viewBox="0 0 24 24">
                  {item.paths.map((path) => <path key={path} d={path} fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />)}
                </svg>
              </span>
              <span>{item.label}</span>
            </Link>
          ))}
          <button className="mobile-home-action mobile-home-action--leaderboard" type="button" onClick={onJumpToLeaderboard}>
            <span className="mobile-home-action__icon" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                {LEADERBOARD_ICON_PATHS.map((path) => <path key={path} d={path} fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />)}
              </svg>
            </span>
            <span>贡献榜单</span>
          </button>
        </div>
      </section>
      <MobileResourceSection title="为你推荐" eyebrow="Recommend" hrefLabel="更多" items={recommendedItems} />
      <MobileResourceSection title="最新资料" eyebrow="Latest" hrefLabel="全部资料" items={latestItems} />
    </>
  );
}
