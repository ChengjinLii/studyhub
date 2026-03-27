export interface PayoutEarnings {
  grossAmount: number;
  platformFee: number;
  payoutAmount: number;
  orderCount: number;
  unclaimedPayoutTotal: number;
}

export interface PayoutApplication {
  id?: number;
  status?: 'PENDING' | 'APPROVED' | 'REJECTED' | 'SETTLED' | 'KYC_FAILED' | 'KYC_PENDING';
  alipayAccount?: string;
  alipayName?: string;
  kycStatus?: 'VERIFIED' | 'FAILED' | 'PENDING';
  kycVerifiedAt?: string;
  contactType?: 'QQ' | 'WECHAT' | 'PHONE' | 'OTHER';
  contactValue?: string;
  notes?: string;
  reviewNotes?: string;
  reviewerName?: string;
  cycleKey?: string;
  cycleStartDate?: string;
  cycleEndDate?: string;
  createdAt?: string;
  updatedAt?: string;
  settledAt?: string;
  earnings?: PayoutEarnings;
}

export interface PayoutSchedule {
  launchDate?: string;
  lastPayoutDate?: string;
  nextPayoutDate?: string;
  recentPayoutDates?: string[];
}

export interface PayoutSettlementDetail {
  settlementId: number;
  sourceType?: string | null;
  sourceId?: number | null;
  materialTitle?: string | null;
  grossAmount?: number | null;
  platformFee?: number | null;
  payoutAmount?: number | null;
  policyVersion?: string | null;
  scheduledPayoutAt?: string | null;
  createdAt?: string | null;
  status?: string | null;
}

export interface AdminMonthlyPayoutItem {
  uploaderId: number;
  uploaderUsername?: string | null;
  uploaderNickname?: string | null;
  paidDownloadCount?: number | null;
  payoutAmount?: number | null;
  hasPayoutQr?: boolean | null;
  markedPaid?: boolean | null;
  markedAt?: string | null;
  markedById?: number | null;
  markedByName?: string | null;
  markedAmountSnapshot?: number | null;
}

export interface AdminMonthlyPayoutOverview {
  monthKey: string;
  periodStart?: string | null;
  periodEnd?: string | null;
  totalPayoutAmount?: number | null;
  totalPaidDownloadCount?: number | null;
  creatorCount?: number | null;
  items: AdminMonthlyPayoutItem[];
}

export interface AdminPayoutQr {
  uploaderId: number;
  hasPayoutQr: boolean;
  payoutQrUrl?: string | null;
}
