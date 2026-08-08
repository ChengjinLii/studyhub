import { describe, expect, it } from 'vitest';
import {
  buildNetdiskCopyText,
  resolveNetdiskOpenUrl,
} from '../../components/materials/NetdiskAccessModal';

describe('netdisk access helpers', () => {
  it('builds one-click copy text with an optional password', () => {
    expect(buildNetdiskCopyText('https://pan.example/file', 'a1b2')).toBe(
      '网盘链接：https://pan.example/file\n提取码：a1b2'
    );
    expect(buildNetdiskCopyText('https://pan.example/file')).toBe(
      '网盘链接：https://pan.example/file'
    );
  });

  it('only exposes http links as clickable destinations', () => {
    expect(resolveNetdiskOpenUrl('https://pan.example/file')).toBe('https://pan.example/file');
    expect(resolveNetdiskOpenUrl('javascript:alert(1)')).toBeNull();
    expect(resolveNetdiskOpenUrl('网盘链接请联系投稿者')).toBeNull();
  });
});
