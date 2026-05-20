import { type Dispatch, type RefObject, type SetStateAction, useCallback, useRef, useState } from 'react';
import { appendImageFiles, ImageSelectionOptions } from './uploadAssets';

export interface UploadImageSelectionState {
  files: File[];
  setFiles: Dispatch<SetStateAction<File[]>>;
  notice: string | null;
  setNotice: Dispatch<SetStateAction<string | null>>;
  inputRef: RefObject<HTMLInputElement>;
  handleSelection: (files: FileList | null) => void;
  removeFile: (index: number) => void;
  clearFiles: () => void;
}

export const useUploadImageSelection = (options: ImageSelectionOptions): UploadImageSelectionState => {
  const [files, setFiles] = useState<File[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { label, maxFileBytes, maxFiles } = options;

  const handleSelection = useCallback(
    (fileList: FileList | null) => {
      if (!fileList) return;
      setNotice(null);
      const result = appendImageFiles(files, fileList, { label, maxFiles, maxFileBytes });
      setFiles(result.files);
      if (inputRef.current) {
        inputRef.current.value = '';
      }
      if (result.notice) {
        setNotice(result.notice);
      }
    },
    [files, label, maxFileBytes, maxFiles]
  );

  const removeFile = useCallback((index: number) => {
    setFiles((prev) => prev.filter((_, idx) => idx !== index));
  }, []);

  const clearFiles = useCallback(() => {
    setFiles([]);
    if (inputRef.current) {
      inputRef.current.value = '';
    }
  }, []);

  return {
    files,
    setFiles,
    notice,
    setNotice,
    inputRef,
    handleSelection,
    removeFile,
    clearFiles,
  };
};
