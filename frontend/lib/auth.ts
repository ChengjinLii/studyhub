import type { IncomingMessage } from 'http';
import { parseCookies } from './cookies';
import { SessionUser, RoleMask } from '../types/user';

export interface SessionState {
  user: SessionUser | null;
  token: string | null;
}

export function readSession(req?: IncomingMessage): SessionState {
  const header = req?.headers?.cookie;
  const cookieSource =
    typeof header === 'string'
      ? header
      : typeof document !== 'undefined'
        ? document.cookie
        : undefined;
  const cookies = parseCookies(cookieSource);
  const token = cookies['studyhub_token'] || null;
  let user: SessionUser | null = null;
  const rawUser = cookies['studyhub_user'];
  if (rawUser) {
    try {
      user = JSON.parse(decodeURIComponent(rawUser));
    } catch {
      user = null;
    }
  }
  return { user, token };
}

export function hasRole(mask: number | null | undefined, role: RoleMask): boolean {
  if (typeof mask !== 'number') return false;
  return (mask & role) === role;
}
