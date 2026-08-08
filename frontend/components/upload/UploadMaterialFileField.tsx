import { DragEvent, RefObject, useRef, useState } from 'react';
import { buildZipName } from '../../lib/uploadAssets';
import UploadSectionLabel from './UploadSectionLabel';

interface UploadMaterialFileFieldProps {
  file: File | null;
  sourceCount: number;
  preparing: boolean;
  isEditing: boolean;
  placeholder: string;
  title: string;
  maxTitleLength: number;
  inputRef: RefObject<HTMLInputElement>;
  uploadProgress: number | null;
  onFilesSelected: (files: FileList | null) => void | Promise<void>;
  onClear: () => void;
}

const formatFileSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export default function UploadMaterialFileField({
  file,
  sourceCount,
  preparing,
  isEditing,
  placeholder,
  title,
  maxTitleLength,
  inputRef,
  uploadProgress,
  onFilesSelected,
  onClear,
}: UploadMaterialFileFieldProps) {
  const [dragActive, setDragActive] = useState(false);
  const dragDepthRef = useRef(0);

  const handleDragEnter = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragDepthRef.current += 1;
    setDragActive(true);
  };

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setDragActive(false);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragDepthRef.current = 0;
    setDragActive(false);
    if (event.dataTransfer.files.length > 0) {
      void onFilesSelected(event.dataTransfer.files);
      event.dataTransfer.clearData();
    }
  };

  const selectedName = preparing
    ? '正在打包文件...'
    : file
      ? sourceCount > 1
        ? `已选择 ${sourceCount} 个文件，打包为 ${buildZipName(
            title,
            file.name.replace(/\.zip$/i, ''),
            maxTitleLength
          )}`
        : file.name
      : isEditing
        ? '保持现有文件（可重新上传）'
        : placeholder;

  return (
    <div className="form-item full">
      <UploadSectionLabel htmlFor="zip" text="资料文件（总大小≤50MB，支持多文件）" />
      <div
        className={`file-field drop-zone material-file-dropzone${file || preparing ? ' has-file' : ''}${
          preparing ? ' is-preparing' : ''
        }${dragActive ? ' is-dragover' : ''}`}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <span className="material-file-dropzone__copy">
          <span className="file-trigger">
            {dragActive ? '松开即可添加' : preparing ? '正在处理文件' : file ? '更换文件' : '选择 / 拖拽 文件'}
          </span>
          <span className="file-name">{selectedName}</span>
          {file && !preparing && <span className="material-file-dropzone__meta">{formatFileSize(file.size)}</span>}
        </span>
        {(file || preparing) && (
          <span className="material-file-dropzone__status">{preparing ? '处理中' : '已添加'}</span>
        )}
        {(file || preparing) && (
          <button type="button" className="file-clear" onClick={onClear} aria-label="移除文件">
            ×
          </button>
        )}
        <input
          id="zip"
          type="file"
          ref={inputRef}
          multiple
          onChange={(event) => void onFilesSelected(event.target.files)}
        />
      </div>
      {uploadProgress !== null && (
        <div className="upload-progress" aria-live="polite">
          <progress value={uploadProgress} max={100} />
          <span className="upload-percent">{uploadProgress}%</span>
        </div>
      )}
      <p className="help-text">将文件拖拽到此区域或点击选择，总大小不超过 50MB，多文件将自动打包为 zip。</p>
    </div>
  );
}
