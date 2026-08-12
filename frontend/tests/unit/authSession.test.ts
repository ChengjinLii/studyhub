import type { IncomingMessage } from 'node:http';
import { describe, expect, it } from 'vitest';
import { readSession } from '../../lib/auth';

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
