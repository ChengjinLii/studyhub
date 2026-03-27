export type SharePayload = {
  title: string;
  text?: string;
  url?: string;
};

export const canNativeShare = () =>
  typeof navigator !== 'undefined' && typeof navigator.share === 'function';

export const tryNativeShare = async (payload: SharePayload) => {
  if (!canNativeShare()) return false;
  try {
    await navigator.share(payload);
    return true;
  } catch {
    return false;
  }
};

export const isLikelyMobile = () => {
  if (typeof window === 'undefined') return false;
  const ua = navigator.userAgent || '';
  const uaMatch = /Android|iPhone|iPad|iPod|Mobile|IEMobile|Opera Mini/i.test(ua);
  if (uaMatch) return true;
  if (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) {
    return true;
  }
  return false;
};

export const copyToClipboard = async (value: string) => {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      return false;
    }
  }
  try {
    const textarea = document.createElement('textarea');
    textarea.value = value;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    textarea.style.pointerEvents = 'none';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const copied = document.execCommand('copy');
    document.body.removeChild(textarea);
    return copied;
  } catch {
    return false;
  }
};
