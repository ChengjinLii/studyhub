import { useCallback, useEffect, useRef, useState } from 'react';
import { toErrorMessage } from './errors';
import { describeUploadFile, requestMaterialUploadAuthorization } from './uploadAuthorization';

export type StagedUploadRole = 'MATERIAL' | 'PREVIEW' | 'CUSTOM_PREVIEW';

export interface StagedUploadAsset {
  signature: string;
  token: string;
}

export interface StagedUploadResponse {
  ok?: boolean;
  msg?: string;
  data?: {
    stagedUploadToken: string;
    files: number;
  };
}

export const buildUploadFileSignature = (files: File[]): string =>
  files.map((file) => `${file.name}:${file.size}:${file.lastModified}:${file.type}`).join('|');

export const sendStagedUploadFormData = (
  url: string,
  formData: FormData,
  options: {
    uploadToken: string;
    onProgress: (value: number) => void;
    requestRef: { current: XMLHttpRequest | null };
  }
): Promise<{ stagedUploadToken: string; files: number }> =>
  new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    options.requestRef.current = xhr;
    xhr.open('POST', url);
    xhr.responseType = 'json';
    xhr.timeout = 10 * 60 * 1000;
    xhr.withCredentials = true;
    xhr.setRequestHeader('X-StudyHub-Upload-Token', options.uploadToken);
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      const complete = event.loaded >= event.total;
      options.onProgress(complete ? 100 : Math.min(99, Math.round((event.loaded / event.total) * 100)));
    };
    xhr.upload.onload = () => options.onProgress(100);
    xhr.onload = () => {
      const response: StagedUploadResponse | null = xhr.response;
      if (
        xhr.status >= 200 &&
        xhr.status < 300 &&
        response?.ok &&
        response.data?.stagedUploadToken
      ) {
        resolve(response.data);
        return;
      }
      reject(new Error(response?.msg || '文件上传失败'));
    };
    xhr.onerror = () => reject(new Error('文件上传网络异常'));
    xhr.onabort = () => reject(new Error('文件上传已取消'));
    xhr.ontimeout = () => reject(new Error('文件上传超时'));
    xhr.send(formData);
  });

export const stageAuthorizedUploadFiles = async (
  apiBase: string,
  role: StagedUploadRole,
  files: File[],
  submissionId: string,
  authorizationSubmissionId: string,
  requestRef: { current: XMLHttpRequest | null },
  onProgress: (value: number) => void
) => {
  const authorization = await requestMaterialUploadAuthorization(
    authorizationSubmissionId,
    files.map((file) => describeUploadFile(role, file))
  );
  const formData = new FormData();
  formData.append('submissionId', submissionId);
  formData.append('authorizationSubmissionId', authorizationSubmissionId);
  const field = role === 'MATERIAL' ? 'zip' : role === 'PREVIEW' ? 'previews' : 'customPreviews';
  files.forEach((file) => formData.append(field, file));
  return sendStagedUploadFormData(`${apiBase}/material-uploads/stage`, formData, {
    uploadToken: authorization.uploadToken,
    onProgress,
    requestRef,
  });
};

export function useStagedPreviewGroup(options: {
  apiBase: string;
  role: 'PREVIEW' | 'CUSTOM_PREVIEW';
  enabled: boolean;
  activeSubmissionId: string | null;
  files: File[];
  errorFallback: string;
  onClearStatus: () => void;
  onError: (message: string) => void;
}) {
  const { apiBase, role, enabled, activeSubmissionId, files, errorFallback, onClearStatus, onError } = options;
  const [staged, setStaged] = useState<StagedUploadAsset | null>(null);
  const [uploading, setUploading] = useState(false);
  const requestRef = useRef<XMLHttpRequest | null>(null);
  const taskRef = useRef(0);
  const onClearStatusRef = useRef(onClearStatus);
  onClearStatusRef.current = onClearStatus;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const reset = useCallback(() => {
    requestRef.current?.abort();
    requestRef.current = null;
    taskRef.current += 1;
    setUploading(false);
    setStaged(null);
  }, []);

  useEffect(() => {
    if (!enabled || !activeSubmissionId) return;
    requestRef.current?.abort();
    requestRef.current = null;
    const taskId = ++taskRef.current;
    if (files.length === 0) {
      setStaged(null);
      setUploading(false);
      return;
    }
    const signature = buildUploadFileSignature(files);
    setStaged(null);
    setUploading(true);
    void stageAuthorizedUploadFiles(
      apiBase,
      role,
      files,
      activeSubmissionId,
      globalThis.crypto.randomUUID(),
      requestRef,
      () => undefined
    )
      .then((result) => {
        if (taskRef.current !== taskId) return;
        setStaged({ signature, token: result.stagedUploadToken });
        onClearStatusRef.current();
      })
      .catch((error: unknown) => {
        if (taskRef.current !== taskId) return;
        onErrorRef.current(toErrorMessage(error, errorFallback));
      })
      .finally(() => {
        if (taskRef.current === taskId) setUploading(false);
        requestRef.current = null;
      });
    return () => {
      if (taskRef.current === taskId) requestRef.current?.abort();
    };
  }, [activeSubmissionId, apiBase, enabled, errorFallback, files, role]);

  return { staged, uploading, reset };
}
