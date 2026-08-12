import { describe, expect, it, vi } from 'vitest';
import {
  MATERIALS_LIST_SESSION_KEY,
  readMaterialsListSession,
  writeMaterialsListSession,
} from '../../lib/materialsListSession';

const createStorage = () => {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) || null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
    values,
  };
};

const snapshot = {
  pendingRestore: true,
  filters: {
    keyword: '通信原理', school: '', college: '', major: '', tag: '', gradeValue: '',
    courseCategory: '', price: '', sort: 'downloads', page: '2', size: '24',
  },
  materials: [],
  meta: { page: 2, size: 24, total: 80 },
  availableTags: ['期末真题'],
  mobileView: 'detail' as const,
  scrollY: 680,
};

describe('materials list session', () => {
  it('round-trips a pending list snapshot', () => {
    const storage = createStorage();
    vi.spyOn(Date, 'now').mockReturnValue(1_000);
    expect(writeMaterialsListSession(storage, snapshot)).toBe(true);
    expect(readMaterialsListSession(storage, 1_500)).toMatchObject(snapshot);
    vi.restoreAllMocks();
  });

  it('drops stale or non-pending snapshots', () => {
    const storage = createStorage();
    vi.spyOn(Date, 'now').mockReturnValue(1_000);
    writeMaterialsListSession(storage, snapshot);
    expect(readMaterialsListSession(storage, 31 * 60 * 1_000)).toBeNull();
    expect(storage.values.has(MATERIALS_LIST_SESSION_KEY)).toBe(false);

    writeMaterialsListSession(storage, { ...snapshot, pendingRestore: false });
    expect(readMaterialsListSession(storage, 1_100)).toBeNull();
    vi.restoreAllMocks();
  });
});
