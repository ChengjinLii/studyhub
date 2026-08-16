import { queueNextAppToast, useAppToast } from '../components/AppToastProvider';

export const useUploadSubmissionToast = () => {
  const toast = useAppToast();
  const id = 'upload-submission';

  return {
    invalid: (message: string) => toast.show(message, { tone: 'error' }),
    preparing: () => toast.show('正在准备投稿内容…', { id, tone: 'loading' }),
    uploading: (editing: boolean) => toast.show(editing ? '正在上传更新内容…' : '正在上传资料…', { id, tone: 'loading' }),
    processing: () => toast.show('文件上传完成，正在保存资料…', { id, tone: 'loading' }),
    success: (editing: boolean, detail?: string) => {
      const message = detail || (editing ? '资料更新成功' : '资料投稿成功');
      toast.show(`${message}，正在打开资料页`, { id, tone: 'success' });
      queueNextAppToast(message);
    },
    failed: (message: string, uncertain: boolean) =>
      toast.show(message, { id, tone: uncertain ? 'warning' : 'error' }),
  };
};
