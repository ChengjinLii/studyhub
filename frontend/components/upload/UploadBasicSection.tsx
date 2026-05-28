import Link from 'next/link';
import AppImage from '../AppImage';
import UploadSectionLabel from './UploadSectionLabel';

interface UploadBasicSectionProps {
  isExperience: boolean;
  isQuickMode: boolean;
  experienceHeading: string;
  title: string;
  description: string;
  descriptionLimit: number;
  maxTitleLength: number;
  price: string;
  priceSummary: string;
  hasPayoutQr: boolean;
  customPreviewTitle: string;
  customPreviewHint: string;
  customPreviewLabel: string;
  customPreviewFiles: File[];
  customPreviewNotice: string | null;
  existingCustomPreviewImages: string[];
  maxCustomPreviewImages: number;
  customPreviewInputRef: React.RefObject<HTMLInputElement>;
  onTitleChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onPriceChange: (value: string) => void;
  onPriceBlur: () => void;
  onCustomPreviewSelection: (files: FileList | null) => void;
  onClearCustomPreviewFiles: () => void;
  onRemoveCustomPreviewFile: (index: number) => void;
  onClearCustomPreviewAll: () => void;
}

export default function UploadBasicSection({
  isExperience,
  isQuickMode,
  experienceHeading,
  title,
  description,
  descriptionLimit,
  maxTitleLength,
  price,
  priceSummary,
  hasPayoutQr,
  customPreviewTitle,
  customPreviewHint,
  customPreviewLabel,
  customPreviewFiles,
  customPreviewNotice,
  existingCustomPreviewImages,
  maxCustomPreviewImages,
  customPreviewInputRef,
  onTitleChange,
  onDescriptionChange,
  onPriceChange,
  onPriceBlur,
  onCustomPreviewSelection,
  onClearCustomPreviewFiles,
  onRemoveCustomPreviewFile,
  onClearCustomPreviewAll,
}: UploadBasicSectionProps) {
  return (
    <div className="upload-section-shell" id="upload-basic">
      <div className="upload-section-heading">
        <div className="upload-section-heading__copy">
          <h2 className="upload-section-heading__title">基础信息</h2>
        </div>
      </div>
      <section className="card upload-main-card upload-section-card">
        <div className="form-grid upload-section-grid">
          <div className="form-item full">
            <UploadSectionLabel
              htmlFor="title"
              text={isExperience ? `${experienceHeading}标题` : '资料标题'}
              optional={isQuickMode}
            />
            <input
              id="title"
              value={title}
              onChange={(e) => onTitleChange(e.target.value)}
              required={!isQuickMode}
              placeholder={isQuickMode ? '可留空，系统将优先使用文件名自动生成标题' : undefined}
            />
            <p className="help-text">
              {isQuickMode
                ? `标题可留空；如已上传文件会自动生成，当前：${title.length}`
                : `标题需在 ${maxTitleLength} 个字符以内，当前：${title.length}`}
            </p>
          </div>
          {!isQuickMode && (
            <div className="form-item full">
              <UploadSectionLabel
                htmlFor="description"
                text={isExperience ? `${experienceHeading}内容` : '资料简介'}
                optional={!isExperience}
              />
              <textarea
                id="description"
                value={description}
                onChange={(e) => onDescriptionChange(e.target.value)}
                placeholder={isExperience ? '写下你的经验分享，支持 Markdown 语法' : '支持 Markdown 语法'}
                maxLength={descriptionLimit}
                required={isExperience}
              />
              <p className="help-text">
                {isExperience
                  ? `内容支持 Markdown 语法，当前：${description.length}`
                  : `资料简介需在 ${descriptionLimit} 个字符以内，当前：${description.length}`}
              </p>
            </div>
          )}
          {isExperience && (
            <div className="form-item full">
              <UploadSectionLabel text={customPreviewTitle} optional />
              <p className="help-text">{customPreviewHint}</p>
              <div
                className="file-field drop-zone"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  onCustomPreviewSelection(e.dataTransfer.files);
                }}
              >
                <span className="file-trigger">选择{customPreviewLabel}</span>
                <span className="file-name">
                  {customPreviewFiles.length
                    ? `已选择 ${customPreviewFiles.length} 张配图`
                    : `单张 ≤ 5MB，最多 ${maxCustomPreviewImages} 张`}
                </span>
                {customPreviewFiles.length > 0 && (
                  <button
                    type="button"
                    className="file-clear"
                    onClick={onClearCustomPreviewFiles}
                    aria-label="清空配图"
                  >
                    x
                  </button>
                )}
                <input
                  type="file"
                  ref={customPreviewInputRef}
                  accept="image/*"
                  multiple
                  onChange={(e) => onCustomPreviewSelection(e.target.files)}
                />
              </div>
              {customPreviewFiles.length > 0 && (
                <div className="inline-group wrap" style={{ marginTop: 8 }}>
                  {customPreviewFiles.map((file, index) => (
                    <span key={`${file.name}-${index}`} className="badge-outline">
                      {file.name}
                      <button
                        type="button"
                        className="file-clear"
                        onClick={() => onRemoveCustomPreviewFile(index)}
                        aria-label={`移除 ${file.name}`}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
              {customPreviewNotice && <p className="error-text">{customPreviewNotice}</p>}
              {existingCustomPreviewImages.length > 0 && customPreviewFiles.length === 0 && (
                <div className="custom-preview-existing">
                  <p className="help-text">已存在 {existingCustomPreviewImages.length} 张配图。</p>
                  <div className="custom-preview-existing__grid">
                    {existingCustomPreviewImages.map((url, index) => (
                      <AppImage key={`${url}-${index}`} src={url} alt={`已上传配图 ${index + 1}`} loading="lazy" />
                    ))}
                  </div>
                </div>
              )}
              {(customPreviewFiles.length > 0 || existingCustomPreviewImages.length > 0) && (
                <button type="button" className="text-button" onClick={onClearCustomPreviewAll}>
                  清空配图
                </button>
              )}
            </div>
          )}
          {!isExperience && (
            <div className="form-item full">
              <UploadSectionLabel htmlFor="price" text="价格（元）" />
              <input
                id="price"
                value={price}
                inputMode="numeric"
                pattern="[0-9]*"
                placeholder="0"
                onChange={(e) => onPriceChange(e.target.value)}
                onBlur={onPriceBlur}
              />
              {priceSummary && <p className="help-text">默认免费；{priceSummary}</p>}
              <div className={`upload-price-payout-tip ${hasPayoutQr ? 'is-ready' : 'is-missing'}`}>
                <div className="upload-price-payout-tip__text">
                  {hasPayoutQr
                    ? '已检测到你已上传个人收款码，可直接投稿。'
                    : '你还未上传个人收款码，建议先补充，方便后续收益打款。'}
                </div>
                {!hasPayoutQr && (
                  <Link className="button ghost small upload-price-payout-tip__action" href="/me#profile">
                    去上传
                  </Link>
                )}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
