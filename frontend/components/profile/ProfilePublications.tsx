import Link from 'next/link';
import { formatDate } from '../../lib/format';
import { marketPath, materialPath } from '../../lib/slug';
import type { UploadItem, MarketListingItem } from '../../types/profile';

export interface ProfilePublicationsProps {
  totalUploads: number;
  totalListings: number;
  visibleUploads: UploadItem[];
  visibleListings: MarketListingItem[];
  canExpandUploads: boolean;
  canExpandListings: boolean;
  handleExpandUploads: () => void | Promise<void>;
  handleExpandListings: () => void | Promise<void>;
  uploadsLoading: boolean;
  listingsLoading: boolean;
  uploadsExpanded: boolean;
  listingsExpanded: boolean;
}

export default function ProfilePublications({
  totalUploads,
  totalListings,
  visibleUploads,
  visibleListings,
  canExpandUploads,
  canExpandListings,
  handleExpandUploads,
  handleExpandListings,
  uploadsLoading,
  listingsLoading,
  uploadsExpanded,
  listingsExpanded,
}: ProfilePublicationsProps) {
  return (
    <>
      <div className="profile-card__section">
        <div className="profile-card__label">我发布的资料</div>
        <div className="profile-card__count">{totalUploads} 条</div>
        {visibleUploads.length === 0 ? (
          <div className="profile-card__empty">暂无发布</div>
        ) : (
          <ul className="profile-card__list">
            {visibleUploads.map((item) => (
              <li key={item.materialId}>
                <div className="profile-card__list-main">
                  <Link href={materialPath(item.materialId, item.title)}>{item.title}</Link>
                  <span className="profile-card__hint">
                    下载 {item.downloadCount ?? 0} · {formatDate(item.createdAt)}
                  </span>
                </div>
                <span className="profile-card__badge">{item.free ? '免费' : `¥${item.price.toFixed(2)}`}</span>
              </li>
            ))}
          </ul>
        )}
        {canExpandUploads && (
          <button
            type="button"
            className="profile-card__expand"
            onClick={handleExpandUploads}
            disabled={uploadsLoading}
            data-expanded={uploadsExpanded}
          >
            {uploadsExpanded ? '收起' : uploadsLoading ? '加载中...' : '展开全部'}
          </button>
        )}
      </div>

      <div className="profile-card__section">
        <div className="profile-card__label">我发布的好物</div>
        <div className="profile-card__count">{totalListings} 条</div>
        {visibleListings.length === 0 ? (
          <div className="profile-card__empty">暂无发布</div>
        ) : (
          <ul className="profile-card__list">
            {visibleListings.map((item) => (
              <li key={item.itemId}>
                <div className="profile-card__list-main">
                  <Link href={marketPath(item.itemId, item.title)}>{item.title}</Link>
                  <span className="profile-card__hint">
                    想要 {item.wantCount ?? 0} · {formatDate(item.createdAt)}
                  </span>
                </div>
                <span className="profile-card__badge">¥{item.price.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        )}
        {canExpandListings && (
          <button
            type="button"
            className="profile-card__expand"
            onClick={handleExpandListings}
            disabled={listingsLoading}
            data-expanded={listingsExpanded}
          >
            {listingsExpanded ? '收起' : listingsLoading ? '加载中...' : '展开全部'}
          </button>
        )}
      </div>
    </>
  );
}
