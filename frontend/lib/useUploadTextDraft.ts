import { useCallback, useEffect, useRef, useState } from 'react';
import { clearUploadDraft, readUploadDraft, UploadTextDraft, UploadTextDraftValue, writeUploadDraft } from './uploadDraft';

interface UploadTextDraftOptions {
  draftKey: string | null;
  isEditing: boolean;
  value: UploadTextDraftValue;
  onRestore: (draft: UploadTextDraft) => void;
}

export function useUploadTextDraftPersistence({ draftKey, isEditing, value, onRestore }: UploadTextDraftOptions) {
  const [readyKey, setReadyKey] = useState<string | null>(null);
  const [restored, setRestored] = useState(false);
  const onRestoreRef = useRef(onRestore);
  const valueRef = useRef(value);
  onRestoreRef.current = onRestore;
  valueRef.current = value;
  const serializedValue = JSON.stringify(value);

  useEffect(() => {
    setRestored(false);
    if (isEditing || !draftKey || typeof window === 'undefined') {
      setReadyKey(null);
      return;
    }
    const draft = readUploadDraft(window.localStorage, draftKey);
    if (draft) {
      onRestoreRef.current(draft);
      setRestored(true);
    }
    setReadyKey(draftKey);
  }, [draftKey, isEditing]);

  useEffect(() => {
    if (isEditing || !draftKey || readyKey !== draftKey || typeof window === 'undefined') return;
    const timeoutId = window.setTimeout(() => {
      writeUploadDraft(window.localStorage, draftKey, {
        ...valueRef.current,
        version: 1,
        updatedAt: Date.now(),
      });
    }, 700);
    return () => window.clearTimeout(timeoutId);
  }, [draftKey, isEditing, readyKey, serializedValue]);

  const clearDraft = useCallback(() => {
    if (draftKey && typeof window !== 'undefined') clearUploadDraft(window.localStorage, draftKey);
  }, [draftKey]);

  return { draftRestored: restored, dismissDraftRestored: () => setRestored(false), clearDraft };
}
