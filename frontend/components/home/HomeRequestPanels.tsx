import Link from 'next/link';
import { ChevronRight, Copy } from 'lucide-react';
import { useCallback, useState } from 'react';
import { MaterialListItem } from '../../types/material';
import { MaterialRequestItem } from '../../types/request';
import { HOME_DISCOVERY_DEFAULT_VIEW, HomeDiscoveryView, HomeSubjectRank } from '../../lib/homeDiscovery';
import { formatMajorDisplay } from '../../lib/major';
import { copyToClipboard } from '../../lib/share';
import { materialPath } from '../../lib/slug';
import { formatDate, formatNumber } from '../../lib/format';
import styles from '../../styles/HomeDiscovery.module.css';

const COOPERATION_EMAIL = 'chengjinli@std.uestc.edu.cn';
const DISCOVERY_TABS: Array<{ view: HomeDiscoveryView; label: string }> = [
  { view: 'requests', label: '求购列表' },
  { view: 'subjects', label: '热门学科' },
  { view: 'popular', label: '近期热门' },
];

interface HomeRequestPanelsProps {
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
  profileMissingFields: string[];
  buildUploadLink: (item: MaterialRequestItem) => string;
  onFollowRequest: (item: MaterialRequestItem) => void;
}

export default function HomeRequestPanels({
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
  profileMissingFields,
  buildUploadLink,
  onFollowRequest,
}: HomeRequestPanelsProps) {
  const profileIncomplete = profileMissingFields.length > 0;
  const profileCompletionHint = profileIncomplete
    ? `个人信息待完善：${profileMissingFields.join('、')}`
    : '完善个人主页';
  const [activeDiscoveryView, setActiveDiscoveryView] = useState<HomeDiscoveryView>(HOME_DISCOVERY_DEFAULT_VIEW);
  const [emailCopyState, setEmailCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const handleCopyEmail = useCallback(async () => {
    const copied = await copyToClipboard(COOPERATION_EMAIL);
    setEmailCopyState(copied ? 'copied' : 'failed');
    window.setTimeout(() => setEmailCopyState('idle'), 2000);
  }, []);

  return (
    <div className={`home-dual-panel ${styles.panels}`} id="home-requests">
      <section className="card request-card">
        <div className={`materials-header home-discovery-header ${styles.discoveryHeader}`}>
            <h2 className="card-title">
              {DISCOVERY_TABS.find((tab) => tab.view === activeDiscoveryView)?.label}
            </h2>
            <div className="home-discovery-tabs" role="tablist" aria-label="首页发现内容">
              {DISCOVERY_TABS.map((tab) => <button
                key={tab.view} id={`home-discovery-tab-${tab.view}`} type="button" role="tab"
                aria-selected={activeDiscoveryView === tab.view} aria-controls="home-discovery-panel"
                className={activeDiscoveryView === tab.view ? 'active' : ''}
                onClick={() => setActiveDiscoveryView(tab.view)}
              >{tab.label}</button>)}
            </div>
          <div className="request-header-actions">
            {activeDiscoveryView === 'requests' ? (
              <Link className="button primary small" href="/requests/new">
                我要购买
              </Link>
            ) : activeDiscoveryView === 'popular' ? (
              <button className="button primary small" type="button" onClick={onBrowseMaterials}>
                全部资料
              </button>
            ) : <button className="button primary small" type="button" onClick={onBrowseSubjects}>全部学科</button>}
          </div>
        </div>
        <div className="request-list-wrapper" id="home-discovery-panel" role="tabpanel" aria-labelledby={`home-discovery-tab-${activeDiscoveryView}`}>
          {activeDiscoveryView === 'requests' ? (
            <>
              {requestLoading && <p className="help-text">加载中...</p>}
              {requestError && <p className="error-text">{requestError}</p>}
              {requestNotice && (
                <p className={requestNotice.type === 'error' ? 'error-text' : 'success-text'}>
                  {requestNotice.text}
                </p>
              )}
              {!requestLoading && requestItems.length === 0 ? (
                <div className="empty-state">暂无求购需求，可以切换查看近期热门资料。</div>
              ) : (
                <ul className="request-list">
                  {requestItems.map((item) => {
                    const title = item.course || '求购需求';
                    const detailLink = `/requests/${item.id}`;
                    const budgetLabel = item.budget != null ? `预算 ¥${item.budget}` : '预算 待议';
                    const fundedLabel =
                      item.fundedAmount != null && item.fundedAmount > 0 ? `已筹 ¥${item.fundedAmount}` : '已筹 待议';
                    const canRespond = (item.responseCount ?? 0) === 0 || Boolean(item.responded);
                    return (
                      <li key={item.id} className="request-item">
                        <div className="request-title-row">
                          <div className="request-title">
                            <Link href={detailLink}>{title}</Link>
                          </div>
                          <div className="request-action-row">
                            {item.owner ? (
                              <Link className="button ghost small" href={detailLink}>
                                查看
                              </Link>
                            ) : (
                              <>
                                <button className="button primary small" type="button" onClick={() => onFollowRequest(item)}>
                                  跟购
                                </button>
                                {canRespond ? (
                                  <Link className="button ghost small" href={buildUploadLink(item)}>
                                    应答
                                  </Link>
                                ) : (
                                  <span className="help-text">已有应答</span>
                                )}
                                <Link className="button ghost small" href={detailLink}>
                                  查看
                                </Link>
                              </>
                            )}
                          </div>
                        </div>
                        <div className="request-footer">
                          <span className="request-footer__tag request-footer__budget">{budgetLabel}</span>
                          {item.creatorFloor != null && <span className="request-footer__tag">跟购底价 ¥{item.creatorFloor}</span>}
                          <span className="request-footer__tag request-footer__funded">{fundedLabel}</span>
                          <span className="request-footer__tag request-footer__responses">应答 {item.responseCount ?? 0}</span>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
              {leaderboardItems.length > 0 && (
                <div className="request-leaderboard">
                  <div className="request-leaderboard__title">
                    求购榜 <span className="request-leaderboard__hint">按已筹金额</span>
                  </div>
                  <ul className="request-leaderboard__list">
                    {leaderboardItems.map((item, index) => {
                      const title = item.course || '求购需求';
                      const fundedLabel =
                        item.fundedAmount != null && item.fundedAmount > 0 ? `已筹 ¥${item.fundedAmount}` : '待议';
                      return (
                        <li key={item.id} className="request-leaderboard__item">
                          <span className="request-leaderboard__rank">{index + 1}</span>
                          <Link href={`/requests/${item.id}`}>{title}</Link>
                          <span className="request-leaderboard__amount">{fundedLabel}</span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </>
          ) : activeDiscoveryView === 'popular' ? (
            popularItems.length === 0 ? (
              <div className="empty-state">暂无热门资料。</div>
            ) : (
              <ol className="home-popular-list">
                {popularItems.map((item, index) => {
                  const majorLabel = formatMajorDisplay(item.major);
                  const context = [item.school, item.college, majorLabel].filter(Boolean).join(' · ');
                  return (
                    <li key={item.id} className="home-popular-item">
                      <span className={`home-popular-rank ${index < 3 ? 'is-top' : ''}`}>{index + 1}</span>
                      <div className="home-popular-copy">
                        <Link href={materialPath(item.id, item.title)}>{item.title}</Link>
                        <span>{context || '资料信息待完善'}</span>
                      </div>
                      <span className="home-popular-downloads">下载 {item.downloadCount ?? 0}</span>
                    </li>
                  );
                })}
              </ol>
            )
          ) : (
            <>
              <p className={styles.snapshot}>累计下载排行 · 更新于 {formatDate(subjectsUpdatedAt)}</p>
              {subjectRanks.length === 0 ? <div className="empty-state">暂无学科资料。</div> : <ol className={styles.subjectList} aria-label="热门学科排行">
                {subjectRanks.map((subject, index) => <li key={subject.id}>
                  <button type="button" className={styles.subjectButton} onClick={() => onOpenSubject(subject.id)} aria-label={`查看${subject.name}，${subject.materialCount}份资料`}>
                    <span className={`home-popular-rank ${index < 3 ? 'is-top' : ''}`}>{index + 1}</span>
                    <span className={styles.subjectCopy}><strong>{subject.name}</strong><span>{formatNumber(subject.materialCount)} 份资料</span></span>
                    <span className={styles.subjectDownloads}><strong>{formatNumber(subject.downloadCount)}</strong><span>累计下载</span></span>
                    <ChevronRight size={16} aria-hidden="true" />
                  </button>
                </li>)}
              </ol>}
            </>
          )}
        </div>
      </section>

      <section className={`card ${styles.cooperationCard}`} aria-label="合作招募">
        <div className="materials-header">
          <div>
            <h2 className="card-title">合作招募</h2>
          </div>
          <div className="request-header-actions">
            <Link
              className={`button primary small profile-completion-link${profileIncomplete ? ' is-incomplete' : ''}`}
              href="/me#profile"
              aria-label={profileCompletionHint}
              title={profileCompletionHint}
            >
              <span>完善主页</span>
              {profileIncomplete ? (
                <span className="profile-completion-link__badge" aria-hidden="true">
                  待完善
                </span>
              ) : null}
            </Link>
          </div>
        </div>
        <div className="home-cooperation">
          <p>资料共建、校园合作或技术协作，欢迎邮件联系。</p>
          <div className="home-cooperation__contact">
            <div>
              <span>联系邮箱</span>
              <a href={`mailto:${COOPERATION_EMAIL}`}>{COOPERATION_EMAIL}</a>
            </div>
            <button className="button ghost small" type="button" onClick={handleCopyEmail}>
              <Copy size={16} aria-hidden="true" />{emailCopyState === 'copied' ? '已复制' : '复制邮箱'}
            </button>
          </div>
          <span className="home-cooperation__status" role="status" aria-live="polite">
            {emailCopyState === 'failed' ? '复制失败，请手动复制邮箱。' : ''}
          </span>
        </div>
      </section>
    </div>
  );
}
