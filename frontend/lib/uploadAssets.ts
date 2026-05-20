import JSZip from 'jszip';

const sanitizeFilename = (value: string) =>
  value
    .replace(/[\\/:*?"<>|]+/g, '_')
    .replace(/\s+/g, ' ')
    .trim();

export interface ImageSelectionOptions {
  label: string;
  maxFiles: number;
  maxFileBytes: number;
}

export interface ImageSelectionResult {
  files: File[];
  notice: string | null;
}

export const appendImageFiles = (
  currentFiles: File[],
  files: FileList | File[],
  options: ImageSelectionOptions
): ImageSelectionResult => {
  const next = [...currentFiles];
  let notice: string | null = null;

  Array.from(files).forEach((file) => {
    if (!file.type.startsWith('image/')) {
      notice = notice || `${file.name} 不是图片格式`;
      return;
    }
    if (file.size > options.maxFileBytes) {
      notice = notice || `${file.name} 超过 5MB`;
      return;
    }
    if (next.length >= options.maxFiles) {
      notice = notice || `最多上传 ${options.maxFiles} 张${options.label}`;
      return;
    }
    next.push(file);
  });

  return { files: next, notice };
};

export const buildZipName = (titleValue: string, fallbackName: string, maxTitleLength: number) => {
  const base = sanitizeFilename(titleValue || fallbackName || '资料');
  const trimmed = base.slice(0, maxTitleLength).trim() || '资料';
  const normalized = trimmed.replace(/\.zip$/i, '');
  return `${normalized}.zip`;
};

export const resolveZipFileName = (file: File, titleValue: string, maxTitleLength: number) => {
  const fallback = file.name.replace(/\.zip$/i, '') || '资料';
  const zipName = buildZipName(titleValue, fallback, maxTitleLength);
  if (file.name === zipName) return file;
  return new File([file], zipName, {
    type: file.type || 'application/zip',
    lastModified: file.lastModified,
  });
};

export const zipFiles = async (files: File[], zipName: string, maxFileBytes: number) => {
  const zip = new JSZip();
  files.forEach((file) => {
    zip.file(file.name, file);
  });
  const blob = await zip.generateAsync({ type: 'blob', compression: 'DEFLATE', compressionOptions: { level: 6 } });
  if (blob.size > maxFileBytes) {
    throw new Error('打包后的文件超过 50MB，请删除部分文件或改用网盘链接。');
  }
  return new File([blob], zipName, { type: 'application/zip', lastModified: Date.now() });
};

export const zipMarkdownContent = async (
  titleValue: string,
  content: string,
  maxFileBytes: number,
  maxTitleLength: number
) => {
  const zip = new JSZip();
  zip.file('experience.md', content);
  const zipName = buildZipName(titleValue, '经验分享', maxTitleLength);
  const blob = await zip.generateAsync({ type: 'blob', compression: 'DEFLATE', compressionOptions: { level: 6 } });
  if (blob.size > maxFileBytes) {
    throw new Error('内容过长，打包后超过 50MB。');
  }
  return new File([blob], zipName, { type: 'application/zip', lastModified: Date.now() });
};
