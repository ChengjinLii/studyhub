import AppImage from '../AppImage';

interface AdminPayoutQrModalProps {
  open: boolean;
  loading: boolean;
  error: string | null;
  url: string | null;
  title: string;
  onClose: () => void;
}

export default function AdminPayoutQrModal({
  open,
  loading,
  error,
  url,
  title,
  onClose,
}: AdminPayoutQrModalProps) {
  if (!open) return null;
  return (
    <div className="modal-mask" role="presentation" onClick={onClose}>
      <div className="modal-card wechat-modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" type="button" onClick={onClose} aria-label="关闭弹窗">
          ×
        </button>
        <h2 className="wechat-modal__title">{title || '收款码'}</h2>
        {loading && <p className="wechat-modal__hint">收款码加载中...</p>}
        {!loading && error && <p className="error-text">{error}</p>}
        {!loading && !error && url && (
          <>
            <p className="wechat-modal__hint">请核对收款码后再进行线下打款。</p>
            <AppImage src={url} alt="用户收款码" loading="lazy" />
          </>
        )}
      </div>
    </div>
  );
}
