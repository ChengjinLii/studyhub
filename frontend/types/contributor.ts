export interface ContributorRank {
  userId: number;
  username: string;
  downloads: number;
  roleMask?: number | null;
}

export type LeaderboardPeriod = 'all' | 'week' | 'month';
