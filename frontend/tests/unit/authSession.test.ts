import type { IncomingMessage } from 'node:http';
import { describe, expect, it } from 'vitest';
import { hasAuthenticatedSession, readSession, resolveAdminPageAccess } from '../../lib/auth';
import { RoleMask } from '../../types/user';

const requestWithCookie = (cookie: string) =>
  ({ headers: { cookie } }) as IncomingMessage;

describe('session cookie parsing', () => {
  it('keeps percent characters in user display fields', () => {
    const user = {
      id: 9,
      username: 'percent-user',
      nickname: '进度 100%',
      roleMask: 1,
    };
    const cookie = `studyhub_user=${encodeURIComponent(JSON.stringify(user))}`;

    expect(readSession(requestWithCookie(cookie)).user).toEqual(user);
  });

  it('returns no user for malformed user cookies', () => {
    expect(readSession(requestWithCookie('studyhub_user=not-json')).user).toBeNull();
  });
});

describe('session access decisions', () => {
  const user = (roleMask: number) => ({ id: 1, username: 'u', nickname: 'u', roleMask });

  it('treats a user cookie without a token as signed out', () => {
    expect(hasAuthenticatedSession({ user: user(RoleMask.USER), token: null })).toBe(false);
    expect(hasAuthenticatedSession({ user: null, token: 'token' })).toBe(false);
    expect(hasAuthenticatedSession({ user: user(RoleMask.USER), token: 'token' })).toBe(true);
  });

  it('sends only signed-out visitors to login and hides admin pages from other users', () => {
    expect(resolveAdminPageAccess({ user: null, token: null })).toBe('login');
    expect(resolveAdminPageAccess({ user: user(RoleMask.ADMIN), token: null })).toBe('login');
    expect(resolveAdminPageAccess({ user: user(RoleMask.USER), token: 'token' })).toBe('forbidden');
    expect(resolveAdminPageAccess({ user: user(RoleMask.USER | RoleMask.ADMIN), token: 'token' })).toBe('allowed');
    expect(resolveAdminPageAccess({ user: user(RoleMask.USER | RoleMask.DEVELOPER), token: 'token' })).toBe('allowed');
  });
});
