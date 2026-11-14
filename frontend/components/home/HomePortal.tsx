import Link from 'next/link';
import { ReactNode } from 'react';
import BrandLogo from '../BrandLogo';
import { HomeSubjectRank } from '../../lib/homeDiscovery';
import { formatNumber } from '../../lib/format';
import { materialPath } from '../../lib/slug';
import { MaterialListItem } from '../../types/material';
import styles from '../../styles/HomePortal.module.css';

// Each column shows a fixed number of rows, so the first screen keeps one height.
export const PORTAL_ROW_COUNT = 5;
// A rank column holds more rows than it shows: the reader turns it like a wheel.
export const PORTAL_WHEEL_LIMIT = 10;

const FALLBACK_QQ_GROUP = '245934740';

export interface HomePortalStats {
  users: string;
  materials: string;
  free: string;
  downloads: string;
  subjects: string;
}

interface HomePortalProps {
  /** The search form (keyword box, filters and the two actions). */
  search: ReactNode;
  popularItems: MaterialListItem[];
  subjectRanks: HomeSubjectRank[];
  stats: HomePortalStats;
  officialQQ?: string;
  onOpenSubject: (id: string) => void;
  onBrowseSubjects: () => void;
  onBrowseMaterials: () => void;
  /** Opens the content under the first screen and scrolls to it. */
  onScrollDown: () => void;
}

/**
 * Keeps the state of a wheel list on the element: which end it rests at (for the fade at the
 * other end) and how far it has turned (for the thumb at its side).
 */
const markWheel = (list: HTMLElement) => {
  const range = list.scrollHeight - list.clientHeight;
  const atStart = list.scrollTop <= 1;
  const atEnd = list.scrollTop >= range - 1;
  list.dataset.edge = atStart && atEnd ? 'both' : atStart ? 'start' : atEnd ? 'end' : 'middle';
  list.parentElement?.style.setProperty('--wheel-turn', range > 0 ? String(list.scrollTop / range) : '0');
};

const rankClass = (rank: number) => `${styles.rank}${rank <= 3 ? ` ${styles.rankTop}` : ''}`;

/**
 * First screen of the home page: a search portal. The brand lockup sits over a centred search
 * box; three short columns follow, and a thin information strip closes the screen. The strip
 * also tells the reader to scroll: the rest of the home page starts under it.
 */
export default function HomePortal({
  search,
  popularItems,
  subjectRanks,
  stats,
  officialQQ,
  onOpenSubject,
  onBrowseSubjects,
  onBrowseMaterials,
  onScrollDown,
}: HomePortalProps) {
  const topPopular = popularItems.slice(0, PORTAL_WHEEL_LIMIT);
  const topSubjects = subjectRanks.slice(0, PORTAL_WHEEL_LIMIT);
  const wheelEdge = (count: number) => (count > PORTAL_ROW_COUNT ? 'start' : 'both');

  return (
    <section className={styles.portal} data-home-portal="" aria-label="搜索">
      <div className={styles.portalMain}>
        {/* The page heading. The opening splash lands on it, so its metrics follow the splash. */}
        <h1 className={styles.lockup} data-splash-target="">
          <BrandLogo theme="light" size={72} />
          <span className={styles.wordmark}>StudyHub</span>
        </h1>

        <div className={styles.search}>{search}</div>

        <div className={styles.columns}>
          <section className={styles.column} aria-labelledby="portal-popular-title">
            <div className={styles.columnHead}>
              <h2 id="portal-popular-title">近期热门</h2>
              <button type="button" className={styles.more} onClick={onBrowseMaterials}>
                全部资料
              </button>
            </div>
            {topPopular.length === 0 ? (
              <p className={styles.empty}>暂无热门资料。</p>
            ) : (
              <div className={styles.wheel}>
                <ol
                  className={styles.wheelRows}
                  data-edge={wheelEdge(topPopular.length)}
                  onScroll={(event) => markWheel(event.currentTarget)}
                  aria-label="近期热门资料排行"
                >
                  {topPopular.map((item, index) => (
                    <li key={item.id} className={styles.row}>
                      <span className={rankClass(index + 1)}>{index + 1}</span>
                      <Link
                        className={styles.rowName}
                        href={materialPath(item.id, item.title)}
                        prefetch={false}
                        title={item.title}
                      >
                        {item.title}
                      </Link>
                      <span className={styles.rowMeta}>{formatNumber(item.downloadCount ?? 0)} 下载</span>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </section>

          <section className={styles.column} aria-labelledby="portal-subjects-title">
            <div className={styles.columnHead}>
              <h2 id="portal-subjects-title">热门学科</h2>
              <button type="button" className={styles.more} onClick={onBrowseSubjects}>
                全部学科
              </button>
            </div>
            {topSubjects.length === 0 ? (
              <p className={styles.empty}>暂无学科资料。</p>
            ) : (
              <div className={styles.wheel}>
                <ol
                  className={styles.wheelRows}
                  data-edge={wheelEdge(topSubjects.length)}
                  onScroll={(event) => markWheel(event.currentTarget)}
                  aria-label="热门学科排行"
                >
                  {topSubjects.map((subject, index) => (
                    <li key={subject.id} className={styles.row}>
                      <span className={rankClass(index + 1)}>{index + 1}</span>
                      <button
                        type="button"
                        className={styles.rowName}
                        onClick={() => onOpenSubject(subject.id)}
                        title={subject.name}
                      >
                        {subject.name}
                      </button>
                      <span className={styles.rowMeta}>{formatNumber(subject.downloadCount)} 下载</span>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </section>

          {/* The overview is set apart from the two rank columns: a rule at its left, the user
              count large, and the other figures in a short list at its right. */}
          <section className={`${styles.column} ${styles.overview}`} aria-labelledby="portal-overview-title">
            <h2 id="portal-overview-title" className={styles.overviewTitle}>
              平台概览
            </h2>
            <div className={styles.overviewBody}>
              <p className={styles.overviewLead}>
                <strong>{stats.users}</strong>
                <span>位注册同学</span>
              </p>
              <dl className={styles.overviewRows}>
                <div>
                  <dt>已上架资料</dt>
                  <dd>{stats.materials}</dd>
                </div>
                <div>
                  <dt>免费资料</dt>
                  <dd>{stats.free}</dd>
                </div>
                <div>
                  <dt>累计下载</dt>
                  <dd>{stats.downloads}</dd>
                </div>
                <div>
                  <dt>收录学科</dt>
                  <dd>{stats.subjects}</dd>
                </div>
              </dl>
            </div>
          </section>
        </div>
      </div>

      {/* The strip closes the first screen. Its centre tells that the page goes on below; the line
          on its top edge fills while the reader scrolls towards the content. */}
      <div className={styles.strip}>
        <div className={styles.stripInner}>
          <div className={styles.stripGroup}>
            <span>官方 QQ 群：{officialQQ || FALLBACK_QQ_GROUP}</span>
            <span>核心贡献者：李承锦、曾逸帆</span>
          </div>
          <button type="button" className={styles.scrollCue} onClick={onScrollDown}>
            <span>向下滚动，浏览资料与贡献榜</span>
            <svg
              className={styles.scrollCueArrow}
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>
          <a
            className={styles.stripEnd}
            href="https://beian.miit.gov.cn/"
            target="_blank"
            rel="noopener noreferrer"
          >
            浙ICP备2025212695号
          </a>
        </div>
      </div>
    </section>
  );
}
