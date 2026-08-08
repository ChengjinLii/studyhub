export type UploadSubmissionStage = 'idle' | 'preparing' | 'uploading' | 'processing' | 'redirecting';

interface PendingUploadSubmission {
  fingerprint: string;
  submissionId: string;
  createdAt: number;
}

interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

const STORAGE_KEY = 'studyhub:pending-material-submission:v1';
const MAX_PENDING_AGE_MS = 24 * 60 * 60 * 1000;

const toHex = (buffer: ArrayBuffer) =>
  Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, '0')).join('');

export async function buildUploadSubmissionFingerprint(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return toHex(digest);
}

export function resolveUploadSubmissionId(
  fingerprint: string,
  storage: StorageLike,
  now = Date.now(),
  createId = () => globalThis.crypto.randomUUID()
): string {
  const pending = readPendingSubmission(storage);
  if (
    pending &&
    pending.fingerprint === fingerprint &&
    now - pending.createdAt >= 0 &&
    now - pending.createdAt <= MAX_PENDING_AGE_MS
  ) {
    return pending.submissionId;
  }

  const submissionId = createId();
  try {
    storage.setItem(
      STORAGE_KEY,
      JSON.stringify({ fingerprint, submissionId, createdAt: now } satisfies PendingUploadSubmission)
    );
  } catch {
    // Storage may be unavailable in strict privacy modes. The request still
    // carries an idempotency key; only refresh recovery is reduced.
  }
  return submissionId;
}

export function clearUploadSubmission(storage: StorageLike, submissionId: string): void {
  const pending = readPendingSubmission(storage);
  if (pending?.submissionId === submissionId) {
    try {
      storage.removeItem(STORAGE_KEY);
    } catch {
      // Ignore unavailable browser storage after a confirmed submission.
    }
  }
}

function readPendingSubmission(storage: StorageLike): PendingUploadSubmission | null {
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PendingUploadSubmission>;
    if (
      typeof parsed.fingerprint !== 'string' ||
      typeof parsed.submissionId !== 'string' ||
      typeof parsed.createdAt !== 'number'
    ) {
      try {
        storage.removeItem(STORAGE_KEY);
      } catch {
        // Ignore unavailable browser storage.
      }
      return null;
    }
    return parsed as PendingUploadSubmission;
  } catch {
    try {
      storage.removeItem(STORAGE_KEY);
    } catch {
      // Ignore unavailable browser storage.
    }
    return null;
  }
}
