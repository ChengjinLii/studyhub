const HANDOFF_TTL_MS = 10 * 60 * 1000;

interface QuickUploadHandoffState {
  files: File[];
  stagedAt: number;
}

let pendingHandoff: QuickUploadHandoffState | null = null;

const normalizeFiles = (input: FileList | readonly File[] | null | undefined): File[] => {
  if (!input) return [];
  const out: File[] = [];
  for (let i = 0; i < input.length; i += 1) {
    const file = input[i];
    if (file) {
      out.push(file);
    }
  }
  return out;
};

export const stageQuickUploadFiles = (
  input: FileList | readonly File[] | null | undefined
): File[] => {
  const files = normalizeFiles(input);
  if (files.length === 0) return [];
  pendingHandoff = {
    files,
    stagedAt: Date.now(),
  };
  return [...files];
};

export const peekQuickUploadFiles = (): File[] => {
  if (!pendingHandoff) return [];
  if (Date.now() - pendingHandoff.stagedAt > HANDOFF_TTL_MS) {
    pendingHandoff = null;
    return [];
  }
  return [...pendingHandoff.files];
};

export const consumeQuickUploadFiles = (): File[] => {
  const files = peekQuickUploadFiles();
  pendingHandoff = null;
  return files;
};

export const clearQuickUploadFiles = (): void => {
  pendingHandoff = null;
};
