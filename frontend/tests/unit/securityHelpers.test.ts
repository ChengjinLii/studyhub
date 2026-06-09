import { describe, expect, it, vi } from 'vitest';
import { safeMarkdownImageUrl, safeMarkdownUrl } from '../../components/SafeMarkdown';
import { navigateTrustedPaymentUrl, resolveTrustedPaymentAction } from '../../lib/safePaymentForm';

describe('security helpers', () => {
  it('allows only trusted payment form actions', () => {
    expect(resolveTrustedPaymentAction('/pay/result', 'https://study-hub.cn').href).toBe('https://study-hub.cn/pay/result');
    expect(resolveTrustedPaymentAction('https://openapi.alipay.com/gateway.do', 'https://study-hub.cn').hostname).toBe(
      'openapi.alipay.com'
    );
    expect(resolveTrustedPaymentAction('https://openapi-sandbox.dl.alipaydev.com/gateway.do', 'https://study-hub.cn').hostname).toBe(
      'openapi-sandbox.dl.alipaydev.com'
    );
    expect(() => resolveTrustedPaymentAction('/api/admin/users', 'https://study-hub.cn')).toThrow('不受信任');
    expect(() => resolveTrustedPaymentAction('https://evil.example/pay', 'https://study-hub.cn')).toThrow('不受信任');
  });

  it('navigates only to trusted payment gateway urls', () => {
    const originalWindow = globalThis.window;
    const assign = vi.fn();
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: {
        location: {
          origin: 'https://study-hub.cn',
          assign,
        },
      },
    });

    navigateTrustedPaymentUrl('https://openapi.alipay.com/gateway.do?out_trade_no=ORDER1');
    expect(assign).toHaveBeenCalledWith('https://openapi.alipay.com/gateway.do?out_trade_no=ORDER1');
    expect(() => navigateTrustedPaymentUrl('https://evil.example/pay')).toThrow('不受信任');

    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: originalWindow,
    });
  });

  it('filters unsafe markdown urls', () => {
    expect(safeMarkdownUrl('https://example.com/path')).toBe('https://example.com/path');
    expect(safeMarkdownUrl('/materials/1')).toBe('/materials/1');
    expect(safeMarkdownUrl('#section')).toBe('#section');
    expect(safeMarkdownUrl('mailto:user@example.com')).toBe('mailto:user@example.com');
    expect(safeMarkdownUrl('//evil.example/path')).toBe('');
    expect(safeMarkdownUrl('javascript:alert(1)')).toBe('');
    expect(safeMarkdownUrl('data:text/html;base64,PGgxPkJvb208L2gxPg==')).toBe('');
  });

  it('allows only same-site markdown images', () => {
    expect(safeMarkdownImageUrl('/uploads/preview.png')).toBe('/uploads/preview.png');
    expect(safeMarkdownImageUrl('//evil.example/track.png')).toBe('');
    expect(safeMarkdownImageUrl('https://example.com/track.png')).toBe('');
    expect(safeMarkdownImageUrl('data:image/png;base64,AAAA')).toBe('');
  });
});
