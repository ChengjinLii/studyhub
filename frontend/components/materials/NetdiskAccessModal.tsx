import { useEffect, useId, useState } from 'react';
import { copyToClipboard } from '../../lib/share';

interface NetdiskAccessModalProps {
  open: boolean;
  title: string;
  url: string;
  password?: string | null;
  expiredAt?: string | null;
  reminder?: string | null;
  onClose: () => void;
}

export const buildNetdiskCopyText = (url: string, password?: string | null) =>
  [`网盘链接：${url}`, password ? `提取码：${password}` : ''].filter(Boolean).join('\n');

export const resolveNetdiskOpenUrl = (value: string) => {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : null;
  } catch {
    return null;
  }
};

export default function NetdiskAccessModal({
  open,
  title,
  url,
  password,
  expiredAt,
  reminder,
  onClose,
}: NetdiskAccessModalProps) {
  const titleId = useId();
  const [notice, setNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const openUrl = resolveNetdiskOpenUrl(url);

  useEffect(() => {
    if (!open) return;
    setNotice(null);
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose, open]);

  if (!open) return null;

  const handleCopy = async (value: string, successText: string) => {
    const copied = await copyToClipboard(value);
    setNotice({
      type: copied ? 'success' : 'error',
      text: copied ? successText : '复制失败，请长按内容手动复制。',
    });
  };

  return (
    <div className="modal-mask netdisk-access-mask" onClick={onClose}>
      <section
        className="modal-card netdisk-access-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <button className="modal-close" type="button" aria-label="关闭网盘信息" onClick={onClose}>
          ×
        </button>
        <div className="netdisk-access-modal__heading">
          <span>网盘资源</span>
          <h2 id={titleId}>{title}</h2>
          <p>链接与提取码仅供本人学习使用，请勿公开传播。</p>
        </div>
        <div className="netdisk-access-modal__details">
          <div className="netdisk-access-modal__field">
            <span>网盘链接</span>
            <div>
              <p>{url}</p>
              <button type="button" onClick={() => handleCopy(url, '网盘链接已复制。')}>复制链接</button>
            </div>
          </div>
          <div className="netdisk-access-modal__field">
            <span>提取码</span>
            <div>
              <p>{password || '无需提取码'}</p>
              {password && (
                <button type="button" onClick={() => handleCopy(password, '提取码已复制。')}>复制提取码</button>
              )}
            </div>
          </div>
          {expiredAt && <p className="netdisk-access-modal__meta">建议在 {expiredAt} 前检查链接有效性。</p>}
          {reminder && <p className="netdisk-access-modal__meta">投稿者提醒：{reminder}</p>}
        </div>
        <div className="netdisk-access-modal__actions">
          <button
            className="button primary"
            type="button"
            onClick={() => handleCopy(buildNetdiskCopyText(url, password), '链接和提取码已复制。')}
          >
            一键复制
          </button>
          {openUrl && (
            <a className="button ghost" href={openUrl} target="_blank" rel="noopener noreferrer">
              打开网盘
            </a>
          )}
        </div>
        {notice && <p className={notice.type === 'success' ? 'success-text' : 'error-text'}>{notice.text}</p>}
      </section>
    </div>
  );
}
