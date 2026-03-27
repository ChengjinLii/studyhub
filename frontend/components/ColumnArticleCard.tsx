import Link from 'next/link';
import { materialPath, userPath } from '../lib/slug';
import { MaterialListItem } from '../types/material';

interface Props {
  post: MaterialListItem;
  onOpenDetail?: () => void;
}

const COMMUNITY_TAG_SET = new Set([
  '经验分享',
  '保研面经',
  '求职面经',
  '考研攻略',
  '留学指南',
  '考研心得',
  '留学心得',
]);

const normalizeMarkdownText = (value?: string | null) => {
  const raw = value?.trim() || '';
  if (!raw) return '';
  return raw
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/^>\s?/gm, '')
    .replace(/^#{1,6}\s*/gm, '')
    .replace(/[*_~]/g, '')
    .replace(/\|/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
};

const clampExcerpt = (value?: string | null) => {
  const trimmed = normalizeMarkdownText(value);
  if (!trimmed) return '这篇内容正在整理摘要，进入详情页可查看完整正文与更多上下文。';
  if (trimmed.length <= 116) return trimmed;
  return `${trimmed.slice(0, 115)}…`;
};

const formatPublishTime = (value?: string | null) => {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  if (diffMs <= 0) return `${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')}`;
  const dayMs = 24 * 60 * 60 * 1000;

  const isSameDay =
    now.getFullYear() === date.getFullYear() &&
    now.getMonth() === date.getMonth() &&
    now.getDate() === date.getDate();
  if (isSameDay) {
    const minutes = Math.max(1, Math.floor(diffMs / 60000));
    if (minutes < 60) return `${minutes} 分钟前`;
    const hours = Math.floor(minutes / 60);
    return `${hours} 小时前`;
  }

  if (now.getFullYear() === date.getFullYear()) {
    const days = Math.floor(diffMs / dayMs);
    if (days < 30) {
      return `${Math.max(1, days)} 天前`;
    }
    const months =
      (now.getFullYear() - date.getFullYear()) * 12 + now.getMonth() - date.getMonth();
    const safeMonths = Math.max(1, months);
    return `${safeMonths} 个月前`;
  }

  return `${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')}`;
};

export default function ColumnArticleCard({ post, onOpenDetail }: Props) {
  const publisherName = post.uploaderNickname || post.uploaderUsername || '匿名同学';
  const excerpt = clampExcerpt(post.description);
  const publishTime = formatPublishTime(post.createdAt);
  const rawTags = (post.tags || []).filter((tag) => tag && tag.trim());
  const communityMode = rawTags.some((tag) => COMMUNITY_TAG_SET.has(tag));
  const normalizedCommunityTags = rawTags
    .filter((tag) => COMMUNITY_TAG_SET.has(tag))
    .map((tag) => {
      if (tag === '经验分享') return '经验心得';
      if (tag === '考研心得') return '考研攻略';
      if (tag === '留学心得') return '留学指南';
      return tag;
    });
  const uniqueCommunityTags = Array.from(new Set(normalizedCommunityTags));
  const primaryCommunityTag =
    uniqueCommunityTags.find((tag) => tag === '保研面经') ||
    uniqueCommunityTags.find((tag) => tag === '求职面经') ||
    uniqueCommunityTags.find((tag) => tag === '考研攻略') ||
    uniqueCommunityTags.find((tag) => tag === '留学指南') ||
    '经验心得';
  const visibleTags = communityMode
    ? [primaryCommunityTag]
    : rawTags.filter((tag) => tag !== '经验分享').slice(0, 2);
  const hiddenTagCount = communityMode ? 0 : Math.max(rawTags.length - visibleTags.length, 0);

  return (
    <li className="column-article-card">
      <div className="column-article-card__shell">
        <div className="column-article-card__eyebrow">
          <div className="column-article-card__meta">
            {publishTime && <span>{publishTime}</span>}
          </div>
        </div>

        <Link className="column-article-card__title-link" href={materialPath(post.id, post.title)} onClick={onOpenDetail}>
          <h3 className="column-article-card__title">{post.title}</h3>
        </Link>

        <Link className="column-article-card__excerpt-link" href={materialPath(post.id, post.title)} onClick={onOpenDetail}>
          <p className="column-article-card__excerpt">{excerpt}</p>
        </Link>

        {(visibleTags.length > 0 || hiddenTagCount > 0) && (
          <div className="column-article-card__topics">
            {visibleTags.map((tag) => (
              <span key={tag} className="column-article-card__topic">
                #{tag}
              </span>
            ))}
            {hiddenTagCount > 0 && (
              <span className="column-article-card__topic column-article-card__topic--count">+{hiddenTagCount}</span>
            )}
          </div>
        )}
        <div className="column-article-card__publisher-line">
          <span>发布者：</span>
          {post.uploaderId ? (
            <Link className="column-article-card__author-link" href={userPath(post.uploaderId, publisherName)}>
              {publisherName}
            </Link>
          ) : (
            <span className="column-article-card__author-name">{publisherName}</span>
          )}
        </div>

        <div className="column-article-card__footer">
          <div className="column-article-card__stats">
            <span className="column-article-card__metric" aria-label="查看">
              <svg className="column-article-card__metric-icon" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
              </svg>
              <span className="column-article-card__metric-value">{post.viewCount ?? 0}</span>
            </span>
            <span className="column-article-card__metric" aria-label="评论">
              <svg className="column-article-card__metric-icon" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span className="column-article-card__metric-value">{post.commentCount ?? 0}</span>
            </span>
            <span className="column-article-card__metric" aria-label="点赞">
              <svg className="column-article-card__metric-icon" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3z"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <path
                  d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span className="column-article-card__metric-value">{post.likeCount ?? 0}</span>
            </span>
          </div>
          <Link
            className="column-article-card__readmore"
            href={materialPath(post.id, post.title)}
            aria-label={`阅读 ${post.title}`}
            onClick={onOpenDetail}
          >
              <span className="column-article-card__readmore-text">阅读全文</span>
              <svg className="column-article-card__readmore-icon" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M7 12h10M13 6l6 6-6 6"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.7"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
          </Link>
        </div>
      </div>
    </li>
  );
}
