export interface UserSummary {
  id: number;
  username: string;
  nickname: string;
  roleMask: number;
  createdAt?: string;
  updatedAt?: string;
  totalEarnings?: number;
}

export interface FeedbackEntry {
  id: number;
  userId?: number | null;
  type: string;
  page?: string | null;
  content: string;
  contact?: string | null;
  status: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface VolunteerApplicationEntry {
  id: number;
  userId?: number | null;
  name: string;
  schoolMajorGrade: string;
  skills: string[];
  timeCommitment?: string | null;
  portfolioUrl?: string | null;
  intro: string;
  contact?: string | null;
  status: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface AdminMaterial {
  id: number;
  title: string;
  school?: string | null;
  college?: string | null;
  major?: string | null;
  gradeValue?: string | null;
  gradeType?: string | null;
  courseCategory?: string | null;
  tags?: string[];
  price?: number | null;
  free?: boolean;
  status?: string | null;
  reviewStatus?: string | null;
  uploaderUsername?: string | null;
  uploaderNickname?: string | null;
  createdAt?: string;
  updatedAt?: string;
  deletedAt?: string | null;
}

export interface AdminMarketItem {
  id: number;
  title: string;
  price: number;
  priceText: string;
  category?: string | null;
  status?: string | null;
  wantCount?: number | null;
  school?: string | null;
  createdAt?: string;
  sellerId?: number | null;
  sellerName?: string | null;
  contactType?: string | null;
  contactValue?: string | null;
  thumbnail?: string | null;
}

export interface AdminReport {
  id: number;
  targetType: string;
  targetId: number;
  targetLabel?: string | null;
  targetStatus?: string | null;
  targetUrl?: string | null;
  reporterId?: number | null;
  reporterName?: string | null;
  reason: string;
  status: string;
  adminNote?: string | null;
  createdAt?: string;
}

export interface AdminListMeta {
  page: number;
  size: number;
  total: number;
}
