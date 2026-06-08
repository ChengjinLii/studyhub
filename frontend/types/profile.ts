export interface PurchaseItem {
  orderId: number;
  materialId: number;
  title: string;
  amount: number;
  free: boolean;
  status: string;
  createdAt: string;
  hasFile: boolean;
  hasNetdisk: boolean;
  netdiskUrl?: string | null;
  netdiskPassword?: string | null;
  netdiskExpiredAt?: string | null;
  originalFilename?: string | null;
}

export interface UploadItem {
  materialId: number;
  title: string;
  status?: string;
  free: boolean;
  price: number;
  salesCount: number;
  downloadCount: number;
  createdAt: string;
  commentCount?: number;
  likeCount?: number;
  tags?: string[] | null;
}

export interface AdminNote {
  id: number;
  adminId: number;
  adminUsername?: string | null;
  adminNickname?: string | null;
  message: string;
  createdAt: string;
}

export interface MarketWantItem {
  itemId: number;
  title: string;
  price: number;
  wantCount: number;
  sellerName?: string | null;
  createdAt: string;
}

export interface MarketListingItem {
  itemId: number;
  title: string;
  price: number;
  wantCount: number;
  status: string;
  createdAt: string;
}

export interface FreeDownloadStatus {
  remaining: number;
  unlimited: boolean;
}

export interface ProfileSummary {
  purchases: PurchaseItem[];
  uploads: UploadItem[];
  marketWants: MarketWantItem[];
  marketListings: MarketListingItem[];
  adminNotes: AdminNote[];
  freeDownloadStatus: FreeDownloadStatus;
  hasNewAlerts: boolean;
  totalDownloads: number;
  uniqueDownloaders: number;
  totalEarnings: number;
}

export interface NotificationItem {
  id: number;
  message: string;
  sender: string | null;
  createdAt: string;
}
