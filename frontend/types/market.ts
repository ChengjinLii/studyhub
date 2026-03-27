export interface MarketItem {
  id: number;
  sellerId?: number | null;
  title: string;
  price: number;
  category: string;
  thumbnail?: string | null;
  thumbnailVariant?: MarketImageVariant | null;
  wantCount: number;
  // Whether the current user has marked this item as wanted; undefined when unauthenticated.
  wanted?: boolean;
  school?: string | null;
  sellerName?: string | null;
  createdAt?: string;
}

export interface MarketImageVariant {
  src: string;
  srcSet?: string | null;
  webpSrcSet?: string | null;
  avifSrcSet?: string | null;
  lqip?: string | null;
}

export interface MarketListResponse {
  items: MarketItem[];
  meta: {
    page: number;
    size: number;
    total: number;
  };
  stats?: {
    active: number;
    sold: number;
    userCount?: number;
  };
}

export interface MarketItemDetail {
  id: number;
  sellerId: number;
  sellerName?: string | null;
  title: string;
  description?: string | null;
  price: number;
  category: string;
  images: string[];
  imageVariants?: MarketImageVariant[];
  wantCount: number;
  school?: string | null;
  status?: string;
  canViewContact: boolean;
  contactType?: string | null;
  contactValue?: string | null;
  wanted: boolean;
  isOwner: boolean;
  createdAt?: string;
}
