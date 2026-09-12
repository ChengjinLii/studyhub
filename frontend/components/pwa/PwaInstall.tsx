import { useEffect, useId, useRef, useState } from 'react';
import { useRouter } from 'next/router';
import { Copy, Download, LoaderCircle, X } from 'lucide-react';
import { detectInstallClient, installSteps, InstallPromptEvent } from '../../lib/pwaInstall';
import { copyToClipboard } from '../../lib/share';
import styles from './PwaInstall.module.css';

export default function PwaInstall() {
  const router = useRouter();
  const [copyStatus, setCopyStatus] = useState('');
  const [client, setClient] = useState<ReturnType<typeof detectInstallClient> | null>(null);
  const [installed, setInstalled] = useState(false);
  const [suppressed, setSuppressed] = useState(false);
  const [bottom, setBottom] = useState(88);
  const [help, setHelp] = useState(false);
  const [busy, setBusy] = useState(false);
  const [promptFailed, setPromptFailed] = useState(false);
  const prompt = useRef<InstallPromptEvent | null>(null);
  const prompting = useRef(false);
  const installationAccepted = useRef(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  useEffect(() => {
    const mode = window.matchMedia('(display-mode: standalone), (display-mode: fullscreen), (display-mode: minimal-ui)');
    const mobile = window.matchMedia('(max-width: 1024px)');
    const sync = () => {
      setInstalled(installationAccepted.current || mode.matches || (navigator as Navigator & { standalone?: boolean }).standalone === true);
      setClient(window.isSecureContext && mobile.matches
        ? detectInstallClient(navigator.userAgent, navigator.platform, navigator.maxTouchPoints, window.matchMedia('(pointer: coarse)').matches)
        : null);
    };
    const onPrompt = (event: Event) => {
      const candidate = event as InstallPromptEvent;
      if (typeof candidate.prompt !== 'function') return;
      // Keep the native desktop installation UI; only replace it on touch/mobile clients.
      const current = detectInstallClient(navigator.userAgent, navigator.platform, navigator.maxTouchPoints, window.matchMedia('(pointer: coarse)').matches);
      if (!mobile.matches || !current.mobile) return;
      event.preventDefault();
      installationAccepted.current = false;
      setInstalled(false);
      prompt.current = candidate;
      setPromptFailed(false);
    };
    const onInstalled = () => {
      installationAccepted.current = true;
      prompt.current = null;
      setInstalled(true);
      setHelp(false);
    };
    sync();
    mode.addEventListener('change', sync);
    mobile.addEventListener('change', sync);
    window.addEventListener('beforeinstallprompt', onPrompt);
    window.addEventListener('appinstalled', onInstalled);
    return () => {
      mode.removeEventListener('change', sync);
      mobile.removeEventListener('change', sync);
      window.removeEventListener('beforeinstallprompt', onPrompt);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);

  useEffect(() => {
    const update = () => {
      const active = document.activeElement;
      const editing = active instanceof HTMLElement && (active.matches('input:not([type=checkbox]):not([type=radio]), textarea, select') || active.isContentEditable);
      const viewport = window.visualViewport;
      setSuppressed(editing || Boolean(viewport && window.innerHeight - viewport.height > 150));
      const nav = document.querySelector('.mobile-bottom-nav');
      const rect = nav?.getBoundingClientRect();
      setBottom(rect && rect.height > 0 ? Math.max(0, window.innerHeight - rect.top) + 12 : 16);
    };
    const onBlur = () => { frame = window.requestAnimationFrame(update); };
    let frame = 0;
    const observer = new ResizeObserver(update);
    const nav = document.querySelector('.mobile-bottom-nav');
    if (nav) observer.observe(nav);
    update();
    window.addEventListener('resize', update);
    window.addEventListener('focusin', update);
    window.addEventListener('focusout', onBlur);
    window.visualViewport?.addEventListener('resize', update);
    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(frame);
      window.removeEventListener('resize', update);
      window.removeEventListener('focusin', update);
      window.removeEventListener('focusout', onBlur);
      window.visualViewport?.removeEventListener('resize', update);
    };
  }, [router.asPath]);

  const visible = Boolean(client?.mobile && !installed && !suppressed);
  useEffect(() => {
    window.dispatchEvent(new Event('pwa:layout'));
  }, [visible, bottom]);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (!help) {
      if (element.open) element.close();
      return;
    }
    const previous = document.body.style.overflow;
    const opener = trigger.current;
    element.showModal();
    document.body.style.overflow = 'hidden';
    return () => {
      if (element.open) element.close();
      document.body.style.overflow = previous;
      opener?.focus({ preventScroll: true });
    };
  }, [help]);

  const install = async () => {
    if (prompting.current) return;
    const available = prompt.current;
    if (!available) { setHelp(true); return; }
    prompting.current = true;
    prompt.current = null; // A beforeinstallprompt event can only be used once.
    setBusy(true);
    try {
      await available.prompt();
      const choice = await available.userChoice;
      if (choice.outcome === 'accepted') {
        installationAccepted.current = true;
        setInstalled(true);
        setHelp(false);
      }
    } catch {
      setPromptFailed(true);
      setHelp(true);
    } finally {
      prompting.current = false;
      setBusy(false);
    }
  };

  return <>
    {visible && <button ref={trigger} type="button" className={styles.install} data-pwa-install
      style={{ bottom: `max(${bottom}px, calc(16px + env(safe-area-inset-bottom)))` }}
      aria-label="安装 StudyHub" title="安装 StudyHub" disabled={busy} onClick={() => void install()}>
      {busy ? <LoaderCircle size={24} className={styles.spin} aria-hidden="true" /> : <Download size={25} strokeWidth={1.8} aria-hidden="true" />}
    </button>}
    <dialog ref={dialog} className={styles.dialog} aria-labelledby={titleId}
      onCancel={() => setHelp(false)} onClick={(event) => { if (event.target === dialog.current) {
        const rect = dialog.current.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) setHelp(false);
      } }}>
      <button type="button" className={styles.close} aria-label="关闭安装指引" onClick={() => setHelp(false)} autoFocus><X size={21} /></button>
      <div className={styles.brand}>
        {/* Existing application artwork, shared with the installed app. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/icons/bot-192.png" alt="" width={52} height={52} />
        <div><h2 id={titleId}>StudyHub <span>学汇</span></h2><p>添加到主屏幕</p></div>
      </div>
      {promptFailed && <p className={styles.notice} role="status">安装窗口未能打开，请通过浏览器菜单添加。</p>}
      <ol className={styles.steps}>{installSteps(client?.platform || 'other', client?.embedded || false).map(step => <li key={step}>{step}</li>)}</ol>
      <p className={styles.note}>登录、下载、支付和投稿仍需联网。部分设备首次打开时需要重新登录。</p>
      <button type="button" className={styles.copy} onClick={async () => {
        const ok = await copyToClipboard(`${window.location.origin}/`);
        setCopyStatus(ok ? '网站地址已复制' : '复制失败，请从地址栏复制');
      }}><Copy size={17} aria-hidden="true" />复制网站地址</button>
      {copyStatus && <p className={styles.note} role="status">{copyStatus}</p>}
    </dialog>
  </>;
}
