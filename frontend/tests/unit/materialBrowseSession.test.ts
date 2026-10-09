import { describe, expect, it } from 'vitest';
import { MaterialBrowseSnapshot, readBrowseSnapshot, validateBrowseSnapshot, writeBrowseSnapshot } from '../../lib/materialBrowseSession';

const snapshot: MaterialBrowseSnapshot = {
  version: 1, savedAt: 1000, source: '/', scope: '1:1', url: '/?page=3&sort=downloads',
  detailPath: '/materials/42-CPS', historyIndex: 2, pendingRestore: true, scrollY: 1280,
  anchor: { id: 42, top: 230 },
  state: {
    filters: { page: '3', sort: 'downloads' }, materials: [], meta: { page: 3, size: 24, total: 120 },
    availableTags: [], mode: 'subjects', subjectId: 'communication-principles', subjectPage: 2,
    selectedIds: [42], showAdvanced: true,
  },
};

describe('material browse return state', () => {
  it('preserves the subject folder, page, filters, selection and card offset', () => {
    expect(validateBrowseSnapshot(snapshot, '1:1', 1500)).toEqual(snapshot);
  });

  it('does not restore another account or permission scope', () => {
    expect(validateBrowseSnapshot(snapshot, '2:1', 1500)).toBeNull();
    expect(validateBrowseSnapshot(snapshot, '1:8', 1500)).toBeNull();
  });

  it('drops expired or already-consumed snapshots', () => {
    expect(validateBrowseSnapshot(snapshot, '1:1', 31 * 60 * 1000)).toBeNull();
    expect(validateBrowseSnapshot({ ...snapshot, pendingRestore: false }, '1:1', 1500)).toBeNull();
  });

  it('rejects external return targets and malformed state', () => {
    expect(validateBrowseSnapshot({ ...snapshot, url: '//evil.example/' }, '1:1', 1500)).toBeNull();
    expect(validateBrowseSnapshot({ ...snapshot, source: '/login' }, '1:1', 1500)).toBeNull();
    expect(validateBrowseSnapshot({ ...snapshot, state: { ...snapshot.state, subjectPage: -1 } }, '1:1', 1500)).toBeNull();
    expect(validateBrowseSnapshot({ ...snapshot, anchor: { id: '"onclick', top: 0 } }, '1:1', 1500)).toBeNull();
  });

  it('handles unavailable or corrupt browser storage without interrupting navigation', () => {
    expect(readBrowseSnapshot({ getItem: () => '{invalid' }, '1:1')).toBeNull();
    expect(() => writeBrowseSnapshot({ setItem: () => { throw new Error('quota'); } }, snapshot)).not.toThrow();
  });
});
