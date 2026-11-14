import Link from 'next/link';
import { useEffect, useState } from 'react';
import { ContributorRank, LeaderboardPeriod } from '../../types/contributor';
import { RoleMask, SessionUser } from '../../types/user';
import { userPath } from '../../lib/slug';
import minStyles from '../../styles/HomeMinimal.module.css';

const DEFAULT_VISIBLE_CONTRIBUTORS = 5;

interface HomeLeaderboardProps {
  user: SessionUser | null;
  topContributors: ContributorRank[];
  leaderboardPeriod: LeaderboardPeriod;
  leaderboardLabels: Record<LeaderboardPeriod, string>;
  leaderboardPeriods: LeaderboardPeriod[];
  leaderboardRangeHint: string;
  leaderboardEmptyHint: string;
  leaderboardLoading: boolean;
  leaderboardError: string;
  leaderboardFollowNotice: { type: 'success' | 'error'; text: string } | null;
  leaderboardFollowed: Record<number, boolean>;
  leaderboardFollowLoading: Record<number, boolean>;
  onPeriodChange: (period: LeaderboardPeriod) => void;
  onFollowContributor: (userId: number) => void;
}

export default function HomeLeaderboard({
  user,
  topContributors,
  leaderboardPeriod,
  leaderboardLabels,
  leaderboardPeriods,
  leaderboardEmptyHint,
  leaderboardLoading,
  leaderboardError,
  leaderboardFollowNotice,
  leaderboardFollowed,
  leaderboardFollowLoading,
  onPeriodChange,
  onFollowContributor,
}: HomeLeaderboardProps) {
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setExpanded(false);
  }, [leaderboardPeriod]);

  const visibleContributors = expanded
    ? topContributors
    : topContributors.slice(0, DEFAULT_VISIBLE_CONTRIBUTORS);

  return (
    <section id="leaderboard" className={`leaderboard-card ${minStyles.sideBlock}`}>
      <div className={minStyles.sideBlockHeader}>
        <h2 className={minStyles.sideBlockTitle}>贡献榜单</h2>
        <div className={minStyles.periodTabs} role="tablist" aria-label="贡献榜单周期">
          {leaderboardPeriods.map((period) => {
            const active = leaderboardPeriod === period;
            return (
              <button
                key={period}
                type="button"
                role="tab"
                aria-selected={active}
                className={`${minStyles.periodTab}${active ? ` ${minStyles.periodTabActive}` : ''}`}
                onClick={() => onPeriodChange(period)}
              >
                {leaderboardLabels[period]}
              </button>
            );
          })}
        </div>
      </div>

      {leaderboardFollowNotice?.type === 'error' ? <p className="error-text">{leaderboardFollowNotice.text}</p> : null}
      {leaderboardError ? <p className="error-text">{leaderboardError}</p> : null}
      {leaderboardLoading ? <p className={minStyles.sideNote}>贡献榜单加载中...</p> : null}

      {topContributors.length === 0 ? (
        <div className={minStyles.emptyMuted}>{leaderboardEmptyHint}</div>
      ) : (
        <ol className={minStyles.contribList}>
          {(() => {
            let rankCounter = 0;
            return visibleContributors.map((c, idx) => {
              const isSelf = Boolean(user && user.id === c.userId);
              const isFollowed = Boolean(leaderboardFollowed[c.userId]);
              const isLoading = Boolean(leaderboardFollowLoading[c.userId]);
              const followLabel = isSelf ? '自己' : isFollowed ? '已关注' : isLoading ? '关注中...' : '关注';
              const roleMask = c.roleMask ?? 0;
              const isAdmin =
                (roleMask & RoleMask.ADMIN) === RoleMask.ADMIN ||
                (roleMask & RoleMask.DEVELOPER) === RoleMask.DEVELOPER;
              const rankLabel = isAdmin ? '管' : String(++rankCounter);
              return (
                <li key={`${c.userId}-${idx}`} className={minStyles.contribItem}>
                  <span className={minStyles.sideRankNum}>{rankLabel}</span>
                  <div className={minStyles.contribInfo}>
                    <Link href={userPath(c.userId, c.username || '匿名贡献者')} prefetch={false}>
                      {c.username || '匿名贡献者'}
                    </Link>
                    <span>{c.downloads} 位同学下载过 Ta 的资料</span>
                  </div>
                  <button
                    className={minStyles.miniPillBtn}
                    type="button"
                    onClick={() => onFollowContributor(c.userId)}
                    disabled={isSelf || isFollowed || isLoading}
                  >
                    {followLabel}
                  </button>
                </li>
              );
            });
          })()}
        </ol>
      )}

      {topContributors.length > DEFAULT_VISIBLE_CONTRIBUTORS ? (
        <div>
          <button
            className={minStyles.sideActionLink}
            type="button"
            onClick={() => setExpanded((current) => !current)}
            aria-expanded={expanded}
          >
            {expanded ? '收起榜单' : `展开全部（${topContributors.length}）`}
          </button>
        </div>
      ) : null}
    </section>
  );
}
