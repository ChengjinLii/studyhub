import Link from 'next/link';
import { useCallback, useState } from 'react';
import { MaterialListItem } from '../../types/material';
import { MaterialRequestItem } from '../../types/request';
import { HOME_DISCOVERY_DEFAULT_VIEW, HomeDiscoveryView, HomeSubjectRank } from '../../lib/homeDiscovery';
import { copyToClipboard } from '../../lib/share';
import { materialPath } from '../../lib/slug';
import { formatDate, formatNumber } from '../../lib/format';
import minStyles from '../../styles/HomeMinimal.module.css';

const COOPERATION_EMAIL = 'chengjinli@std.uestc.edu.cn';
// The card is shown at phone width only, so each list stays short.
const SIDEBAR_LIST_LIMIT = 5;

// Rank badge. The first three ranks are set in the accent colour.
const rankBadgeClass = (rank: number) => `${minStyles.sideRankNum}${rank <= 3 ? ` ${minStyles.sideRankNumTop}` : ''}`;

const DISCOVERY_TABS: Array<{ view: HomeDiscoveryView; label: string }> = [
  { view: 'subjects', label: '热门学科' },
  { view: 'popular', label: '近期热门' },
  { view: 'requests', label: '求购列表' },
];

export interface HomeDiscoveryCardProps {
  requestItems: MaterialRequestItem[];
  requestLoading: boolean;
  requestError: string;
  requestNotice: { type: 'success' | 'error'; text: string } | null;
  leaderboardItems: MaterialRequestItem[];
  popularItems: MaterialListItem[];
  subjectRanks: HomeSubjectRank[];
  subjectsUpdatedAt: string;
  onOpenSubject: (id: string) => void;
  onBrowseSubjects: () => void;
  onBrowseMaterials: () => void;
  buildUploadLink: (item: MaterialRequestItem) => string;
  onFollowRequest: (item: MaterialRequestItem) => void;
  className?: string;
}

export interface HomeCooperationCardProps {
  profileMissingFields: string[];
  className?: string;
}

type HomeRequestPanelsProps = HomeDiscoveryCardProps & HomeCooperationCardProps;

export function HomeDiscoveryCard({
  requestItems,
  requestLoading,
  requestError,
  requestNotice,
  leaderboardItems,
  popularItems,
  subjectRanks,
  subjectsUpdatedAt,
  onOpenSubject,
  onBrowseSubjects,
  onBrowseMaterials,
  className,
}: HomeDiscoveryCardProps) {
  const [activeDiscoveryView, setActiveDiscoveryView] = useState<HomeDiscoveryView>(HOME_DISCOVERY_DEFAULT_VIEW);
  const topSubjects = subjectRanks.slice(0, SIDEBAR_LIST_LIMIT);
  const topPopular = popularItems.slice(0, SIDEBAR_LIST_LIMIT);
  const visibleRequests = (leaderboardItems.length > 0 ? leaderboardItems : requestItems).slice(0, SIDEBAR_LIST_LIMIT);

  return (
    <section
      className={`request-card ${minStyles.sideBlock}${className ? ` ${className}` : ''}`}
      id="home-requests"
      aria-label="热门与发现"
    >
      <div className={minStyles.sideTabs} role="tablist" aria-label="首页发现内容">
        {DISCOVERY_TABS.map((tab) => {
          const selected = activeDiscoveryView === tab.view;
          return (
            <button
              key={tab.view}
              id={`home-discovery-tab-${tab.view}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls="home-discovery-panel"
              className={`${minStyles.sideTabBtn}${selected ? ` ${minStyles.sideTabBtnActive}` : ''}`}
              onClick={() => setActiveDiscoveryView(tab.view)}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      <div
        id="home-discovery-panel"
        role="tabpanel"
        aria-labelledby={`home-discovery-tab-${activeDiscoveryView}`}
      >
        {activeDiscoveryView === 'requests' ? (
          <>
            {requestLoading ? <p className={minStyles.sideNote}>加载中...</p> : null}
            {requestError ? <p className="error-text">{requestError}</p> : null}
            {requestNotice ? (
              <p className={requestNotice.type === 'error' ? 'error-text' : 'success-text'}>
                {requestNotice.text}
              </p>
            ) : null}
            {!requestLoading && visibleRequests.length === 0 ? (
              <div className={minStyles.emptyMuted}>暂时没有公开的求购需求。</div>
            ) : (
              <ol className={minStyles.sideRankList} aria-label="求购榜">
                {visibleRequests.map((item, index) => {
                  const title = item.course || '求购需求';
                  const amountText =
                    item.fundedAmount != null && item.fundedAmount > 0
                      ? `已筹 ¥${item.fundedAmount}`
                      : item.budget != null
                        ? `预算 ¥${item.budget}`
                        : '待议';
                  return (
                    <li key={item.id} className={minStyles.sideRankRow}>
                      <span className={rankBadgeClass(index + 1)}>{index + 1}</span>
                      <span className={minStyles.sideRankLine}>
                        <Link className={minStyles.sideRankName} href={`/requests/${item.id}`} prefetch={false}>
                          {title}
                        </Link>
                        <span className={minStyles.sideRankMeta}>{amountText}</span>
                      </span>
                    </li>
                  );
                })}
              </ol>
            )}
            <div className={minStyles.sideFooterRow}>
              <span className={minStyles.sideNote}>按已筹金额排行</span>
              <div style={{ display: 'inline-flex', gap: 12 }}>
                <Link className={minStyles.sideActionLink} href="/requests" prefetch={false}>
                  全部求购
                </Link>
                <Link className={minStyles.sideActionLink} href="/requests/new" prefetch={false}>
                  我要购买
                </Link>
              </div>
            </div>
          </>
        ) : activeDiscoveryView === 'popular' ? (
          <>
            {topPopular.length === 0 ? (
              <div className={minStyles.emptyMuted}>暂无热门资料。</div>
            ) : (
              <ol className={minStyles.sideRankList} aria-label="近期热门资料">
                {topPopular.map((item, index) => (
                  <li key={item.id} className={minStyles.sideRankRow}>
                    <span className={rankBadgeClass(index + 1)}>{index + 1}</span>
                    <span className={minStyles.sideRankMain}>
                      <Link
                        className={minStyles.sideRankName}
                        href={materialPath(item.id, item.title)}
                        prefetch={false}
                        title={item.title}
                      >
                        {item.title}
                      </Link>
                    </span>
                    <span className={minStyles.sideRankValue}>
                      {formatNumber(item.downloadCount ?? 0)}
                      <span>下载</span>
                    </span>
                  </li>
                ))}
              </ol>
            )}
            <div className={minStyles.sideFooterRow}>
              <span className={minStyles.sideNote}>近期下载排行</span>
              <button className={minStyles.sideActionLink} type="button" onClick={onBrowseMaterials}>
                全部资料
              </button>
            </div>
          </>
        ) : (
          <>
            {topSubjects.length === 0 ? (
              <div className={minStyles.emptyMuted}>暂无学科资料。</div>
            ) : (
              <ol className={minStyles.sideRankList} aria-label="热门学科排行">
                {topSubjects.map((subject, index) => (
                  <li key={subject.id}>
                    <button
                      type="button"
                      className={minStyles.sideRankButton}
                      onClick={() => onOpenSubject(subject.id)}
                      aria-label={`查看${subject.name}，${subject.materialCount}份资料`}
                    >
                      <span className={rankBadgeClass(index + 1)}>{index + 1}</span>
                      <span className={minStyles.sideRankMain}>
                        <span className={minStyles.sideRankName}>{subject.name}</span>
                        <span className={minStyles.sideRankMeta}>{formatNumber(subject.materialCount)} 份资料</span>
                      </span>
                      <span className={minStyles.sideRankValue}>
                        {formatNumber(subject.downloadCount)}
                        <span>下载</span>
                      </span>
                      <svg
                        className={minStyles.sideRankChevron}
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                      >
                        <path d="M9 6l6 6-6 6" />
                      </svg>
                    </button>
                  </li>
                ))}
              </ol>
            )}
            <div className={minStyles.sideFooterRow}>
              <span className={minStyles.sideNote}>累计下载排行 · 更新于 {formatDate(subjectsUpdatedAt)}</span>
              <button className={minStyles.sideActionLink} type="button" onClick={onBrowseSubjects}>
                全部学科
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

export function HomeCooperationCard({ profileMissingFields, className }: HomeCooperationCardProps) {
  const profileIncomplete = profileMissingFields.length > 0;
  const profileCompletionHint = profileIncomplete
    ? `个人信息待完善：${profileMissingFields.join('、')}`
    : '完善个人主页';
  const [emailCopyState, setEmailCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const handleCopyEmail = useCallback(async () => {
    const copied = await copyToClipboard(COOPERATION_EMAIL);
    setEmailCopyState(copied ? 'copied' : 'failed');
    window.setTimeout(() => setEmailCopyState('idle'), 2000);
  }, []);

  return (
    <section
      className={`${minStyles.sideInfoSection}${className ? ` ${className}` : ''}`}
      aria-label="合作招募"
    >
      <div className={minStyles.sideSubHeadingRow}>
        <h3 className={minStyles.sideSubHeading}>合作招募</h3>
        <Link
          className={minStyles.profileHintLink}
          href="/me#profile"
          prefetch={false}
          aria-label={profileCompletionHint}
          title={profileCompletionHint}
        >
          {profileIncomplete ? '完善个人主页 · 待完善' : '完善个人主页'}
        </Link>
      </div>
      <p className={minStyles.sideDesc}>欢迎一起维护资料、专栏和代码。</p>
      <div className={minStyles.coopContactRow}>
        <a className={minStyles.coopEmail} href={`mailto:${COOPERATION_EMAIL}`}>
          {COOPERATION_EMAIL}
        </a>
        <button className={minStyles.miniPillBtn} type="button" onClick={handleCopyEmail}>
          {emailCopyState === 'copied' ? '已复制' : '复制邮箱'}
        </button>
      </div>
      {emailCopyState === 'failed' ? (
        <span className="error-text" role="status" aria-live="polite" style={{ fontSize: 12 }}>
          复制失败，请手动复制邮箱。
        </span>
      ) : null}
    </section>
  );
}

export default function HomeRequestPanels(props: HomeRequestPanelsProps) {
  return (
    <div className={`home-dual-panel`} id="home-requests-dual">
      <HomeDiscoveryCard {...props} />
      <HomeCooperationCard profileMissingFields={props.profileMissingFields} />
    </div>
  );
}
