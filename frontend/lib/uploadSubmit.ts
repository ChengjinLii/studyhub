export interface UploadMutationResponse {
  ok?: boolean;
  msg?: string;
  data?: {
    id: number;
    title?: string | null;
  };
}

export class UploadSubmitError extends Error {
  readonly resultUncertain: boolean;

  constructor(message: string, resultUncertain: boolean) {
    super(message);
    this.name = 'UploadSubmitError';
    this.resultUncertain = resultUncertain;
  }
}

export const isUploadResultUncertain = (error: unknown) =>
  error instanceof UploadSubmitError && error.resultUncertain;

export const sendUploadFormData = (
  url: string,
  method: 'POST' | 'PUT',
  formData: FormData,
  options: {
    token?: string | null;
    uploadToken?: string | null;
    onProgress: (value: number) => void;
    requestRef: { current: XMLHttpRequest | null };
  }
): Promise<UploadMutationResponse> =>
  new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    options.requestRef.current = xhr;
    xhr.open(method, url);
    xhr.responseType = 'json';
    xhr.timeout = 10 * 60 * 1000;
    if (options.token) {
      xhr.setRequestHeader('Authorization', `Bearer ${options.token}`);
    }
    if (options.uploadToken) {
      xhr.setRequestHeader('X-StudyHub-Upload-Token', options.uploadToken);
    }
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      const percent = Math.round((event.loaded / event.total) * 100);
      options.onProgress(percent);
    };
    xhr.upload.onload = () => options.onProgress(100);
    xhr.onload = () => {
      const response: UploadMutationResponse | null =
        xhr.response ||
        (() => {
          try {
            return JSON.parse(xhr.responseText) as UploadMutationResponse;
          } catch {
            return null;
          }
        })();
      if (xhr.status >= 200 && xhr.status < 300 && response?.ok && Number.isInteger(response.data?.id)) {
        options.onProgress(100);
        resolve(response);
        return;
      }
      const successfulHttpResponse = xhr.status >= 200 && xhr.status < 300;
      reject(new UploadSubmitError(response?.msg || '投稿失败', successfulHttpResponse));
    };
    xhr.onerror = () => reject(new UploadSubmitError('网络异常', true));
    xhr.onabort = () => reject(new UploadSubmitError('上传已取消', true));
    xhr.ontimeout = () => reject(new UploadSubmitError('服务器处理超时', true));
    xhr.send(formData);
  });
