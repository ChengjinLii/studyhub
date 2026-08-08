import { describe, expect, it } from 'vitest';
import { MATERIAL_SORT_OPTIONS, normalizeMaterialSort } from '../../constants/materialSort';

describe('material sort options', () => {
  it('exposes explicit newest and download ordering', () => {
    expect(MATERIAL_SORT_OPTIONS.map((option) => option.value)).toEqual([
      'latest',
      'newest',
      'downloads',
    ]);
  });

  it('falls back to the existing recommendation order for unknown query values', () => {
    expect(normalizeMaterialSort('newest')).toBe('newest');
    expect(normalizeMaterialSort('downloads')).toBe('downloads');
    expect(normalizeMaterialSort('price')).toBe('latest');
    expect(normalizeMaterialSort('')).toBe('latest');
  });
});
