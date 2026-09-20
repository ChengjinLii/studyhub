import Link from 'next/link';
import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { amendBatch, listOwnBatches } from '../../lib/batchApi';
import { batchStatusLabel, safeBatchUrl } from '../../lib/batchSubmission';
import { toErrorMessage } from '../../lib/errors';
import { BatchPage } from '../../types/batch';
import styles from '../../styles/Batch.module.css';

export default function OwnBatchStatus({ refreshKey = 0 }: { refreshKey?: number }) {
  const [page, setPage] = useState<BatchPage>({ items: [], total: 0 });
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reply, setReply] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    listOwnBatches(offset, 10, controller.signal).then(data => {
      if (!controller.signal.aborted) setPage(data);
    }).catch(err => {
      if (!controller.signal.aborted) setError(toErrorMessage(err, '加载批次失败'));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [offset, refresh, refreshKey]);
  return <section id="batch-submissions" className={styles.section} aria-busy={loading}>
    <div className={styles.row}><h2>我的批量投稿</h2><Link href="/upload/batch">批量投稿</Link>
      <button type="button" className={styles.icon} title="刷新批量投稿" aria-label="刷新批量投稿" disabled={loading} onClick={() => setRefresh(value => value + 1)}><RefreshCw size={18} /></button></div>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {loading ? <p role="status">加载中...</p> : !error && <>
      {!page.items.length && <p className={styles.muted}>暂无批量投稿</p>}
      <ul className={styles.list}>{page.items.map(batch => <li key={batch.id} className={styles.item}>
        <div className={styles.name}><strong>批次 #{batch.id}</strong><p>{batchStatusLabel(batch.status)} · {batch.itemCount} 项</p>
          {batch.statusCounts && <p className={styles.muted}>{Object.entries(batch.statusCounts).map(([status, count]) => `${status}: ${count}`).join(' · ')}</p>}
          {batch.items?.map(item => <p key={item.id} className={styles.muted}>条目 #{item.id} · {batchStatusLabel(item.status)} · {batchStatusLabel(item.scanStatus)}{item.reason && ` · ${item.reason}`}</p>)}
          {batch.items?.some(item => item.status === 'RETURNED') && <form className={styles.form} onSubmit={async event => {
            event.preventDefault(); if (sending) return; setSending(true); setError('');
            try { await amendBatch(batch.id, reply[String(batch.id)] || ''); setRefresh(value => value + 1); }
            catch (err) { setError(toErrorMessage(err, '补充失败')); } finally { setSending(false); }
          }}><label className={styles.field}>补充说明<textarea required maxLength={2000} value={reply[String(batch.id)] || ''} onChange={event => setReply(previous => ({ ...previous, [String(batch.id)]: event.target.value }))} /></label>
            <button className="button secondary" disabled={sending}>提交补充</button></form>}
          {batch.publications?.map(publication => safeBatchUrl(publication.url) && <p key={publication.id}><a href={publication.url} rel="noopener noreferrer">{publication.title || '查看已发布资料'}</a></p>)}
        </div>
      </li>)}</ul>
      <div className={styles.row}><button className="button ghost" disabled={offset === 0} onClick={() => setOffset(value => Math.max(0, value - 10))}>上一页</button>
        <span>第 {offset / 10 + 1} 页 · 共 {page.total} 批</span><button className="button ghost" disabled={offset + 10 >= page.total} onClick={() => setOffset(value => value + 10)}>下一页</button></div>
    </>}
  </section>;
}
