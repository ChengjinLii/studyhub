import { describe, expect, it } from 'vitest';
import { HOME_DISCOVERY_DEFAULT_VIEW, rankHomeSubjects } from '../../lib/homeDiscovery';
import type { MaterialSubjectFolder } from '../../lib/materialSubjects';

const folder = (id: string, name: string, counts: Array<number | undefined>): MaterialSubjectFolder => ({
  id, name, materials: counts.map((downloadCount, index) => ({ id: index + 1, title: name, free: true, price: 0, downloadCount })),
});

describe('home subject discovery', () => {
  it('always defaults to popular subjects regardless of available requests', () => {
    expect(HOME_DISCOVERY_DEFAULT_VIEW).toBe('subjects');
  });

  it('sums material downloads and sorts by downloads rather than material count', () => {
    const folders = [folder('physics', '大学物理', [3, 5, 1]), folder('cps', '通信原理', [20, 10])];
    expect(rankHomeSubjects(folders)).toEqual([
      { id: 'cps', name: '通信原理', materialCount: 2, downloadCount: 30 },
      { id: 'physics', name: '大学物理', materialCount: 3, downloadCount: 9 },
    ]);
    expect(folders[0].id).toBe('physics');
    expect(folders[0].materials.map((material) => material.downloadCount)).toEqual([3, 5, 1]);
  });

  it('keeps zero-download subjects, handles missing counts and omits non-subject folders', () => {
    expect(rankHomeSubjects([
      folder('esd', '电子系统设计', [undefined, -3, NaN, Infinity]),
      folder('other', '其他资料', [100]), folder('empty', '空学科', []),
    ])).toEqual([{ id: 'esd', name: '电子系统设计', materialCount: 4, downloadCount: 0 }]);
    expect(rankHomeSubjects([])).toEqual([]);
  });

  it('breaks equal-download ties by material count and then subject name', () => {
    const ranked = rankHomeSubjects([
      folder('c', 'C', [10]), folder('a', 'A', [5, 5]), folder('b', 'B', [5, 5]),
    ]);
    expect(ranked.map((subject) => subject.id)).toEqual(['a', 'b', 'c']);
  });
});
