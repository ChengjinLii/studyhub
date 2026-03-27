import { UploadItem, MarketListingItem } from './profile';

export interface UserAccountProfile {
  id: number;
  username: string;
  nickname: string;
  signature?: string | null;
  school?: string | null;
  college?: string | null;
  major?: string | null;
  gradeStages?: string[] | null;
  email?: string | null;
  emailPrivacy?: boolean;
  avatar?: string | null;
  payoutQrUrl?: string | null;
  legendaryContributorUntil?: string | null;
  purchaseCount?: number;
  saleCount?: number;
}

export interface PublicUserProfile {
  id: number;
  username: string;
  nickname: string;
  signature?: string | null;
  school?: string | null;
  college?: string | null;
  major?: string | null;
  gradeStages?: string[] | null;
  avatar?: string | null;
  email?: string | null;
  emailVisible?: boolean;
  payoutQrUrl?: string | null;
  legendaryContributorUntil?: string | null;
  uploadCount: number;
  marketCount: number;
  purchaseCount?: number;
  saleCount?: number;
  followersCount: number;
  followingCount: number;
  isFollowing: boolean;
  recentUploads: UploadItem[];
  recentMarketListings: MarketListingItem[];
}

export interface UserFollowItem {
  id: number;
  username: string;
  nickname: string;
  signature?: string | null;
  school?: string | null;
  college?: string | null;
  major?: string | null;
  avatar?: string | null;
}
