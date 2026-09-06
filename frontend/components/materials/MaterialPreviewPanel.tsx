import { CSSProperties } from 'react';
import Link from 'next/link';
import AppImage from '../AppImage';
import PaginationBar from '../PaginationBar';
import { MaterialDetail, MaterialPreview } from '../../types/material';
import { SessionUser } from '../../types/user';

interface MaterialPreviewPanelProps {
  embedded?: boolean;
  material: MaterialDetail;
  user: SessionUser | null;
  loginHref: string;
  hasPreviewContent: boolean;
  hasCustomPreview: boolean;
  isManualPreview: boolean;
  isPdfMaterial: boolean;
  previewHint: string;
  preview: MaterialPreview | null;
  previewLoading: boolean;
  previewError: string;
  previewExpanded: boolean;
  previewPage: number;
  previewPageSize: number;
  onPreviewToggle: () => void;
  onPreviewPageChange: (page: number) => void;
}

export default function MaterialPreviewPanel({
  embedded = false,
  material,
  user,
  loginHref,
  hasPreviewContent,
  hasCustomPreview,
  isManualPreview,
  isPdfMaterial,
  previewHint,
  preview,
  previewLoading,
  previewError,
  previewExpanded,
  previewPage,
  previewPageSize,
  onPreviewToggle,
  onPreviewPageChange,
}: MaterialPreviewPanelProps) {
  return (
    <section className="card material-preview">
      {(!embedded || hasPreviewContent) && (
        <div className="material-preview__header">
          <div className="material-preview__header-left">
            {!embedded && <h2>资料预览</h2>}
            {hasPreviewContent && <span className="material-preview__hint">{previewHint}</span>}
          </div>
          {hasPreviewContent && (
            <button type="button" className="button ghost small material-preview__toggle" onClick={onPreviewToggle}>
              {previewExpanded ? '收起预览' : '展示预览'}
            </button>
          )}
        </div>
      )}
      {!previewExpanded ? (
        !hasPreviewContent ? (
          <div className="material-preview__collapsed">
            <p>当前资料暂不支持预览。</p>
          </div>
        ) : !user ? (
          <div className="material-preview__collapsed">
            <p>
              <a className="login-link" href={loginHref}>
                登录
              </a>
              后可查看预览缩略图。
            </p>
            <Link className="button ghost small" href={loginHref}>
              立即登录
            </Link>
          </div>
        ) : (
          <button type="button" className="material-preview__collapsed material-preview__collapsed-btn" onClick={onPreviewToggle}>
            点击查看预览
          </button>
        )
      ) : !user ? (
        <div className="material-preview__locked">
          <p>
            <a className="login-link" href={loginHref}>
              登录
            </a>
            后可查看预览缩略图。
          </p>
          <Link className="button ghost small" href={loginHref}>
            立即登录
          </Link>
        </div>
      ) : (
        <>
          {hasCustomPreview && (
            <div className="material-custom-preview">
              <div className="material-custom-preview__header">
                <h3>作者自定义预览</h3>
                <span className="material-custom-preview__hint">图文展示</span>
              </div>
              {material.customPreviewText && <div className="material-custom-preview__text">{material.customPreviewText}</div>}
              {material.customPreviewImages && material.customPreviewImages.length > 0 && (
                <div className="material-custom-preview__grid">
                  {material.customPreviewImages.map((url, index) => (
                    <AppImage key={`${url}-${index}`} src={url} alt={`预览图 ${index + 1}`} loading="lazy" decoding="async" />
                  ))}
                </div>
              )}
            </div>
          )}
          {isManualPreview || isPdfMaterial ? (
            previewLoading ? (
              <p className="help-text">预览生成中，请稍候刷新。</p>
            ) : previewError ? (
              <p className="error-text">{previewError}</p>
            ) : preview?.status === 'failed' ? (
              <p className="help-text">预览生成失败，请稍后重试。</p>
            ) : preview?.status === 'done' && preview.images.length > 0 ? (
              <>
                <div className="material-preview__grid">
                  {preview.images.slice((previewPage - 1) * previewPageSize, previewPage * previewPageSize).map((item) => {
                    const lqipStyle = item.lqip ? ({ '--lqip': `url(${item.lqip})` } as CSSProperties) : undefined;
                    const hasLqip = Boolean(item.lqip);
                    return (
                      <div key={item.index} className={`material-preview__page${hasLqip ? ' has-lqip' : ''}`} style={lqipStyle}>
                        <picture>
                          {item.avif?.srcSet && (
                            <source type="image/avif" srcSet={item.avif.srcSet} sizes={item.avif.sizes || item.img.sizes || undefined} />
                          )}
                          {item.webp?.srcSet && (
                            <source type="image/webp" srcSet={item.webp.srcSet} sizes={item.webp.sizes || item.img.sizes || undefined} />
                          )}
                          <img
                            src={item.img.src}
                            srcSet={item.img.srcSet || undefined}
                            sizes={item.img.sizes || undefined}
                            alt={`预览第 ${item.index} 页`}
                            decoding="async"
                            loading={previewPage === item.index ? 'eager' : 'lazy'}
                            fetchPriority={previewPage === item.index ? 'high' : undefined}
                          />
                        </picture>
                        <span className="material-preview__label">第 {item.index} 页</span>
                      </div>
                    );
                  })}
                </div>
                <PaginationBar
                  currentPage={previewPage}
                  totalItems={preview.images.length}
                  pageSize={previewPageSize}
                  onPageChange={onPreviewPageChange}
                  className="materials-pagination material-preview__pagination"
                />
              </>
            ) : (
              <p className="help-text">预览生成中，请稍后刷新。</p>
            )
          ) : (
            !hasCustomPreview && <p className="help-text">当前资料暂不支持预览。</p>
          )}
        </>
      )}
    </section>
  );
}
