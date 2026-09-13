export interface StagedUploadResponse {
  ok?: boolean;
  msg?: string;
  data?: {
    stagedUploadToken: string;
    files: number;
  };
}

export const sendStagedUploadFormData = (
  url: string,
  formData: FormData,
  options: {
    token?: string | null;
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
    if (options.token) xhr.setRequestHeader('Authorization', `Bearer ${options.token}`);
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
