export interface MaterialRequestItem {
  id: number;
  course?: string | null;
  keyword?: string | null;
  school?: string | null;
  college?: string | null;
  major?: string | null;
  budget?: number | null;
  fundedAmount?: number | null;
  contributionCount?: number | null;
  deadline?: string | null;
  urgencyTier?: string | null;
  creatorFloor?: number | null;
  previewRequirement?: string | null;
  anonymous?: boolean;
  requesterName?: string | null;
  responseCount: number;
  responded?: boolean;
  owner?: boolean;
  acceptedResponseId?: number | null;
  status?: string | null;
  createdAt?: string | null;
}

export interface MaterialRequestResponse {
  id: number;
  responderName?: string | null;
  message?: string | null;
  materialId?: number | null;
  revisionCount?: number | null;
  updatedAt?: string | null;
  createdAt?: string | null;
}

export interface MaterialRequestContributionItem {
  id: number;
  contributorId?: number | null;
  contributorName?: string | null;
  type?: string | null;
  amount?: number | null;
  status?: string | null;
  deadlineTier?: string | null;
  deadlineAt?: string | null;
  createdAt?: string | null;
}
