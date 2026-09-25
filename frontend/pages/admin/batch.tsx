import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { FormEvent, useEffect, useRef, useState } from 'react';
import { Download, RefreshCw } from 'lucide-react';
import NavBar from '../../components/NavBar';
import { readSession, resolveAdminPageAccess } from '../../lib/auth';
import { downloadBatchItem, getAdminBatch, listAdminBatches, publishBatch, reviewBatch } from '../../lib/batchApi';
import { batchStatusLabel, safeBatchUrl } from '../../lib/batchSubmission';
import { toErrorMessage } from '../../lib/errors';
import { COURSE_CATEGORY_OPTIONS, SUPPORTED_SCHOOL } from '../../constants/metadata';
import { BatchDetail, BatchId, BatchPage, PublishBatch } from '../../types/batch';
import { SessionUser } from '../../types/user';
import styles from '../../styles/Batch.module.css';

function BatchReview({ batch, reload }: { batch: BatchDetail; reload: () => Promise<void> }) {
  const [selected, setSelected] = useState<BatchId[]>([]);
  const [action, setAction] = useState<'REVIEW' | 'RETURN' | 'REJECT'>('REVIEW');
  const [reason, setReason] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [school, setSchool] = useState(SUPPORTED_SCHOOL);
  const [category, setCategory] = useState<string>(COURSE_CATEGORY_OPTIONS[0].value);
  const [price, setPrice] = useState('0');
  const [college, setCollege] = useState('');
  const [major, setMajor] = useState('');
  const [tags, setTags] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [confirmationNote, setConfirmationNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [pendingPublication, setPendingPublication] = useState<PublishBatch | null>(null);
  const running = useRef(false);
  const locked = busy || !!pendingPublication;
  async function run(task: () => Promise<unknown>, success: string) {
    if (running.current) return;
    running.current = true; setBusy(true); setError(''); setMessage('');
    try {
      await task(); setMessage(success);
      try { await reload(); } catch (err) { setError(`操作已完成，但刷新失败：${toErrorMessage(err, '加载失败')}`); }
    } catch (err) { setError(toErrorMessage(err, '操作失败')); }
    finally { running.current = false; setBusy(false); }
  }
  function review(event: FormEvent) {
    event.preventDefault();
    if (!selected.length || !reason.trim()) { setError('请选择条目并填写审核理由'); return; }
    void run(async () => { await reviewBatch(batch.id, selected, action, reason); setSelected([]); }, '审核已保存');
  }
  function publish(event: FormEvent) {
    event.preventDefault();
    if (!pendingPublication && (!selected.length || !title.trim() || !description.trim() || !school.trim() || !confirmed || !confirmationNote.trim() || !/^\d+(\.\d{1,2})?$/.test(price) || !Number.isFinite(Number(price)) || Number(price) > 10000)) {
      setError('请选择条目，填写发布信息和有效价格，并确认定价'); return;
    }
    if (!pendingPublication && batch.publicationIntent === 'FREE' && Number(price) !== 0) { setError('免费意向的资料必须免费发布'); return; }
    if (!pendingPublication && batch.items.filter(item => selected.includes(item.id)).reduce((sum, item) => sum + item.sizeBytes, 0) > 50 * 1024 * 1024) { setError('合并发布上限为 50 MiB，请拆分所选条目'); return; }
    const payload = pendingPublication ?? { itemIds: [...selected], title: title.trim(), description: description.trim(), school: school.trim(), courseCategory: category,
      college: category === 'GENERAL' ? '' : college.trim(), major: category === 'GENERAL' ? '' : major.trim(), tags: tags.trim(),
      price: Math.round(Number(price) * 100), pricingConfirmed: confirmed, confirmationNote: confirmationNote.trim(), publicationId: crypto.randomUUID() };
    setPendingPublication(payload);
    void run(async () => { await publishBatch(batch.id, payload); setPendingPublication(null); setSelected([]); setConfirmed(false); }, '资料已发布');
  }
  async function download(itemId: BatchId) {
    await run(async () => {
      const result = await downloadBatchItem(batch.id, itemId);
      const url = safeBatchUrl(result.url);
      if (!url || new URL(url, window.location.origin).origin !== window.location.origin) throw new Error('无效的下载链接');
      const anchor = document.createElement('a');
      anchor.href = url; anchor.target = '_blank'; anchor.rel = 'noopener noreferrer'; anchor.click();
    }, '下载链接已打开');
  }
  return <section className={styles.section}>
    <h2>批次 #{batch.id} · {batchStatusLabel(batch.status)}</h2>
    <div className={styles.private}>
      <p>投稿者账号 #{batch.uploaderId} · {batch.deliveryMethod === 'FILE' ? '文件投稿' : '网盘投稿'} · {{ FREE: '免费分享', PAID: '希望付费', CONTACT: '需联系确认' }[batch.publicationIntent]}</p>
      <p>定价说明：{batch.pricingNote || '无'}</p><p>备注：{batch.note || '无'}</p>
      {batch.netdiskUrl && <p>网盘：{safeBatchUrl(batch.netdiskUrl) ? <a href={batch.netdiskUrl} target="_blank" rel="noopener noreferrer">{batch.netdiskUrl}</a> : batch.netdiskUrl}</p>}
      {batch.netdiskPassword && <p>提取码：{batch.netdiskPassword}</p>}
    </div>
    <label><input type="checkbox" disabled={locked || !batch.items.length} checked={!!batch.items.length && selected.length === batch.items.length} onChange={event => { setSelected(event.target.checked ? batch.items.map(item => item.id) : []); setConfirmed(false); }} /> 全选（已选 {selected.length} 项）</label>
    <ul className={styles.list}>{batch.items.map(item => <li className={styles.item} key={item.id}>
      <input aria-label={`选择 ${item.name}`} type="checkbox" disabled={locked} checked={selected.includes(item.id)} onChange={event => { setSelected(previous => event.target.checked ? [...previous, item.id] : previous.filter(id => id !== item.id)); setConfirmed(false); }} />
      <span className={styles.name}>{item.name}<br /><span className={styles.muted}>{(item.sizeBytes / 1024 / 1024).toFixed(2)} MiB · {batchStatusLabel(item.status)} · {batchStatusLabel(item.scanStatus)}{item.reason && ` · ${item.reason}`}</span></span>
      {batch.deliveryMethod === 'FILE' && <button type="button" disabled={busy || ['CLEANED', 'REJECTED', 'PENDING', 'UPLOADING'].includes(item.status)} className={styles.icon} title={`下载 ${item.name}`} aria-label={`下载 ${item.name}`} onClick={() => void download(item.id)}><Download size={18} /></button>}
    </li>)}</ul>
    <form onSubmit={review} className={styles.form}><fieldset disabled={locked}><legend>审核所选条目</legend>
      <label className={styles.field}>操作<select value={action} onChange={event => setAction(event.target.value as typeof action)}><option value="REVIEW">审核通过</option><option value="RETURN">退回修改</option><option value="REJECT">拒绝</option></select></label>
      <label className={styles.field}>审核理由<textarea required maxLength={500} value={reason} onChange={event => setReason(event.target.value)} /></label>
      {action === 'REJECT' && <p className={styles.error}>将清理所选 {selected.length} 项，共 {(batch.items.filter(item => selected.includes(item.id)).reduce((sum, item) => sum + item.sizeBytes, 0) / 1048576).toFixed(2)} MB。已发布条目不能删除。</p>}
      <button className="button secondary" disabled={!selected.length} type="submit">保存审核</button></fieldset></form>
    <form onSubmit={publish} className={`${styles.form} ${styles.section}`}>
      <fieldset disabled={locked}><legend>发布所选条目{selected.length > 1 ? '（合并为 ZIP）' : ''}</legend>
        <p className={styles.muted}>合并 ZIP 上限 50 MiB，超出时请拆分发布。</p>
        <label className={styles.field}>标题<input required maxLength={80} value={title} onChange={event => setTitle(event.target.value)} /></label>
        <label className={styles.field}>描述<textarea required maxLength={3000} value={description} onChange={event => setDescription(event.target.value)} /></label>
        <div className={styles.columns}><label className={styles.field}>学校<input required maxLength={120} value={school} onChange={event => setSchool(event.target.value)} /></label>
          <label className={styles.field}>课程分类<select value={category} onChange={event => setCategory(event.target.value)}>{COURSE_CATEGORY_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label></div>
        {category !== 'GENERAL' && <div className={styles.columns}><label className={styles.field}>学院<input maxLength={120} value={college} onChange={event => setCollege(event.target.value)} /></label><label className={styles.field}>专业<input maxLength={120} value={major} onChange={event => setMajor(event.target.value)} /></label></div>}
        <label className={styles.field}>标签（用逗号分隔）<input maxLength={500} value={tags} onChange={event => setTags(event.target.value)} /></label>
        <label className={styles.field}>价格（元）<input type="number" required min="0" max="10000" step="0.01" value={price} onChange={event => { setPrice(event.target.value); setConfirmed(false); }} /></label>
        <label className={styles.field}>定价确认记录<textarea required maxLength={1000} value={confirmationNote} onChange={event => { setConfirmationNote(event.target.value); setConfirmed(false); }} /></label>
        <label><input type="checkbox" required checked={confirmed} onChange={event => setConfirmed(event.target.checked)} /> 已确认所选资料的发布授权和最终价格 ¥{price || '0'}</label>
      </fieldset>
      <button className="button primary" disabled={busy || (!pendingPublication && (!selected.length || !confirmed))} type="submit">{pendingPublication ? '重试同一发布请求' : selected.length > 1 ? '合并为 ZIP 并发布' : '发布所选条目'}</button>
    </form>
    {pendingPublication && <div className={styles.row}><p className={styles.muted}>发布结果尚未确认，可重试同一请求，或刷新状态后调整。</p><button type="button" className="button ghost" disabled={busy} onClick={() => void run(async () => { await reload(); setPendingPublication(null); }, '状态已刷新，可调整发布信息')}>刷新并调整</button></div>}
    {error && <p role="alert" className={styles.error}>{error}</p>}{message && <p role="status" className={styles.success}>{message}</p>}
  </section>;
}

export default function AdminBatchPage({ user }: { user: SessionUser }) {
  const [page, setPage] = useState<BatchPage>({ items: [], total: 0 });
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [detail, setDetail] = useState<BatchDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError('');
    listAdminBatches(offset, 10, controller.signal).then(data => { if (!controller.signal.aborted) setPage(data); })
      .catch(err => { if (!controller.signal.aborted) setError(toErrorMessage(err, '加载失败')); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [offset, refresh]);
  async function open(id: BatchId) {
    setOpening(true); setError('');
    try { setDetail(await getAdminBatch(id)); } catch (err) { setError(toErrorMessage(err, '加载失败')); }
    finally { setOpening(false); }
  }
  return <><NavBar user={user} /><main className={`container ${styles.page}`}>
    <section className={styles.section}><Link href="/admin">管理后台</Link><div className={styles.row}><h1>批量投稿审核</h1>
      <button type="button" className={styles.icon} title="刷新列表" aria-label="刷新列表" disabled={loading} onClick={() => setRefresh(value => value + 1)}><RefreshCw size={18} /></button></div>
      {error && <p role="alert" className={styles.error}>{error}</p>}
      {loading ? <p role="status">加载中...</p> : <><ul className={styles.list}>{page.items.map(batch => <li key={batch.id} className={styles.item}><span className={styles.name}>#{batch.id} · {batchStatusLabel(batch.status)} · {batch.itemCount} 项<br /><span className={styles.muted}>投稿者 #{batch.uploaderId} · {batch.createdAt && new Date(batch.createdAt).toLocaleString()} · {((batch.totalBytes || 0) / 1048576).toFixed(2)} MB</span></span><button className="button ghost" disabled={opening || !!detail} onClick={() => void open(batch.id)}>查看批次</button></li>)}</ul>
        {!error && !page.items.length && <p>暂无批量投稿</p>}
        <div className={styles.row}><button className="button ghost" disabled={offset === 0} onClick={() => setOffset(value => value - 10)}>上一页</button><span>第 {offset / 10 + 1} 页 · 共 {page.total} 批</span><button className="button ghost" disabled={offset + 10 >= page.total} onClick={() => setOffset(value => value + 10)}>下一页</button></div></>}
    </section>
    {opening && <p role="status">加载详情...</p>}
    {detail && <><BatchReview key={detail.id} batch={detail} reload={async () => { setDetail(await getAdminBatch(detail.id)); setRefresh(value => value + 1); }} />
      <button className="button ghost" type="button" onClick={() => setDetail(null)}>返回批次列表</button></>}
  </main></>;
}
export const getServerSideProps: GetServerSideProps = async ({ req }) => {
  const session = readSession(req);
  const access = resolveAdminPageAccess(session);
  if (access === 'login') return { redirect: { destination: '/login?next=/admin/batch', permanent: false } };
  if (access === 'forbidden' || !session.user) return { notFound: true };
  return { props: { user: session.user } };
};
