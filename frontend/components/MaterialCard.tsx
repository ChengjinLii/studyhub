import type React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { MaterialListItem } from '../types/material';
import { COURSE_CATEGORY_LABELS, CourseCategoryValue, normalizeCourseCategory } from '../constants/metadata';
import { formatMajorDisplay } from '../lib/major';
import { materialPath, userPath } from '../lib/slug';

interface Props {
  material: MaterialListItem;
  selectable?: boolean;
  checked?: boolean;
  onToggle?: (materialId: number, next: boolean) => void;
  variant?: 'grid' | 'list';
  orderLabel?: string;
}

const priceText = (material: MaterialListItem) => {
  if (material.free) return '免费';
  const price = typeof material.price === 'number' ? material.price : 0;
  return `¥${price.toFixed(2)}`;
};

const formatTitleForDisplay = (title?: string | null) => {
  if (!title) return '';
  if (title.length <= 22) {
    return title;
  }
  return `${title.slice(0, 21)}…`;
};

const cardActionLabel = (material: MaterialListItem, isExperience: boolean) => {
  if (isExperience) return '阅读全文';
  if (material.free) return '免费下载';
  return '购买下载';
};

const MaterialStatIcon = ({ name }: { name: 'like' | 'comment' | 'view' | 'download' }) => (
  <svg className="material-icon" viewBox="0 0 24 24" aria-hidden="true">
    <use href={`#studyhub-material-icon-${name}`} />
  </svg>
);

const isNestedInteractiveTarget = (target: EventTarget | null, container: HTMLElement) => {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const interactiveTarget = target.closest('a,button,input,select,textarea,label,[role="button"],[role="link"]');
  return Boolean(interactiveTarget && interactiveTarget !== container);
};

export default function MaterialCard({
  material,
  selectable,
  checked,
  onToggle,
  variant = 'grid',
  orderLabel,
}: Props) {
  const router = useRouter();
  const displayTitle = formatTitleForDisplay(material.title);
  const normalizedCategory: CourseCategoryValue = normalizeCourseCategory(
    material.courseCategory,
    material.generalEducation
  );
  const categoryLabel = COURSE_CATEGORY_LABELS[normalizedCategory];
  const majorDisplay = formatMajorDisplay(material.major);
  const displayDiscipline =
    normalizedCategory === 'MAJOR' ? majorDisplay || material.college || '专业课' : categoryLabel;
  const publisherName = material.uploaderNickname || material.uploaderUsername || '匿名同学';
  const publisherId = material.uploaderId ?? null;
  const copyrightOwner = material.copyrightOwner?.trim();
  const likeCount = material.likeCount ?? 0;
  const commentCount = material.commentCount ?? 0;
  const viewCount = material.viewCount ?? 0;
  const downloadCount = material.downloadCount ?? 0;
  const tagItems = material.tags || [];
  const isExperienceTag = tagItems.includes('经验分享');
  const filteredTags = tagItems.filter((tag) => tag !== '经验分享');
  const displayedTags = filteredTags.slice(0, 3);
  const extraTagCount = Math.max(filteredTags.length - displayedTags.length, 0);
  const materialHref = materialPath(material.id, material.title);
  const handleToggle = (event: React.MouseEvent | React.ChangeEvent) => {
    event.stopPropagation();
    event.preventDefault();
    if (onToggle) {
      onToggle(material.id, !checked);
    }
  };

  const handlePublisherClick = (event: React.MouseEvent) => {
    if (!publisherId) return;
    event.preventDefault();
    event.stopPropagation();
    void router.push(userPath(publisherId, publisherName));
  };

  const handleCardClick = (event: React.MouseEvent<HTMLLIElement>) => {
    if (isNestedInteractiveTarget(event.target, event.currentTarget)) {
      return;
    }
    void router.push(materialHref);
  };

  const handleCardKeyDown = (event: React.KeyboardEvent<HTMLLIElement>) => {
    if (event.currentTarget !== event.target || (event.key !== 'Enter' && event.key !== ' ')) {
      return;
    }
    event.preventDefault();
    void router.push(materialHref);
  };

  const listItemClasses = [
    'material-card',
    'list-variant',
    'material-card-clickable',
    isExperienceTag ? 'material-card--experience' : '',
    checked ? 'selected' : '',
    selectable ? 'selectable' : '',
  ]
    .filter(Boolean)
    .join(' ');

  if (variant === 'list') {
    return (
      <li
        className={listItemClasses}
        role="button"
        tabIndex={0}
        onClick={handleCardClick}
        onKeyDown={handleCardKeyDown}
      >
        {selectable && (
          <button
            type="button"
            className={`material-card__selector ${checked ? 'checked' : ''}`}
            aria-pressed={checked}
            aria-label={checked ? '取消选择资料' : '选择资料'}
            onClick={handleToggle}
          >
            <span />
          </button>
        )}
        <div className="material-list-row">
          <Link href={materialHref} className="material-list-link" prefetch={false}>
            <div className="material-list-title">
              {orderLabel && <span className="order-label">{orderLabel}</span>}
              {isExperienceTag ? (
                <>
                  <span className="badge badge-ghost material-title-prefix">专栏</span>
                  <h3 title={material.title}>{displayTitle}</h3>
                </>
              ) : (
                <h3 title={material.title}>{displayTitle}</h3>
              )}
            </div>
            <p className="material-meta small">
              {material.school || '未知学校'}
              {material.college ? ` · ${material.college}` : ''}
            </p>
            <p className="material-meta small">
              发布者：
              {publisherId ? (
                <button type="button" className="text-button" onClick={handlePublisherClick}>
                  {publisherName}
                </button>
              ) : (
                publisherName
              )}
            </p>
            {copyrightOwner && (
              <p className="material-meta small">版权持有者：{copyrightOwner}</p>
            )}
            <p className="material-meta strong">
              {displayDiscipline}
              {material.gradeValue ? ` · ${material.gradeValue}` : ''}
            </p>
            <div className="material-tags">
              {isExperienceTag && <span className="badge badge-ghost">经验分享</span>}
              {displayedTags.map((tag) => (
                <span key={tag} className="badge badge-outline">
                  #{tag}
                </span>
              ))}
              {extraTagCount > 0 && <span className="badge badge-outline">+{extraTagCount}</span>}
            </div>
          </Link>
          <div className="material-list-meta">
            {isExperienceTag ? (
              <>
                <span className="badge badge-ghost material-reading-tag">专栏文章</span>
                <Link className="material-card__cta" href={materialHref} prefetch={false}>
                  {cardActionLabel(material, isExperienceTag)}
                </Link>
              </>
            ) : (
              <span className={`price-tag ${material.free ? 'free' : ''}`}>{priceText(material)}</span>
            )}
          </div>
        </div>
      </li>
    );
  }

  return (
    <li
      className={`material-card material-card-clickable ${isExperienceTag ? 'material-card--experience' : ''} ${checked ? 'selected' : ''} ${
        selectable ? 'selectable' : ''
      }`}
      role="button"
      tabIndex={0}
      onClick={handleCardClick}
      onKeyDown={handleCardKeyDown}
    >
      {selectable && (
        <button
          type="button"
          className={`material-card__selector ${checked ? 'checked' : ''}`}
          aria-pressed={checked}
          aria-label={checked ? '取消选择资料' : '选择资料'}
          onClick={handleToggle}
        >
          <span />
        </button>
      )}
      <div className="material-card__header">
        <div>
          {isExperienceTag ? (
            <div className="material-title-row">
              <span className="badge badge-ghost material-title-prefix">专栏</span>
              <h3 title={material.title}>{displayTitle}</h3>
            </div>
          ) : (
            <h3 title={material.title}>{displayTitle}</h3>
          )}
          <p className="material-meta">
            {material.school || '未知学校'}
            {material.college ? ` · ${material.college}` : ''}
          </p>
          <p className="material-meta">
            发布者：
            {publisherId ? (
              <button type="button" className="text-button" onClick={handlePublisherClick}>
                {publisherName}
              </button>
            ) : (
              publisherName
            )}
          </p>
          {copyrightOwner && <p className="material-meta">版权持有者：{copyrightOwner}</p>}
          <p className="material-meta strong">
            {displayDiscipline}
            {material.gradeValue ? ` · ${material.gradeValue}` : ''}
          </p>
        </div>
        {isExperienceTag ? (
          <span className="badge badge-ghost material-reading-tag">专栏文章</span>
        ) : (
          <span className={`price-tag ${material.free ? 'free' : ''}`}>{priceText(material)}</span>
        )}
      </div>
      <div className="material-tags">
        {normalizedCategory !== 'MAJOR' && categoryLabel !== '通识课' && (
          <span className="badge badge-ghost">{categoryLabel}</span>
        )}
        {isExperienceTag && <span className="badge badge-ghost">经验分享</span>}
        {filteredTags.map((tag) => (
          <Link key={tag} className="badge badge-outline" href={`/?tag=${encodeURIComponent(tag)}`} prefetch={false}>
            #{tag}
          </Link>
        ))}
      </div>
      {isExperienceTag ? (
        <div className="material-stats material-stats__rating material-stats__experience">
          <span className="material-emoji" aria-label="点赞">
            <MaterialStatIcon name="like" />
            {likeCount}
          </span>
          <span className="material-emoji" aria-label="评论">
            <MaterialStatIcon name="comment" />
            {commentCount}
          </span>
          <span className="material-emoji" aria-label="阅读">
            <MaterialStatIcon name="view" />
            {viewCount}
          </span>
        </div>
      ) : (
        <div className="material-stats material-stats__rating">
          <span>评分：{material.ratingAvg ? material.ratingAvg.toFixed(1) : '--'}</span>
        </div>
      )}
      <div className="material-stats material-stats__actions">
        {!isExperienceTag && (
          <>
            <span className="material-emoji" aria-label="点赞">
              <MaterialStatIcon name="like" />
              {likeCount}
            </span>
            <span className="material-emoji" aria-label="评论">
              <MaterialStatIcon name="comment" />
              {commentCount}
            </span>
            <span className="material-emoji" aria-label="下载">
              <MaterialStatIcon name="download" />
              {downloadCount}
            </span>
          </>
        )}
      </div>
    </li>
  );
}
