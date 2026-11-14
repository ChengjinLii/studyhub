import { describe, expect, it } from 'vitest';
import { normalizeMarkdownText } from '../../lib/markdownText';

describe('normalizeMarkdownText', () => {
  it('returns an empty string for missing text', () => {
    expect(normalizeMarkdownText(undefined)).toBe('');
    expect(normalizeMarkdownText(null)).toBe('');
    expect(normalizeMarkdownText('   ')).toBe('');
  });

  it('removes Markdown syntax and joins lines', () => {
    const source = '# 期末**速成**\n\n> 重点见 [目录](https://example.com/toc)\n\n`公式` 与 ![图](a.png)\n```\ncode\n```\n| a | b |';
    expect(normalizeMarkdownText(source)).toBe('期末速成 重点见 目录 公式 与 图 a b');
  });
});
