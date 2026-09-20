import { BatchItem } from '../types/batch';

export const MAX_BATCH_FILE_BYTES = 50 * 1024 * 1024;
export const MAX_BATCH_BYTES = 100 * 1024 * 1024;
export const batchStatusLabel = (value: string) => ({
  DRAFT: '上传待完成', WAITING: '等待整理', REVIEW: '整理中', RETURNED: '待补充',
  PARTIAL: '部分发布', PUBLISHED: '已发布', REJECTED: '待清理', CLEANED: '已清理',
  PENDING: '等待处理', UPLOADING: '上传中', UPLOADED: '已上传', SCANNING: '检查中',
  CLEAN: '检查通过', INFECTED: '检查未通过', ERROR: '处理失败，请管理员重试',
  NOT_APPLICABLE: '网盘待人工检查', EXPIRED: '未完成投稿已过期',
} as Record<string, string>)[value] || value;
export function validateBatchFiles(files: readonly { name: string; size: number }[]): string | null {
  if (!files.length) return '请选择资料文件';
  if (files.length > 20) return '每批最多 20 个文件';
  if (files.some(file => file.size <= 0 || file.size > MAX_BATCH_FILE_BYTES)) return '文件不能为空，且每个文件不得超过 50 MiB';
  if (files.reduce((sum, file) => sum + file.size, 0) > MAX_BATCH_BYTES) return '每批文件总大小不得超过 100 MiB';
  if (new Set(files.map(file => file.name)).size !== files.length) return '同一批次不能包含同名文件';
  return null;
}
export function safeBatchUrl(value: string): string | null {
  try {
    const url = new URL(value, 'https://studyhub.invalid');
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    return value;
  } catch { return null; }
}
export function matchBatchFiles(items: BatchItem[], files: File[]): Map<string, File> {
  const result = new Map<string, File>();
  for (const file of files) {
    const matches = items.filter(item => item.name === file.name && item.sizeBytes === file.size);
    if (matches.length !== 1 || result.has(String(matches[0].id))) throw new Error('服务端文件清单不匹配，请联系管理员');
    result.set(String(matches[0].id), file);
  }
  if (result.size !== items.length) throw new Error('服务端文件清单不完整，请联系管理员');
  return result;
}
// Sequential uploads retain acknowledgements even when a later upload fails.
export async function uploadPendingBatchItems(items: BatchItem[], files: File[], completed: Set<string>,
  upload: (item: BatchItem, file: File) => Promise<unknown>, onProgress: (item: BatchItem, state: string) => void) {
  const matched = matchBatchFiles(items, files);
  let failed = false;
  for (const item of items) {
    if (completed.has(String(item.id))) continue;
    onProgress(item, '上传中');
    try {
      await upload(item, matched.get(String(item.id))!);
      completed.add(String(item.id));
      onProgress(item, '已上传');
    } catch (error) {
      failed = true;
      onProgress(item, error instanceof Error ? `失败：${error.message}` : '上传失败');
    }
  }
  if (failed) throw new Error('部分文件上传失败，请重试；已成功的文件将保留');
}
