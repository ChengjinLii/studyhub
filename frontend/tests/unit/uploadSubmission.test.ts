import { webcrypto } from 'node:crypto';
import { beforeAll, describe, expect, it } from 'vitest';
import {
  buildUploadSubmissionFingerprint,
  clearUploadSubmission,
  resolveUploadSubmissionId,
} from '../../lib/uploadSubmission';

class MemoryStorage {
  private readonly values = new Map<string, string>();

  getItem(key: string) {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string) {
    this.values.set(key, value);
  }

  removeItem(key: string) {
    this.values.delete(key);
  }
}

beforeAll(() => {
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value: webcrypto });
});

describe('uploadSubmission', () => {
  it('builds a stable fingerprint without persisting raw form values', async () => {
    const first = await buildUploadSubmissionFingerprint({ title: '通信原理', file: ['notes.pdf', 128] });
    const second = await buildUploadSubmissionFingerprint({ title: '通信原理', file: ['notes.pdf', 128] });
    const changed = await buildUploadSubmissionFingerprint({ title: '通信原理', file: ['notes.pdf', 256] });

    expect(first).toBe(second);
    expect(first).not.toBe(changed);
    expect(first).toMatch(/^[a-f0-9]{64}$/);
  });

  it('reuses the same pending submission after a refresh and clears it after success', () => {
    const storage = new MemoryStorage();
    const ids = ['submission_000000000001', 'submission_000000000002'];
    const createId = () => ids.shift() || 'unexpected';

    const first = resolveUploadSubmissionId('fingerprint-a', storage, 1000, createId);
    const retry = resolveUploadSubmissionId('fingerprint-a', storage, 2000, createId);
    expect(retry).toBe(first);

    clearUploadSubmission(storage, first);
    const next = resolveUploadSubmissionId('fingerprint-a', storage, 3000, createId);
    expect(next).not.toBe(first);
  });

  it('uses a new id when the form fingerprint changes', () => {
    const storage = new MemoryStorage();
    const first = resolveUploadSubmissionId('fingerprint-a', storage, 1000, () => 'submission_000000000001');
    const second = resolveUploadSubmissionId('fingerprint-b', storage, 2000, () => 'submission_000000000002');

    expect(first).not.toBe(second);
  });
});
