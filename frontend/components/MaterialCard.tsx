import type React from 'react';
import Link from 'next/link';
import { MaterialListItem } from '../types/material';
import { COURSE_CATEGORY_LABELS, CourseCategoryValue, normalizeCourseCategory } from '../constants/metadata';
import { formatMajorDisplay } from '../lib/major';
import { materialPath, userPath } from '../lib/slug';
import minStyles from '../styles/HomeMinimal.module.css';

interface Props {
  material: MaterialListItem;
  selectable?: boolean;
  checked?: boolean;
  onToggle?: (materialId: number, next: boolean) => void;
  variant?: 'grid' | 'list' | 'minimal';
  orderLabel?: string;
}

const priceText = (material: MaterialListItem) => {
  if (material.free) return '免费';
  const price = typeof material.price === 'number' ? material.price : 0;
  return `¥${price.toFixed(2)}`;
};

const formatTitleForDisplay = (title?: string | null) => {
  return title || '';
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

export default function MaterialCard({
  material,
  selectable,
  checked,
  onToggle,
  variant = 'grid',
  orderLabel,
}: Props) {
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
  const publisherHref = publisherId ? userPath(publisherId, publisherName) : '';
  const overlayLabel = isExperienceTag ? `阅读《${material.title}》` : `查看资料《${material.title}》`;
  const handleToggle = (event: React.MouseEvent | React.ChangeEvent) => {
    event.stopPropagation();
    event.preventDefault();
    if (onToggle) {
      onToggle(material.id, !checked);
    }
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

  if (variant === 'minimal') {
    const contextText = [
      material.college || material.school || '未知学校',
      displayDiscipline,
      material.gradeValue,
    ]
      .filter(Boolean)
      .join(' · ');

    const minimalClasses = [
      'material-card',
      'minimal-variant',
      'material-card-clickable',
      minStyles.minimalRow,
      isExperienceTag ? 'material-card--experience' : '',
      checked ? `selected ${minStyles.minimalRowSelected}` : '',
    ]
      .filter(Boolean)
      .join(' ');

    return (
      <li data-material-id={material.id} className={minimalClasses}>
        <Link className="material-card__overlay-link" href={materialHref} aria-label={overlayLabel} prefetch={false} />
        {selectable && (
          <button
            type="button"
            className={`${minStyles.rowCheck}${checked ? ` ${minStyles.rowCheckChecked}` : ''}`}
            aria-pressed={checked}
            aria-label={checked ? '取消选择资料' : '选择资料'}
            onClick={handleToggle}
          >
            {checked ? (
              <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M2.5 6.2 5 8.7 9.5 3.5" />
              </svg>
            ) : null}
          </button>
        )}
        <div className={minStyles.rowBody}>
          <div className={minStyles.rowTitleLine}>
            {isExperienceTag ? <span className={minStyles.rowBadge}>专栏</span> : null}
            <h3 className={minStyles.rowTitle} title={material.title}>
              {displayTitle}
            </h3>
          </div>
          <div className={minStyles.rowMeta}>
            <span>
              {contextText}
              {' · '}
              {publisherId ? (
                <Link href={publisherHref} className={minStyles.rowPublisher} prefetch={false}>
                  {publisherName}
                </Link>
              ) : (
                publisherName
              )}
            </span>
            {copyrightOwner ? <span>版权：{copyrightOwner}</span> : null}
            {displayedTags.length > 0 ? (
              <span className={minStyles.rowTags}>
                {displayedTags.map((tag) => (
                  <Link key={tag} className={minStyles.rowTag} href={`/?tag=${encodeURIComponent(tag)}`} prefetch={false}>
                    #{tag}
                  </Link>
                ))}
                {extraTagCount > 0 ? <span className={minStyles.rowTag}>+{extraTagCount}</span> : null}
              </span>
            ) : null}
          </div>
        </div>
        <div className={minStyles.rowMetrics}>
          {!isExperienceTag && material.ratingAvg ? (
            <span className={minStyles.rowStat}>评分 {material.ratingAvg.toFixed(1)}</span>
          ) : null}
          {isExperienceTag
            ? viewCount > 0 && <span className={minStyles.rowStat}>{viewCount} 阅读</span>
            : downloadCount > 0 && <span className={minStyles.rowStat}>{downloadCount} 下载</span>}
          <span className={minStyles.rowPrice}>{isExperienceTag ? '专栏' : priceText(material)}</span>
        </div>
      </li>
    );
  }

  if (variant === 'list') {
    return (
      <li className={listItemClasses}>
        <Link className="material-card__overlay-link" href={materialHref} aria-label={overlayLabel} prefetch={false} />
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
          <div className="material-list-link">
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
                <Link href={publisherHref} className="text-button" prefetch={false}>
                  {publisherName}
                </Link>
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
          </div>
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
      data-material-id={material.id}
      className={`material-card material-card-clickable ${isExperienceTag ? 'material-card--experience' : ''} ${checked ? 'selected' : ''} ${
        selectable ? 'selectable' : ''
      }`}
    >
      <Link className="material-card__overlay-link" href={materialHref} aria-label={overlayLabel} prefetch={false} />
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
              <Link href={publisherHref} className="text-button" prefetch={false}>
                {publisherName}
              </Link>
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
