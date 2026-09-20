import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { FormEvent, useEffect, useRef, useState } from 'react';
import { Copy, Trash2, Upload } from 'lucide-react';
import NavBar from '../../components/NavBar';
import OwnBatchStatus from '../../components/batch/OwnBatchStatus';
import { readSession } from '../../lib/auth';
import { createBatch, submitBatch, uploadBatchItem } from '../../lib/batchApi';
import { safeBatchUrl, uploadPendingBatchItems, validateBatchFiles } from '../../lib/batchSubmission';
import { toErrorMessage } from '../../lib/errors';
import { BatchDetail, CreateBatch, PublicationIntent } from '../../types/batch';
import { SessionUser } from '../../types/user';
import styles from '../../styles/Batch.module.css';

export default function BatchUploadPage({ user }: { user: SessionUser }) {
  const [method, setMethod] = useState<'FILE' | 'NETDISK'>('FILE');
  const [intent, setIntent] = useState<PublicationIntent | ''>('');
  const [files, setFiles] = useState<File[]>([]);
  const [pricingNote, setPricingNote] = useState('');
  const [netdiskUrl, setNetdiskUrl] = useState('');
  const [netdiskPassword, setNetdiskPassword] = useState('');
  const [note, setNote] = useState('');
  const [consent, setConsent] = useState(false);
  const [batch, setBatch] = useState<BatchDetail | null>(null);
  const [locked, setLocked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [copied, setCopied] = useState(false);
  const [progress, setProgress] = useState<Record<string, string>>({});
  const payload = useRef<CreateBatch | null>(null);
  const completed = useRef(new Set<string>());
  const running = useRef(false);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    if (locked && !done) window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [locked, done]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (running.current || done) return;
    setError('');
    if (!payload.current) {
      const validation = method === 'FILE' ? validateBatchFiles(files) : (!/^https?:\/\//i.test(netdiskUrl) || !safeBatchUrl(netdiskUrl) ? '请输入有效的 HTTP(S) 网盘链接' : null);
      if (validation || !intent || !consent) { setError(validation || '请选择发布意向并确认授权'); return; }
      payload.current = { submissionId: crypto.randomUUID(), deliveryMethod: method, publicationIntent: intent,
        pricingNote, netdiskUrl: method === 'NETDISK' ? netdiskUrl : '', netdiskPassword: method === 'NETDISK' ? netdiskPassword : '', note, consent: true,
        files: method === 'FILE' ? files.map(file => ({ name: file.name, sizeBytes: file.size, contentType: file.type || 'application/octet-stream' })) : [] };
      setLocked(true);
    }
    running.current = true; setBusy(true);
    try {
      const current = batch ?? await createBatch(payload.current);
      setBatch(current);
      if (method === 'FILE') await uploadPendingBatchItems(current.items, files, completed.current,
        (item, file) => uploadBatchItem(current.id, item.id, file, percentage => setProgress(previous => ({ ...previous, [item.name]: percentage === 100 ? '服务器保存中' : `上传 ${percentage}%` }))),
        (item, state) => setProgress(previous => ({ ...previous, [item.name]: state })));
      await submitBatch(current.id);
      setDone(true);
    } catch (err) { setError(toErrorMessage(err, '提交失败，请重试')); }
    finally { running.current = false; setBusy(false); }
  }
  function addFiles(selected: FileList | null) {
    if (!selected) return;
    const next = [...files, ...Array.from(selected)];
    const validation = validateBatchFiles(next);
    if (validation) { setError(validation); return; }
    setFiles(next); setError('');
  }
  return <><NavBar user={user} /><main className={`container ${styles.page}`}>
    <section className={styles.section}><Link href="/upload">单份投稿</Link><h1>批量投稿</h1>
      <p>无需填写标题、课程等资料信息，管理员将统一整理后发布，并关联你的账号。</p>
      <p className={styles.muted}>每个文件上限 50 MB，每批上限 100 MB、20 个文件；与普通投稿共享每日 256 MB 文件额度。网盘内容大小不受此限制。</p>
      <div className={styles.row}><span>也可以私聊管理员投稿：</span><strong>QQ：2731938007</strong>
        <button type="button" className={styles.icon} title="复制管理员 QQ" aria-label="复制管理员 QQ" onClick={async () => { try { await navigator.clipboard.writeText('2731938007'); setCopied(true); } catch { setError('复制失败，请手动选择 QQ 号复制'); } }}><Copy size={18} /></button>
        {copied && <span role="status">QQ 号已复制</span>}</div></section>
    <section className={styles.section}>
      {done ? <div role="status"><h2 className={styles.success}>批次 #{batch?.id} 已提交</h2><Link className="button primary" href="/me#batch-submissions">查看投稿状态</Link></div> :
        <form className={styles.form} onSubmit={submit}>
          <fieldset disabled={locked}><legend>交付方式</legend><div className={styles.row}>
            <label><input type="radio" name="delivery" checked={method === 'FILE'} onChange={() => setMethod('FILE')} />文件</label>
            <label><input type="radio" name="delivery" checked={method === 'NETDISK'} onChange={() => setMethod('NETDISK')} />网盘</label></div>
            {method === 'FILE' ? <label className={`${styles.dropzone} ${dragging ? styles.dragging : ''}`}
              onDragOver={event => { event.preventDefault(); if (!locked) setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={event => { event.preventDefault(); setDragging(false); if (!locked) addFiles(event.dataTransfer.files); }}>
              <Upload size={26} /><strong>{files.length ? `已选择 ${files.length} 个文件` : '选择 / 拖拽 文件'}</strong>
              <input aria-label="资料文件" type="file" multiple onChange={event => { addFiles(event.target.files); event.target.value = ''; }} /></label> : <>
              <label className={styles.field}>网盘链接<input type="url" required maxLength={2048} value={netdiskUrl} onChange={event => setNetdiskUrl(event.target.value)} /></label>
              <label className={styles.field}>提取码<input value={netdiskPassword} maxLength={64} onChange={event => setNetdiskPassword(event.target.value)} /></label></>}
          </fieldset>
          {method === 'FILE' && <ul className={styles.list}>{files.map((file, index) => <li key={file.name} className={styles.item}><span className={styles.name}>{file.name} <span className={styles.muted}>({(file.size / 1024 / 1024).toFixed(2)} MiB)</span></span>
            <span role="status">{progress[file.name] || '待上传'}</span><button type="button" disabled={locked} className={styles.icon} title={`移除 ${file.name}`} aria-label={`移除 ${file.name}`} onClick={() => setFiles(previous => previous.filter((_, i) => i !== index))}><Trash2 size={18} /></button></li>)}</ul>}
          <fieldset disabled={locked}><legend>发布意向</legend><div className={styles.row}>{([['FREE', '免费'], ['PAID', '付费'], ['CONTACT', '联系后决定']] as const).map(([value, label]) => <label key={value}><input required type="radio" name="intent" checked={intent === value} onChange={() => setIntent(value)} />{label}</label>)}</div>
            <label className={styles.field}>定价说明（选填）<textarea placeholder="例如：笔记免费，真题解析每份 2 元；合并发布前请联系我。" value={pricingNote} maxLength={2000} onChange={event => setPricingNote(event.target.value)} /></label>
            <label className={styles.field}>投稿备注<textarea placeholder="例如：联系 QQ 号、资料内容说明或其他整理要求" value={note} maxLength={2000} onChange={event => setNote(event.target.value)} /></label>
            <label><input required type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} /> 我拥有分享这些资料的权利，同意管理员审核、整理并按确认的发布意向发布。</label>
          </fieldset>
          {locked && <p className={styles.muted}>批次清单已锁定。请保留此页面直到提交完成。</p>}
          <button className="button primary" disabled={busy} type="submit"><Upload size={18} />{busy ? '正在提交...' : locked ? '重试未完成步骤' : '创建批次并提交'}</button>
          {locked && !batch && !busy && <button className="button ghost" type="button" onClick={() => { payload.current = null; setLocked(false); setError(''); }}>调整投稿信息</button>}
        </form>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
    </section><OwnBatchStatus refreshKey={done ? 1 : 0} />
  </main></>;
}
export const getServerSideProps: GetServerSideProps = async ({ req }) => {
  const { user, token } = readSession(req);
  if (!user || !token) return { redirect: { destination: '/login?next=/upload/batch', permanent: false } };
  return { props: { user } };
};
