export interface PaginationMeta {
  page: number;
  size: number;
  total: number;
}

export interface MaterialListItem {
  id: number;
  uploaderId?: number | null;
  title: string;
  description?: string | null;
  price: number;
  free: boolean;
  school?: string | null;
  college?: string | null;
  major?: string | null;
  generalEducation?: boolean;
  hasFile?: boolean;
  hasNetdisk?: boolean;
  courseCategory?: string | null;
  gradeType?: string | null;
  gradeValue?: string | null;
  tags?: string[];
  previewWatermarkEnabled?: boolean | null;
  previewSource?: string | null;
  copyrightOwner?: string | null;
  ratingAvg?: number;
  ratingCount?: number;
  likeCount?: number;
  commentCount?: number;
  viewCount?: number;
  downloadCount?: number;
  salesCount?: number;
  createdAt?: string;
  uploaderUsername?: string | null;
  uploaderNickname?: string | null;
}

export interface MaterialVersion {
  id: number;
  versionLabel: string;
  createdAt: string;
  changelog?: string | null;
}

export interface CommentUser {
  id?: number | null;
  nickname?: string | null;
  avatar?: string | null;
  isAuthor?: boolean;
}

export interface Comment {
  id: number;
  materialId: number;
  parentId?: number | null;
  content: string;
  likeCount: number;
  replyCount: number;
  edited?: boolean;
  deleted?: boolean;
  createdAt?: string | null;
  updatedAt?: string | null;
  user: CommentUser;
  hasLiked?: boolean;
  rating?: number | null;
  replies?: Comment[];
}

export interface CommentListResponse {
  items: Comment[];
  meta: PaginationMeta;
}

export interface MaterialReview {
  id: number;
  reviewer: string;
  rating: number;
  comment?: string | null;
  createdAt: string;
}

export interface PreviewImageSource {
  src: string;
  srcSet?: string | null;
  sizes?: string | null;
}

export interface MaterialPreviewImage {
  index: number;
  width?: number | null;
  height?: number | null;
  img: PreviewImageSource;
  webp?: PreviewImageSource | null;
  avif?: PreviewImageSource | null;
  lqip?: string | null;
}

export interface MaterialPreview {
  status: 'processing' | 'done' | 'failed' | 'unsupported';
  pageCount?: number | null;
  previewPages?: number | null;
  message?: string | null;
  images: MaterialPreviewImage[];
}

export interface MaterialDetail extends MaterialListItem {
  uploaderId?: number;
  originalFilename?: string | null;
  fileType?: string | null;
  fileSize?: number | null;
  previewManifest?: string | null;
  customPreviewText?: string | null;
  customPreviewImages?: string[];
  netdiskUrl?: string | null;
  netdiskPassword?: string | null;
  netdiskExpiredAt?: string | null;
  netdiskReminderAt?: string | null;
  netdiskAccessible?: boolean;
  purchased?: boolean;
  favorited?: boolean;
  liked?: boolean;
  myRating?: number | null;
  securityScanStatus?: 'PENDING' | 'SCANNING' | 'CLEAN' | 'INFECTED' | 'ERROR' | null;
  hasFile: boolean;
  versions: MaterialVersion[];
  reviews: MaterialReview[];
}

export interface MaterialListStats {
  totalMaterials: number;
  freeMaterials: number;
  totalDownloads: number;
  userCount: number;
}

export interface BatchDownloadItem {
  materialId: number;
  deliveryType: 'FILE' | 'NETDISK';
  url?: string | null;
  netdiskUrl?: string | null;
  netdiskPassword?: string | null;
  netdiskExpiredAt?: string | null;
  originalFilename?: string | null;
}
