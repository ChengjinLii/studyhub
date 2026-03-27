export interface SessionUser {
  id: number;
  username?: string;
  nickname: string;
  roleMask: number;
  email?: string | null;
  verified?: boolean;
  avatar?: string | null;
  freeDownloadQuota?: number | null;
  emailPrivacy?: boolean;
}

export enum RoleMask {
  USER = 1,
  CONTRIBUTOR = 2,
  REVIEWER = 4,
  ADMIN = 8,
  DEVELOPER = 16,
}
