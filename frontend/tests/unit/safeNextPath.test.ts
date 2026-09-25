import { describe, expect, it } from 'vitest';
import { resolveSafeNextPath } from '../../lib/safeNextPath';

describe('resolveSafeNextPath', () => {
  it('keeps same-site relative paths with query and hash', () => {
    expect(resolveSafeNextPath('/me')).toBe('/me');
    expect(resolveSafeNextPath('/pay/result?orderNo=ORDER1')).toBe('/pay/result?orderNo=ORDER1');
    expect(resolveSafeNextPath('/materials/12-intro?tab=preview#comments')).toBe('/materials/12-intro?tab=preview#comments');
    expect(resolveSafeNextPath('/requests/new')).toBe('/requests/new');
  });

  it('falls back to root for missing or non-string values', () => {
    expect(resolveSafeNextPath(undefined)).toBe('/');
    expect(resolveSafeNextPath(null)).toBe('/');
    expect(resolveSafeNextPath('')).toBe('/');
    expect(resolveSafeNextPath(['/me', '/admin'])).toBe('/');
  });

  it('rejects protocol-relative and backslash redirects', () => {
    expect(resolveSafeNextPath('//evil.com')).toBe('/');
    expect(resolveSafeNextPath('//evil.com/path')).toBe('/');
    expect(resolveSafeNextPath('/\\evil.com')).toBe('/');
    expect(resolveSafeNextPath('\\\\evil.com')).toBe('/');
    expect(resolveSafeNextPath('/\\/evil.com')).toBe('/');
  });

  it('rejects absolute and scripted urls', () => {
    expect(resolveSafeNextPath('https://evil.com')).toBe('/');
    expect(resolveSafeNextPath('http://evil.com/me')).toBe('/');
    expect(resolveSafeNextPath('javascript:alert(1)')).toBe('/');
    expect(resolveSafeNextPath('data:text/html,hi')).toBe('/');
    expect(resolveSafeNextPath('evil.com')).toBe('/');
  });

  it('rejects whitespace and control character tricks', () => {
    expect(resolveSafeNextPath(' //evil.com')).toBe('/');
    expect(resolveSafeNextPath('/\t/evil.com')).toBe('/');
    expect(resolveSafeNextPath('/\n/evil.com')).toBe('/');
    expect(resolveSafeNextPath('/\r\n/evil.com')).toBe('/');
    expect(resolveSafeNextPath('/\u0000/evil.com')).toBe('/');
  });

  it('never resolves to a different origin even when encoded', () => {
    const encoded = resolveSafeNextPath('/%2F%2Fevil.com');
    expect(encoded.startsWith('//')).toBe(false);
    expect(new URL(encoded, 'https://study-hub.cn').origin).toBe('https://study-hub.cn');
    const dotted = resolveSafeNextPath('/..//evil.com');
    expect(dotted.startsWith('//')).toBe(false);
    expect(new URL(dotted, 'https://study-hub.cn').origin).toBe('https://study-hub.cn');
  });
});
