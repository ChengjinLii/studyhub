import { describe, expect, it } from 'vitest';
import { sortUploadsByTime } from '../../lib/profileUploads';
import { UploadItem } from '../../types/profile';

const upload = (materialId: number, createdAt: string): UploadItem => ({
  materialId,
  title: `资料 ${materialId}`,
  free: true,
  price: 0,
  salesCount: 0,
  downloadCount: 0,
  createdAt,
});

describe('sortUploadsByTime', () => {
  const uploads = [
    upload(2, '2026-02-01T00:00:00Z'),
    upload(1, '2026-01-01T00:00:00Z'),
    upload(3, '2026-03-01T00:00:00Z'),
  ];

  it('sorts newest submissions first without mutating the source list', () => {
    expect(sortUploadsByTime(uploads, 'newest').map((item) => item.materialId)).toEqual([3, 2, 1]);
    expect(uploads.map((item) => item.materialId)).toEqual([2, 1, 3]);
  });

  it('sorts oldest submissions first', () => {
    expect(sortUploadsByTime(uploads, 'oldest').map((item) => item.materialId)).toEqual([1, 2, 3]);
  });

  it('keeps malformed dates at the end', () => {
    const withMalformedDate = [upload(4, 'unknown'), ...uploads];

    expect(sortUploadsByTime(withMalformedDate, 'newest').at(-1)?.materialId).toBe(4);
    expect(sortUploadsByTime(withMalformedDate, 'oldest').at(-1)?.materialId).toBe(4);
  });
});
