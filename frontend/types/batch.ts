export type BatchId = string | number;
export type PublicationIntent = 'FREE' | 'PAID' | 'CONTACT';
export interface BatchSummary {
  id: BatchId;
  status: string;
  createdAt?: string;
  uploaderId?: number;
  totalBytes?: number;
  itemCount: number;
  statusCounts?: Record<string, number>;
  items?: { id: BatchId; status: string; scanStatus: string; reason?: string }[];
  publications?: { id: BatchId; title: string; url: string }[];
}
export interface BatchItem {
  id: BatchId;
  name: string;
  sizeBytes: number;
  status: string;
  scanStatus: string;
  reason?: string;
}
export interface BatchDetail extends BatchSummary {
  items: BatchItem[];
  deliveryMethod: 'FILE' | 'NETDISK';
  publicationIntent: PublicationIntent;
  pricingNote?: string;
  netdiskUrl?: string;
  netdiskPassword?: string;
  note?: string;
}
export interface BatchPage<T = BatchSummary> { items: T[]; total: number }
export interface CreateBatch {
  submissionId: string;
  deliveryMethod: 'FILE' | 'NETDISK';
  publicationIntent: PublicationIntent;
  pricingNote: string;
  netdiskUrl: string;
  netdiskPassword: string;
  note: string;
  consent: true;
  files: { name: string; sizeBytes: number; contentType: string }[];
}
export interface PublishBatch {
  itemIds: BatchId[];
  title: string;
  description: string;
  school: string;
  courseCategory: string;
  college?: string;
  major?: string;
  tags?: string;
  price: number;
  pricingConfirmed: boolean;
  confirmationNote: string;
  publicationId: string;
}
