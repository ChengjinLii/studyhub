import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { publicSubjectAliases, readMaterialSubjectAliases } from '../../lib/server/materialSubjectAliases';

const directories: string[] = [];
afterEach(() => {
  vi.unstubAllEnvs();
  directories.splice(0).forEach((path) => rmSync(path, { recursive: true, force: true }));
});

describe('private subject search aliases', () => {
  it('only publishes groups related to public courses, with deduplication and normalized case', () => {
    const aliases = publicSubjectAliases({
      微积分: ['高数', 'CALCULUS', '高数', 42],
      数电: ['数字电路', 'DCD'],
      内部词条: ['private-sentinel'],
    });
    expect(aliases.calculus).toEqual(['微积分', '高数', 'calculus']);
    expect(aliases['digital-logic']).toEqual(['数电', '数字电路', 'dcd']);
    expect(JSON.stringify(aliases)).not.toContain('private-sentinel');
    expect(publicSubjectAliases(null)).toEqual({});
    expect(publicSubjectAliases([])).toEqual({});
  });

  it('caps dictionary expansion', () => {
    const aliases = publicSubjectAliases({ 微积分: Array.from({ length: 100 }, (_, index) => `alias${index}`) });
    expect(aliases.calculus).toHaveLength(8);
  });

  it('reads the shared file at runtime, caches it and picks up edits without rebuilding', () => {
    const directory = mkdtempSync(join(tmpdir(), 'studyhub-search-'));
    directories.push(directory);
    const path = join(directory, 'synonyms.json');
    vi.stubEnv('STUDYHUB_MATERIAL_SEARCH_SYNONYMS_PATH', path);
    expect(readMaterialSubjectAliases()).toEqual({});
    writeFileSync(path, JSON.stringify({ 微积分: ['高数'] }));
    const first = readMaterialSubjectAliases();
    expect(first.calculus).toContain('高数');
    expect(readMaterialSubjectAliases()).toBe(first);
    writeFileSync(path, JSON.stringify({ 微积分: ['高等数学', 'Calculus'] }));
    expect(readMaterialSubjectAliases().calculus).toContain('高等数学');
    writeFileSync(path, '{broken');
    expect(readMaterialSubjectAliases()).toEqual({});
    writeFileSync(path, ' '.repeat(256 * 1024 + 1));
    expect(readMaterialSubjectAliases()).toEqual({});
  });
});
