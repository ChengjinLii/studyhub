import Link from 'next/link';
import { ReactNode } from 'react';
import BrandLogo from '../BrandLogo';
import { HomeSubjectRank } from '../../lib/homeDiscovery';
import { formatNumber } from '../../lib/format';
import {
  PORTAL_CANOPY_FILL_PATH,
  PORTAL_CANOPY_RIM_PATH,
  PORTAL_CANOPY_VIEWBOX_HEIGHT,
  PORTAL_CANOPY_VIEWBOX_WIDTH,
} from '../../lib/portalCanopy';
import { materialPath } from '../../lib/slug';
import { MaterialListItem } from '../../types/material';
import styles from '../../styles/HomePortal.module.css';

// Each column shows a fixed number of rows, so the first screen keeps one height.
export const PORTAL_ROW_COUNT = 5;
// A rank column holds more rows than it shows: the reader turns it like a wheel.
export const PORTAL_WHEEL_LIMIT = 10;

const WORDMARK_LETTERS = 'StudyHub'.split('');

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
  onJumpToLeaderboard?: () => void;
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

const rankClass = (rank: number) =>
  rank === 1
    ? `${styles.rank} ${styles.rankFirst}`
    : rank <= 3
    ? `${styles.rank} ${styles.rankTop}`
    : styles.rank;

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
  onJumpToLeaderboard,
  onScrollDown,
}: HomePortalProps) {
  const topPopular = popularItems.slice(0, PORTAL_WHEEL_LIMIT);
  const topSubjects = subjectRanks.slice(0, PORTAL_WHEEL_LIMIT);
  const wheelEdge = (count: number) => (count > PORTAL_ROW_COUNT ? 'start' : 'both');

  return (
    <section className={styles.portal} data-home-portal="" aria-label="搜索">
      <div className={styles.portalMain}>
        <div className={styles.heroStage}>
          <div className={styles.canopy} data-portal-canopy="" aria-hidden="true">
            <div className={styles.canopyUpper} />
            <svg
              className={styles.canopyWave}
              data-portal-canopy-wave=""
              viewBox={`0 0 ${PORTAL_CANOPY_VIEWBOX_WIDTH} ${PORTAL_CANOPY_VIEWBOX_HEIGHT}`}
              preserveAspectRatio="none"
              focusable="false"
            >
              <defs>
                <clipPath id="portal-canopy-clip">
                  <path d={PORTAL_CANOPY_FILL_PATH} />
                </clipPath>
                <pattern id="portal-canopy-grid" width="44" height="44" patternUnits="userSpaceOnUse">
                  <path d="M 44 0 L 0 0 0 44" fill="none" stroke="rgba(255,255,255,0.022)" strokeWidth="1" />
                </pattern>
                <linearGradient id="portal-canopy-rim" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#60a5fa" stopOpacity="0" />
                  <stop offset="18%" stopColor="#60a5fa" stopOpacity="0.68" />
                  <stop offset="44%" stopColor="#818cf8" stopOpacity="0.88" />
                  <stop offset="64%" stopColor="#fcd34d" stopOpacity="0.66" />
                  <stop offset="82%" stopColor="#38bdf8" stopOpacity="0.74" />
                  <stop offset="100%" stopColor="#38bdf8" stopOpacity="0" />
                </linearGradient>
                <radialGradient id="portal-aurora-left" cx="28%" cy="89%" r="26%">
                  <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.11" />
                  <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
                </radialGradient>
                <radialGradient id="portal-aurora-mid" cx="54%" cy="84%" r="24%">
                  <stop offset="0%" stopColor="#818cf8" stopOpacity="0.1" />
                  <stop offset="100%" stopColor="#818cf8" stopOpacity="0" />
                </radialGradient>
                <radialGradient id="portal-aurora-right" cx="76%" cy="87%" r="22%">
                  <stop offset="0%" stopColor="#2dd4bf" stopOpacity="0.08" />
                  <stop offset="65%" stopColor="#f59e0b" stopOpacity="0.03" />
                  <stop offset="100%" stopColor="#2dd4bf" stopOpacity="0" />
                </radialGradient>
              </defs>
              <g clipPath="url(#portal-canopy-clip)">
                <rect width={PORTAL_CANOPY_VIEWBOX_WIDTH} height={PORTAL_CANOPY_VIEWBOX_HEIGHT} fill="#040507" />
                <rect
                  width={PORTAL_CANOPY_VIEWBOX_WIDTH}
                  height={PORTAL_CANOPY_VIEWBOX_HEIGHT}
                  fill="url(#portal-canopy-grid)"
                />
                <rect
                  width={PORTAL_CANOPY_VIEWBOX_WIDTH}
                  height={PORTAL_CANOPY_VIEWBOX_HEIGHT}
                  fill="url(#portal-aurora-left)"
                />
                <rect
                  width={PORTAL_CANOPY_VIEWBOX_WIDTH}
                  height={PORTAL_CANOPY_VIEWBOX_HEIGHT}
                  fill="url(#portal-aurora-mid)"
                />
                <rect
                  width={PORTAL_CANOPY_VIEWBOX_WIDTH}
                  height={PORTAL_CANOPY_VIEWBOX_HEIGHT}
                  fill="url(#portal-aurora-right)"
                />
              </g>
              <path
                className={styles.canopyRimGlow}
                d={PORTAL_CANOPY_RIM_PATH}
                fill="none"
                stroke="url(#portal-canopy-rim)"
                strokeWidth="5"
                vectorEffect="non-scaling-stroke"
              />
              <path
                d={PORTAL_CANOPY_RIM_PATH}
                fill="none"
                stroke="url(#portal-canopy-rim)"
                strokeWidth="1.6"
                vectorEffect="non-scaling-stroke"
              />
            </svg>
          </div>

          {/* The page heading. The opening splash lands on it, so its metrics follow the splash. */}
          <h1 className={styles.lockup} data-splash-target="" aria-label="StudyHub">
            <span className={styles.markWrap}>
              <BrandLogo
                theme="light"
                size={90}
                className={styles.logoImg}
                style={{ width: '100%', height: '100%' }}
              />
            </span>
            <span className={styles.wordmark} aria-hidden="true">
              {WORDMARK_LETTERS.map((letter, index) => (
                <span key={`${letter}-${index}`} className={styles.letter}>
                  {letter}
                </span>
              ))}
            </span>
          </h1>
        </div>

        <div className={styles.portalMid}>
          <div className={styles.search}>{search}</div>

          <div
            className={styles.annivBadge}
            data-portal-anniversary=""
            aria-label="StudyHub 一周年纪念（2025.11 – 2026.11）"
          >
            <span className={styles.annivSeal} aria-hidden="true">
              <svg className={styles.annivSealSvg} viewBox="0 0 64 64" focusable="false">
                <defs>
                  <path id="portal-anniv-arc-top" d="M 10.5,32 A 21.5,21.5 0 1,1 53.5,32" />
                  <path id="portal-anniv-arc-bot" d="M 7.5,32 A 24.5,24.5 0 0,0 56.5,32" />
                </defs>
                <circle cx="32" cy="32" r="29" fill="none" stroke="#d9bc7c" strokeWidth="1" opacity="0.88" />
                <circle
                  cx="32"
                  cy="32"
                  r="17.2"
                  fill="none"
                  stroke="#cbd5e1"
                  strokeWidth="0.75"
                  strokeDasharray="1.5 2.3"
                />
                <text
                  fontFamily="var(--font-brand), var(--font-stack)"
                  fontSize="5"
                  fontWeight="600"
                  fill="#8f6b24"
                  letterSpacing="1.35"
                >
                  <textPath href="#portal-anniv-arc-top" startOffset="50%" textAnchor="middle">
                    STUDYHUB · ANNIV
                  </textPath>
                </text>
                <text
                  fontFamily="var(--font-brand), var(--font-stack)"
                  fontSize="4.6"
                  fontWeight="600"
                  fill="#64748b"
                  letterSpacing="1.15"
                >
                  <textPath href="#portal-anniv-arc-bot" startOffset="50%" textAnchor="middle">
                    2025 — 2026
                  </textPath>
                </text>
                <text
                  x="32"
                  y="36.2"
                  textAnchor="middle"
                  fontFamily="var(--font-brand), var(--font-stack)"
                  fontSize="15.5"
                  fontWeight="640"
                  fill="#1e293b"
                  letterSpacing="-0.4"
                >
                  1st
                </text>
              </svg>
            </span>
            <span className={styles.annivMeta}>
              <span className={styles.annivTitle}>一周年纪念</span>
              <span className={styles.annivDate}>2025.11 – 2026.11</span>
            </span>
          </div>
        </div>

        <div className={styles.columns}>
          <section className={styles.column} aria-labelledby="portal-popular-title">
            <div className={styles.columnHead}>
              <h2 id="portal-popular-title">热门资料</h2>
              <button type="button" className={styles.more} onClick={onBrowseMaterials}>
                <span>全部资料</span>
                <span className={styles.moreArrow} aria-hidden="true">
                  ›
                </span>
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
                  aria-label="热门资料排行"
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
                      <span className={styles.rowMeta} aria-label={`${formatNumber(item.downloadCount ?? 0)} 次下载`}>
                        <span aria-hidden="true">↓ {formatNumber(item.downloadCount ?? 0)}</span>
                      </span>
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
                <span>全部学科</span>
                <span className={styles.moreArrow} aria-hidden="true">
                  ›
                </span>
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
                      <span className={styles.rowMeta}>
                        <span className={styles.rowCount}>{formatNumber(subject.materialCount)} 份</span>
                        <span className={styles.rowDot} aria-hidden="true">
                          ·
                        </span>
                        <span className={styles.rowSubMeta}>↓ {formatNumber(subject.downloadCount)}</span>
                      </span>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </section>

          {/* The overview shares the same editorial header rule and quiet numeric hierarchy. */}
          <section className={`${styles.column} ${styles.overview}`} aria-labelledby="portal-overview-title">
            <div className={styles.columnHead}>
              <h2 id="portal-overview-title" className={styles.overviewTitle}>
                平台概览
              </h2>
              {onJumpToLeaderboard ? (
                <button type="button" className={styles.more} onClick={onJumpToLeaderboard}>
                  <span>贡献榜</span>
                  <span className={styles.moreArrow} aria-hidden="true">
                    ›
                  </span>
                </button>
              ) : null}
            </div>
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
          <a
            className={styles.stripStart}
            href="https://beian.miit.gov.cn/"
            target="_blank"
            rel="noopener noreferrer"
          >
            浙ICP备2025212695号
          </a>
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
          <div className={`${styles.stripGroup} ${styles.stripEnd}`}>
            <span>官方 QQ 群：{officialQQ || FALLBACK_QQ_GROUP}</span>
            <span>核心贡献者：李承锦、曾逸帆</span>
          </div>
        </div>
      </div>
    </section>
  );
}
