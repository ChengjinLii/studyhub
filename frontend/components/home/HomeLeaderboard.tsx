import Link from 'next/link';
import { ContributorRank, LeaderboardPeriod } from '../../types/contributor';
import { RoleMask, SessionUser } from '../../types/user';
import { userPath } from '../../lib/slug';

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
  leaderboardRangeHint,
  leaderboardEmptyHint,
  leaderboardLoading,
  leaderboardError,
  leaderboardFollowNotice,
  leaderboardFollowed,
  leaderboardFollowLoading,
  onPeriodChange,
  onFollowContributor,
}: HomeLeaderboardProps) {
  return (
    <section id="leaderboard" className="card leaderboard-card" style={{ gridColumn: '1 / -1' }}>
      <div className="materials-header">
        <div>
          <h2 className="card-title">
            贡献榜单
            <svg className="title-icon" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M8 21h8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              <path d="M12 17v4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              <path d="M7 4h10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              <path d="M17 4v5a5 5 0 0 1-10 0V4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M5 4h2v3a5 5 0 0 1-2 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M19 4h-2v3a5 5 0 0 0 2 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </h2>
          <p className="help-text">
            {leaderboardLabels[leaderboardPeriod]}按去重下载次数排行（同一用户下载同一资料只算一次），展示前{' '}
            {topContributors.length || 0} 位投稿者。
            {leaderboardRangeHint && <span className="leaderboard-period-hint">{leaderboardRangeHint}</span>}
          </p>
          <p className="help-text">同一用户下载同一上传者不同资料会累计；重复下载同一资料不重复计数。</p>
        </div>
        <div className="leaderboard-controls">
          <div className="leaderboard-tabs" role="tablist" aria-label="贡献榜单周期">
            {leaderboardPeriods.map((period) => (
              <button
                key={period}
                type="button"
                role="tab"
                aria-selected={leaderboardPeriod === period}
                className={`leaderboard-tab ${leaderboardPeriod === period ? 'active' : ''}`}
                onClick={() => onPeriodChange(period)}
              >
                {leaderboardLabels[period]}
              </button>
            ))}
          </div>
        </div>
      </div>
      {leaderboardFollowNotice?.type === 'error' && <p className="error-text">{leaderboardFollowNotice.text}</p>}
      {leaderboardError && <p className="error-text">{leaderboardError}</p>}
      {leaderboardLoading && <p className="help-text">贡献榜单加载中...</p>}
      {topContributors.length === 0 ? (
        <div className="empty-state">{leaderboardEmptyHint}</div>
      ) : (
        <div className="leaderboard-scroll">
          <ol className="leaderboard-list">
            {(() => {
              let rankCounter = 0;
              return topContributors.map((c, idx) => {
                const isSelf = Boolean(user && user.id === c.userId);
                const isFollowed = Boolean(leaderboardFollowed[c.userId]);
                const isLoading = Boolean(leaderboardFollowLoading[c.userId]);
                const followLabel = isSelf ? '自己' : isFollowed ? '已关注' : isLoading ? '关注中...' : '关注';
                const followClass = `button ${isFollowed || isSelf ? 'ghost muted' : 'primary'} small`;
                const roleMask = c.roleMask ?? 0;
                const isAdmin =
                  (roleMask & RoleMask.ADMIN) === RoleMask.ADMIN ||
                  (roleMask & RoleMask.DEVELOPER) === RoleMask.DEVELOPER;
                const rankLabel = isAdmin ? '管' : String(++rankCounter);
                return (
                  <li key={`${c.userId}-${idx}`}>
                    <div className={`leaderboard-rank ${isAdmin ? 'rank-admin' : `rank-${rankCounter}`}`}>{rankLabel}</div>
                    <div className="leaderboard-meta">
                      <strong>
                        <Link className="text-button" href={userPath(c.userId, c.username || '匿名贡献者')}>
                          {c.username || '匿名贡献者'}
                        </Link>
                      </strong>
                      <span>{c.downloads} 位同学下载过 Ta 的资料</span>
                    </div>
                    <div className="leaderboard-actions">
                      <Link
                        className="button ghost small leaderboard-view-action"
                        href={userPath(c.userId, c.username || '匿名贡献者')}
                      >
                        查看
                      </Link>
                      <button
                        className={followClass}
                        type="button"
                        onClick={() => onFollowContributor(c.userId)}
                        disabled={isSelf || isFollowed || isLoading}
                      >
                        {followLabel}
                      </button>
                    </div>
                  </li>
                );
              });
            })()}
          </ol>
        </div>
      )}
    </section>
  );
}
