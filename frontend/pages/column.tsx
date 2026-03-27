import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ColumnArticleCard from '../components/ColumnArticleCard';
import NavBar from '../components/NavBar';
import { fetchColumnPosts, fetchColumnPostsClient } from '../lib/api';
import { getRequestOrigin } from '../lib/apiBase';
import { readSession } from '../lib/auth';
import { buildExperienceUploadPath } from '../lib/column';
import { MaterialListItem, PaginationMeta } from '../types/material';
import { SessionUser } from '../types/user';

const COLUMN_SCROLL_STATE_KEY = 'studyhub:column:scroll-state';

const COLUMN_NAV_ITEMS = [
  { id: 'column-overview', label: '专栏总览' },
  { id: 'column-latest', label: '最新内容' },
  { id: 'column-editorial', label: '进阶入口' },
  { id: 'column-roadmap', label: '栏目规划' },
] as const;

const COLUMN_ENTRIES = [
  {
    key: 'experience',
    title: '经验心得',
    status: '开放投稿',
    tag: '经验分享',
    type: 'community',
  },
  {
    key: 'grad-school',
    title: '保研面经',
    status: '开放投稿',
    tag: '保研面经',
    type: 'community',
  },
  {
    key: 'career',
    title: '求职面经',
    status: '开放投稿',
    tag: '求职面经',
    type: 'community',
  },
  {
    key: 'postgrad-exam',
    title: '考研攻略',
    status: '开放投稿',
    tag: '考研攻略',
    type: 'community',
  },
  {
    key: 'overseas',
    title: '留学指南',
    status: '开放投稿',
    tag: '留学指南',
    type: 'community',
  },
  {
    key: 'leetcode',
    title: 'LeetCode 解析',
    status: '独立更新',
    tag: 'LeetCode解析',
    type: 'editorial',
  },
  {
    key: 'llm',
    title: 'LLM 入门',
    status: '独立更新',
    tag: 'LLM入门',
    type: 'editorial',
  },
] as const;

type ColumnEntry = (typeof COLUMN_ENTRIES)[number];
type ColumnTopicKey = ColumnEntry['key'];
const DEFAULT_COLUMN_TOPIC: ColumnTopicKey = 'experience';
const COMMUNITY_ENTRIES = COLUMN_ENTRIES.filter((entry) => entry.type === 'community');
const EDITORIAL_ENTRIES = COLUMN_ENTRIES.filter((entry) => entry.type === 'editorial');

const COLUMN_TRACKS = [
  {
    key: 'guide',
    title: '学习攻略',
    status: '筹备中',
    description: '适合放复习路线、课程避坑、选课建议、工具教程与成长路径。',
  },
  {
    key: 'campus',
    title: '校园专题',
    status: '筹备中',
    description: '可进一步承接竞赛备赛、实验复盘、课程项目与校内资源整合。',
  },
] as const;

interface ColumnPageProps {
  user: SessionUser | null;
  posts: MaterialListItem[];
  meta: PaginationMeta;
  initialTopic: string;
}

const extractPostTags = (post: MaterialListItem) => (post.tags || []).filter((tag) => tag && tag !== '经验分享');
const normalizeTopicKey = (value: unknown): ColumnTopicKey =>
  COLUMN_ENTRIES.some((entry) => entry.key === value) ? (value as ColumnTopicKey) : 'experience';
type TopicDataMap = Partial<Record<ColumnTopicKey, { posts: MaterialListItem[]; meta: PaginationMeta }>>;

const COLUMN_SKELETON_COUNT = 4;

const ColumnHeroIcon = () => (
  <span className="column-hero__icon" aria-hidden="true">
    <svg viewBox="0 0 24 24" role="img" focusable="false">
      <path d="M6 4h9l3 3v13H6z" />
      <path d="M15 4v4h4" />
      <path d="M9 12h6" />
      <path d="M9 16h4" />
    </svg>
  </span>
);

const ColumnListSkeleton = () => (
  <ul className="column-article-list column-article-list--skeleton" aria-hidden="true">
    {Array.from({ length: COLUMN_SKELETON_COUNT }).map((_, index) => (
      <li className="column-article-card column-article-card--skeleton" key={`column-skeleton-${index}`}>
        <div className="column-article-card__shell">
          <div className="column-skeleton-line short" />
          <div className="column-skeleton-line title" />
          <div className="column-skeleton-line text" />
          <div className="column-skeleton-line text wide" />
          <div className="column-skeleton-tags">
            <span className="column-skeleton-chip" />
            <span className="column-skeleton-chip small" />
          </div>
          <div className="column-skeleton-footer">
            <span className="column-skeleton-chip stat" />
            <span className="column-skeleton-chip stat" />
            <span className="column-skeleton-chip stat" />
          </div>
        </div>
      </li>
    ))}
  </ul>
);

export default function ColumnPage({ user, posts, meta, initialTopic }: ColumnPageProps) {
  const router = useRouter();
  const [activeSection, setActiveSection] = useState<string>('column-overview');
  const [comingSoonEntry, setComingSoonEntry] = useState<ColumnEntry | null>(null);
  const [selectedTopic, setSelectedTopic] = useState<ColumnTopicKey>(normalizeTopicKey(initialTopic));
  const [topicData, setTopicData] = useState<TopicDataMap>({
    [normalizeTopicKey(initialTopic)]: { posts, meta },
  });
  const [topicLoading, setTopicLoading] = useState<ColumnTopicKey | null>(null);
  const topicDataRef = useRef<TopicDataMap>(topicData);
  const requestControllersRef = useRef<Partial<Record<ColumnTopicKey, AbortController>>>({});
  const selectedEntry = useMemo(
    () => COLUMN_ENTRIES.find((entry) => entry.key === selectedTopic) || COLUMN_ENTRIES[0],
    [selectedTopic]
  );
  const visiblePosts = useMemo(() => topicData[selectedTopic]?.posts ?? [], [topicData, selectedTopic]);
  const isCommunityColumn = selectedEntry.type === 'community';
  const topTags = useMemo(() => {
    const counts = new Map<string, number>();
    visiblePosts.forEach((post) => {
      extractPostTags(post).forEach((tag) => {
        counts.set(tag, (counts.get(tag) || 0) + 1);
      });
    });
    return Array.from(counts.entries())
      .sort((left, right) => right[1] - left[1])
      .slice(0, 8);
  }, [visiblePosts]);

  useEffect(() => {
    topicDataRef.current = topicData;
  }, [topicData]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const sections = COLUMN_NAV_ITEMS.map((item) => document.getElementById(item.id)).filter(
      (item): item is HTMLElement => Boolean(item)
    );
    if (!sections.length) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top);
        if (visible.length > 0) {
          setActiveSection(visible[0].target.id);
        }
      },
      { rootMargin: '-24% 0px -56% 0px', threshold: [0.15, 0.4, 0.7] }
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  const ensureTopicData = useCallback(
    async (topic: ColumnTopicKey, options: { force?: boolean; cancelOthers?: boolean } = {}) => {
      if (!options.force && topicDataRef.current[topic]) return;
      if (options.cancelOthers) {
        (Object.keys(requestControllersRef.current) as ColumnTopicKey[]).forEach((key) => {
          if (key !== topic) {
            requestControllersRef.current[key]?.abort();
            delete requestControllersRef.current[key];
          }
        });
      }
      requestControllersRef.current[topic]?.abort();
      const controller = new AbortController();
      requestControllersRef.current[topic] = controller;
      setTopicLoading(topic);
      try {
        const data = await fetchColumnPostsClient({ topic, page: 1, size: 12 }, { signal: controller.signal });
        if (requestControllersRef.current[topic] !== controller) return;
        setTopicData((prev) => ({
          ...prev,
          [topic]: {
            posts: data.items || [],
            meta: data.meta,
          },
        }));
      } catch (error) {
        if (error instanceof Error && error.name === 'AbortError') {
          return;
        }
        // eslint-disable-next-line no-console
        console.warn('Failed to load column topic posts', topic, error);
      } finally {
        if (requestControllersRef.current[topic] === controller) {
          delete requestControllersRef.current[topic];
          setTopicLoading((current) => (current === topic ? null : current));
        }
      }
    },
    []
  );

  useEffect(() => {
    if (!router.isReady) return;
    const queryTopic = normalizeTopicKey(
      typeof router.query.topic === 'string' ? router.query.topic : DEFAULT_COLUMN_TOPIC
    );
    setSelectedTopic((prev) => (prev === queryTopic ? prev : queryTopic));
    void ensureTopicData(queryTopic);
  }, [router.isReady, router.query.topic, ensureTopicData]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const raw = window.sessionStorage.getItem(COLUMN_SCROLL_STATE_KEY);
    if (!raw) return;
    try {
      const state = JSON.parse(raw) as { y?: number; topic?: string };
      const stateTopic = normalizeTopicKey(state.topic);
      if (typeof state.y === 'number' && stateTopic === selectedTopic) {
        window.requestAnimationFrame(() => {
          window.scrollTo({ top: state.y, behavior: 'auto' });
        });
      }
    } catch {
      // ignore
    } finally {
      window.sessionStorage.removeItem(COLUMN_SCROLL_STATE_KEY);
    }
  }, [selectedTopic]);

  useEffect(() => {
    const preloadTopics = COMMUNITY_ENTRIES.map((entry) => entry.key).filter((topic) => topic !== selectedTopic && !topicData[topic]);
    if (!preloadTopics.length) return;
    const timer = window.setTimeout(() => {
      preloadTopics.slice(0, 2).forEach((topic) => {
        void ensureTopicData(topic);
      });
    }, 220);
    return () => window.clearTimeout(timer);
  }, [selectedTopic, topicData, ensureTopicData]);

  useEffect(
    () => () => {
      (Object.values(requestControllersRef.current) as AbortController[]).forEach((controller) => controller.abort());
      requestControllersRef.current = {};
    },
    []
  );

  const jumpToSection = (id: string) => {
    if (typeof window === 'undefined') return;
    const target = document.getElementById(id);
    if (!target) return;
    setActiveSection(id);
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const handleEntryClick = (topic: ColumnTopicKey) => {
    if (topic === selectedTopic) return;
    setSelectedTopic(topic);
    setActiveSection('column-latest');
    router.replace(
      {
        pathname: '/column',
        query: topic === 'experience' ? {} : { topic },
      },
      undefined,
      { scroll: false, shallow: true }
    );
    void ensureTopicData(topic, { cancelOthers: true });
  };

  const handleOpenDetail = () => {
    if (typeof window === 'undefined') return;
    window.sessionStorage.setItem(
      COLUMN_SCROLL_STATE_KEY,
      JSON.stringify({
        y: window.scrollY,
        topic: selectedTopic,
      })
    );
  };

  const openComingSoonModal = (entry: ColumnEntry) => {
    setComingSoonEntry(entry);
  };

  return (
    <>
      <NavBar user={user} />
      <main className="container column-page">
        <div className="me-layout column-layout">
          <aside className="me-sidebar column-sidebar">
            <div className="me-sidebar__brand">学汇专栏</div>
            <div className="me-sidebar__group">
              <div className="me-sidebar__label">栏目导航</div>
              <nav className="me-sidebar__items" aria-label="学汇专栏导航">
                {COLUMN_NAV_ITEMS.map((item) => (
                  <a
                    key={item.id}
                    href={`#${item.id}`}
                    className={`me-sidebar__item${activeSection === item.id ? ' active' : ''}`}
                    onClick={(event) => {
                      event.preventDefault();
                      jumpToSection(item.id);
                    }}
                  >
                    <span className="me-sidebar__indicator" />
                    <span className="me-sidebar__text">{item.label}</span>
                  </a>
                ))}
              </nav>
            </div>
          </aside>

          <div className="column-main">
            <section className="card me-hero column-hero" id="column-overview">
              <div className="me-hero__inner">
                <div className="me-hero__intro">
                  <div className="me-hero__eyebrow">StudyHub 内容阅读区</div>
                  <div className="me-hero__title-row">
                    <h1 className="me-hero__title column-hero__title">
                      <ColumnHeroIcon />
                      <span>学汇专栏</span>
                    </h1>
                  </div>
                  <p className="me-hero__subtitle">面向长期积累的学习内容栏目。</p>
                </div>
              </div>
              <div className="me-hero__meta column-hero__meta">
                <span>当前开放经验心得投稿，后续将逐步补齐面经、题解与学习攻略等方向。</span>
              </div>
            </section>

            <section className="card column-section-card" id="column-latest">
              <div className="materials-header">
                <div>
                  <p className="column-section-overline">LATEST CONTENT</p>
                  <h2 className="card-title">
                    最新内容
                    <svg className="title-icon" viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M6 4h9l3 3v13H6z" fill="none" stroke="currentColor" strokeWidth="1.6" />
                      <path d="M15 4v4h4" fill="none" stroke="currentColor" strokeWidth="1.6" />
                      <path d="M9 12h6M9 16h4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                    </svg>
                  </h2>
                </div>
                <div className="materials-header__actions">
                  {isCommunityColumn && (
                    <Link className="button primary small column-submit-button" href={buildExperienceUploadPath(selectedEntry.key)}>
                      我要投稿
                    </Link>
                  )}
                </div>
              </div>
              <div className="column-latest-tabs" role="tablist" aria-label="最新内容模式切换">
                {COMMUNITY_ENTRIES.map((entry) => (
                  <button
                    key={entry.key}
                    type="button"
                    role="tab"
                    aria-selected={selectedTopic === entry.key}
                    className={`column-latest-tab${selectedTopic === entry.key ? ' active' : ''}`}
                    onClick={() => handleEntryClick(entry.key)}
                  >
                    {entry.title}
                  </button>
                ))}
              </div>

              {topicLoading === selectedTopic && visiblePosts.length === 0 ? (
                <ColumnListSkeleton />
              ) : visiblePosts.length === 0 ? (
                <div className="empty-state">
                  <span>{selectedEntry.title} 暂无内容，欢迎成为第一篇投稿。</span>
                </div>
              ) : (
                <ul className="column-article-list">
                  {visiblePosts.map((post) => (
                    <ColumnArticleCard key={post.id} post={post} onOpenDetail={handleOpenDetail} />
                  ))}
                </ul>
              )}
            </section>

            <section className="card column-section-card" id="column-editorial">
              <div className="materials-header">
                <div>
                  <p className="column-section-overline">EDITORIAL ENTRIES</p>
                  <h2 className="card-title">
                    进阶入口
                    <svg className="title-icon" viewBox="0 0 24 24" aria-hidden="true">
                      <path
                        d="M4 7h16M4 12h16M4 17h10"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                      />
                    </svg>
                  </h2>
                </div>
              </div>
              <div className="column-editorial-grid">
                {EDITORIAL_ENTRIES.map((entry) => (
                  <article key={entry.key} className="column-editorial-card">
                    <div className="column-editorial-card__status">{entry.status}</div>
                    <h3>{entry.title}</h3>
                    <p>独立内容线，适合持续沉淀题解笔记与入门专题。</p>
                    <button type="button" className="button ghost small" onClick={() => openComingSoonModal(entry)}>
                      查看入口
                    </button>
                  </article>
                ))}
              </div>
            </section>

            <section className="card column-section-card" id="column-roadmap">
              <div className="materials-header">
                <div>
                  <p className="column-section-overline">ROADMAP</p>
                  <h2 className="card-title">
                    栏目规划
                    <svg className="title-icon" viewBox="0 0 24 24" aria-hidden="true">
                      <path
                        d="M4 7h16M4 12h10M4 17h7"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                      />
                    </svg>
                  </h2>
                  <p className="help-text">这一页不仅是经验内容入口，也会逐步承接更多偏阅读、偏沉淀、偏图文的学习内容。</p>
                </div>
              </div>

              <div className="column-track-grid">
                {COLUMN_TRACKS.map((track) => (
                  <article key={track.key} className={`column-track-card ${track.status === '已开放' ? 'active' : ''}`}>
                    <div className="column-track-card__status">{track.status}</div>
                    <h3>{track.title}</h3>
                    <p>{track.description}</p>
                  </article>
                ))}
              </div>

              {topTags.length > 0 && (
                <div className="column-tag-panel">
                  <div className="column-tag-panel__label">当前内容高频标签</div>
                  <div className="column-tag-cloud">
                    {topTags.map(([tag, count]) => (
                      <span key={tag} className="column-tag-cloud__item">
                        #{tag}
                        <em>{count}</em>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </section>
          </div>
        </div>
      </main>
      {comingSoonEntry && (
        <div className="modal-mask" onClick={() => setComingSoonEntry(null)}>
          <div
            className="modal-card column-coming-modal"
            role="dialog"
            aria-modal="true"
            aria-label={`${comingSoonEntry.title} 筹备中`}
            onClick={(event) => event.stopPropagation()}
          >
            <h2>{comingSoonEntry.title}</h2>
            <p>该入口正在筹备中，内容整理完成后会在这里开放。</p>
            <div className="column-coming-modal__actions">
              <button type="button" className="button primary" onClick={() => setComingSoonEntry(null)}>
                我知道了
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export const getServerSideProps: GetServerSideProps<ColumnPageProps> = async (ctx) => {
  const session = readSession(ctx.req);
  const origin = getRequestOrigin(ctx.req);
  const defaultMeta: PaginationMeta = { page: 1, size: 12, total: 0 };
  const topic = normalizeTopicKey(typeof ctx.query.topic === 'string' ? ctx.query.topic : 'experience');
  const result = await (async () => {
    try {
      const data = await fetchColumnPosts(
        {
          topic,
          page: 1,
          size: 12,
        },
        session.token || undefined,
        origin
      );
      return {
        posts: data.items || [],
        meta: data.meta || defaultMeta,
      };
    } catch (error) {
      // eslint-disable-next-line no-console
      console.warn('Failed to fetch column posts', error);
      return {
        posts: [] as MaterialListItem[],
        meta: defaultMeta,
      };
    }
  })();

  return {
    props: {
      user: session.user,
      posts: result.posts,
      meta: result.meta,
      initialTopic: topic,
    },
  };
};
