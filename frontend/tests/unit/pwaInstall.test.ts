import { describe, expect, it } from 'vitest';
import { detectInstallClient, installSteps } from '../../lib/pwaInstall';

describe('PWA client guidance', () => {
  it.each([
    ['Mozilla iPhone Safari', 'iPhone', 5, false, 'ios', true, false],
    ['Mozilla Macintosh Safari', 'MacIntel', 5, false, 'ios', true, false],
    ['Mozilla Macintosh Safari', 'MacIntel', 0, false, 'other', false, false],
    ['Mozilla Android Chrome', 'Linux', 5, true, 'android', true, false],
    ['Mozilla iPhone MicroMessenger', 'iPhone', 5, true, 'ios', true, true],
    ['Mozilla Android QQ/8.9', 'Linux', 5, true, 'android', true, true],
    ['Mozilla Android; wv)', 'Linux', 5, true, 'android', true, true],
    ['Mozilla Windows', 'Win32', 0, false, 'other', false, false],
  ] as const)('classifies %s without assuming installation support', (ua, platform, touch, coarse, expected, mobile, embedded) => {
    expect(detectInstallClient(ua, platform, touch, coarse)).toEqual({ platform: expected, mobile, embedded });
  });
  it('uses platform-specific manual installation instead of promising a download', () => {
    expect(installSteps('ios', false).join('')).toContain('分享');
    expect(installSteps('ios', true)[0]).toContain('系统浏览器');
    expect(installSteps('android', false).join('')).toContain('安装应用');
  });
});
