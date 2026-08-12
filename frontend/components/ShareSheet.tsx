import { useEffect, useMemo, useState } from 'react';
import { copyToClipboard, tryNativeShare } from '../lib/share';
import { useAppToast } from './AppToastProvider';

interface ShareSheetProps {
  open: boolean;
  title: string;
  text: string;
  linkUrl?: string;
  onClose: () => void;
}

export default function ShareSheet({ open, title, text, linkUrl, onClose }: ShareSheetProps) {
  const toast = useAppToast();
  const [canShare, setCanShare] = useState(false);
  const isMulti = useMemo(() => text.includes('\n'), [text]);

  useEffect(() => {
    if (typeof navigator === 'undefined') return;
    setCanShare(Boolean(navigator.share));
  }, []);

  if (!open) return null;

  const handleCopy = async () => {
    const ok = await copyToClipboard(text);
    if (ok) {
      toast.show('已复制链接，可以直接分享', { tone: 'success' });
      return;
    }
    toast.show('复制失败，请长按链接手动复制', { tone: 'error' });
  };

  const handleNativeShare = async () => {
    const ok = await tryNativeShare({ title, text, url: linkUrl });
    if (ok) {
      toast.show('已唤起系统分享', { tone: 'success' });
      return;
    }
    toast.show('无法唤起系统分享，请尝试复制链接', { tone: 'error' });
  };

  const handleSelect = (event: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    event.target.select();
  };

  return (
    <div className="share-sheet-mask" onClick={onClose} role="dialog" aria-modal="true">
      <div className="share-sheet" onClick={(event) => event.stopPropagation()}>
        <div className="share-sheet__header">
          <div>
            <div className="share-sheet__title">{title}</div>
            <div className="share-sheet__subtitle">手机端可用系统分享或长按复制链接</div>
          </div>
          <button className="share-sheet__close" type="button" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </div>
        <div className="share-sheet__body">
          {isMulti ? (
            <textarea
              className="share-sheet__input"
              value={text}
              readOnly
              rows={5}
              onFocus={handleSelect}
            />
          ) : (
            <input className="share-sheet__input" value={text} readOnly onFocus={handleSelect} />
          )}
        </div>
        <div className="share-sheet__actions">
          {canShare && (
            <button className="button primary" type="button" onClick={handleNativeShare}>
              系统分享
            </button>
          )}
          <button className="button ghost" type="button" onClick={handleCopy}>
            复制链接
          </button>
          {linkUrl && (
            <a className="button ghost" href={linkUrl} target="_blank" rel="noopener noreferrer">
              打开链接
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
