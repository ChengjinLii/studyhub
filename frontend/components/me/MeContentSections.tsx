import Link from 'next/link';
import { ReactNode } from 'react';
import { MarketListingItem, MarketWantItem, PurchaseItem, UploadItem } from '../../types/profile';

interface MeContentSectionsProps {
  uploads: UploadItem[];
  visibleUploads: UploadItem[];
  uploadsExpanded: boolean;
  canExpandUploads: boolean;
  purchases: PurchaseItem[];
  visiblePurchases: PurchaseItem[];
  purchasesExpanded: boolean;
  canExpandPurchases: boolean;
  marketWants: MarketWantItem[];
  visibleMarketWants: MarketWantItem[];
  wantsExpanded: boolean;
  canExpandMarketWants: boolean;
  marketListings: MarketListingItem[];
  visibleMarketListings: MarketListingItem[];
  listingsExpanded: boolean;
  canExpandMarketListings: boolean;
  renderUpload: (item: UploadItem) => ReactNode;
  renderPurchase: (item: PurchaseItem) => ReactNode;
  renderMarketWant: (item: MarketWantItem) => ReactNode;
  renderMarketListing: (item: MarketListingItem) => ReactNode;
  onUploadsExpandedChange: (value: boolean) => void;
  onPurchasesExpandedChange: (value: boolean) => void;
  onWantsExpandedChange: (value: boolean) => void;
  onListingsExpandedChange: (value: boolean) => void;
}

export default function MeContentSections({
  uploads,
  visibleUploads,
  uploadsExpanded,
  canExpandUploads,
  purchases,
  visiblePurchases,
  purchasesExpanded,
  canExpandPurchases,
  marketWants,
  visibleMarketWants,
  wantsExpanded,
  canExpandMarketWants,
  marketListings,
  visibleMarketListings,
  listingsExpanded,
  canExpandMarketListings,
  renderUpload,
  renderPurchase,
  renderMarketWant,
  renderMarketListing,
  onUploadsExpandedChange,
  onPurchasesExpandedChange,
  onWantsExpandedChange,
  onListingsExpandedChange,
}: MeContentSectionsProps) {
  return (
    <>
      <section className="card" id="uploads">
        <div className="card-title">我的投稿</div>
        {uploads.length === 0 ? (
          <p className="help-text">
            还没有投稿，<Link href="/upload">前往投稿</Link> 提供优质资料吧。
          </p>
        ) : (
          <>
            <ul className="materials-list">{visibleUploads.map(renderUpload)}</ul>
            {canExpandUploads && (
              <button
                type="button"
                className="profile-card__expand"
                onClick={() => onUploadsExpandedChange(!uploadsExpanded)}
                data-expanded={uploadsExpanded}
              >
                {uploadsExpanded ? '收起' : '展开全部'}
              </button>
            )}
          </>
        )}
      </section>
      <section className="card" id="purchases">
        <div className="card-title">最近购买</div>
        {purchases.length === 0 ? (
          <p className="help-text">暂无购买记录，去首页看看吧。</p>
        ) : (
          <>
            <ul className="materials-list">{visiblePurchases.map(renderPurchase)}</ul>
            {canExpandPurchases && (
              <button
                type="button"
                className="profile-card__expand"
                onClick={() => onPurchasesExpandedChange(!purchasesExpanded)}
                data-expanded={purchasesExpanded}
              >
                {purchasesExpanded ? '收起' : '展开全部'}
              </button>
            )}
          </>
        )}
      </section>
      <section className="card" id="wants">
        <div className="card-title">我想要的校园好物</div>
        {marketWants.length === 0 ? (
          <p className="help-text">
            还没有关注校园好物，<Link href="/market">去集市逛逛</Link>。
          </p>
        ) : (
          <>
            <ul className="materials-list">{visibleMarketWants.map(renderMarketWant)}</ul>
            {canExpandMarketWants && (
              <button
                type="button"
                className="profile-card__expand"
                onClick={() => onWantsExpandedChange(!wantsExpanded)}
                data-expanded={wantsExpanded}
              >
                {wantsExpanded ? '收起' : '展开全部'}
              </button>
            )}
          </>
        )}
      </section>
      <section className="card" id="listings">
        <div className="card-title">我发布的校园好物</div>
        {marketListings.length === 0 ? (
          <p className="help-text">
            还没有发布校园好物，<Link href="/market/sell">去集市发布</Link>。
          </p>
        ) : (
          <>
            <ul className="materials-list">{visibleMarketListings.map(renderMarketListing)}</ul>
            {canExpandMarketListings && (
              <button
                type="button"
                className="profile-card__expand"
                onClick={() => onListingsExpandedChange(!listingsExpanded)}
                data-expanded={listingsExpanded}
              >
                {listingsExpanded ? '收起' : '展开全部'}
              </button>
            )}
          </>
        )}
      </section>
    </>
  );
}
