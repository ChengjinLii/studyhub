import Link from 'next/link';
import { FormEvent } from 'react';
import MaterialCard from '../MaterialCard';
import { MaterialListItem } from '../../types/material';
import minStyles from '../../styles/HomeMinimal.module.css';

interface MobileHomeSectionsProps {
  mobileSearch: string;
  stats: Array<{ label: string; value: string }>;
  latestItems: MaterialListItem[];
  onMobileSearchChange: (value: string) => void;
  onMobileSearchSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onJumpToLeaderboard: () => void;
}

export default function MobileHomeSections({
  mobileSearch,
  stats,
  latestItems,
  onMobileSearchChange,
  onMobileSearchSubmit,
  onJumpToLeaderboard,
}: MobileHomeSectionsProps) {
  return (
    <>
      <section className="mobile-home-task-panel" aria-label="移动端搜索与概览">
        <form className="mobile-home-search" onSubmit={onMobileSearchSubmit}>
          <input
            value={mobileSearch}
            onChange={(event) => onMobileSearchChange(event.target.value)}
            placeholder="课程名 / 知识点 / 资料类型"
            aria-label="搜索资料"
          />
          <button className={minStyles.searchSubmit} type="submit" aria-label="搜索资料">
            搜索
          </button>
        </form>

        <dl className={minStyles.statsStrip} style={{ marginTop: 8 }} aria-label="平台概览">
          {stats.map((stat) => (
            <div key={stat.label} className={minStyles.statItem}>
              <dt>{stat.label}</dt>
              <dd style={{ margin: 0 }}>
                <strong style={{ fontSize: '22px' }}>{stat.value}</strong>
              </dd>
            </div>
          ))}
        </dl>

        <div className="mobile-home-actions">
          <Link className="mobile-home-action" href="/upload" prefetch={false}>
            我要投稿
          </Link>
          <button className="mobile-home-action" type="button" onClick={onJumpToLeaderboard}>
            贡献榜单
          </button>
          <Link className="mobile-home-action" href="/join" prefetch={false}>
            关于我们
          </Link>
        </div>
      </section>

      <section className="mobile-home-preview" aria-label="移动端资料列表">
        <div className="mobile-section-head">
          <h2>最新资料</h2>
          <Link href="/materials" prefetch={false}>
            全部资料
          </Link>
        </div>
        {latestItems.length > 0 ? (
          <ul className={`materials-list ${minStyles.minimalList}`}>
            {latestItems.map((item) => (
              <MaterialCard key={item.id} material={item} variant="minimal" />
            ))}
          </ul>
        ) : (
          <div className={minStyles.emptyMuted}>暂无资料。</div>
        )}
      </section>
    </>
  );
}
