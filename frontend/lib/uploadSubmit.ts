export interface UploadMutationResponse {
  ok?: boolean;
  msg?: string;
  data?: {
    id: number;
    title?: string | null;
  };
}

export const sendUploadFormData = (
  url: string,
  method: 'POST' | 'PUT',
  formData: FormData,
  options: {
    token?: string | null;
    onProgress: (value: number) => void;
    requestRef: { current: XMLHttpRequest | null };
  }
): Promise<UploadMutationResponse> =>
  new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    options.requestRef.current = xhr;
    xhr.open(method, url);
    xhr.responseType = 'json';
    if (options.token) {
      xhr.setRequestHeader('Authorization', `Bearer ${options.token}`);
    }
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      const percent = Math.round((event.loaded / event.total) * 100);
      options.onProgress(percent);
    };
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
      if (xhr.status >= 200 && xhr.status < 300 && response?.ok) {
        options.onProgress(100);
        resolve(response);
        return;
      }
      reject(new Error(response?.msg || '投稿失败'));
    };
    xhr.onerror = () => reject(new Error('网络异常'));
    xhr.onabort = () => reject(new Error('上传已取消'));
    xhr.send(formData);
  });
