import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import AgenticPlatformLayout from '../../../../components/admin/AgenticPlatformLayout';
import {
  AgentEvent,
  AgentRun,
  AgentWait,
  agentRunEventsUrl,
  cancelAdminAgentRun,
  fetchAdminAgentRun,
  fetchAdminAgentRunForSsr,
  resumeAdminAgentRun,
} from '../../../../lib/agenticApi';
import { resolveAgenticAdminAccess } from '../../../../lib/agenticAdminAccess';
import { getRequestOrigin } from '../../../../lib/apiBase';
import { toErrorMessage } from '../../../../lib/errors';
import { SessionUser } from '../../../../types/user';

interface AgentRunPageProps {
  user: SessionUser;
  runId: string;
  initialRun: AgentRun | null;
  apiAvailable: boolean;
}

const eventNames = [
  'run.queued',
  'run.started',
  'plan.created',
  'plan.revised',
  'step.started',
  'step.completed',
  'skill.started',
  'skill.completed',
  'subagent.started',
  'subagent.completed',
  'context.compressed',
  'artifact.created',
  'user_input.required',
  'approval.required',
  'run.waiting',
  'run.resumed',
  'run.cancel_requested',
  'run.completed',
  'run.failed',
];

const formatTime = (value: string | null | undefined) => {
  if (!value) return '--';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false });
};

const formatJson = (value: unknown) => {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

const statusLabel: Record<string, string> = {
  created: '已创建',
  queued: '等待 Worker',
  running: '运行中',
  waiting: '等待输入',
  cancelling: '取消中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

export default function AgentRunPage({ user, runId, initialRun, apiAvailable }: AgentRunPageProps) {
  const router = useRouter();
  const [run, setRun] = useState<AgentRun | null>(initialRun);
  const [streamState, setStreamState] = useState<'connecting' | 'live' | 'reconnecting' | 'offline'>('offline');
  const [refreshing, setRefreshing] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [resumingWaitId, setResumingWaitId] = useState<string | null>(null);
  const [resumeText, setResumeText] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(
    apiAvailable ? null : { type: 'error', text: 'Agentic Platform 当前未启用或不可访问。' }
  );

  const reload = useCallback(
    async (quiet = false) => {
      if (!quiet) setRefreshing(true);
      try {
        const next = await fetchAdminAgentRun(runId);
        setRun(next);
        if (!quiet) setNotice(null);
      } catch (error: unknown) {
        if (!quiet) setNotice({ type: 'error', text: toErrorMessage(error, '刷新运行详情失败') });
      } finally {
        if (!quiet) setRefreshing(false);
      }
    },
    [runId]
  );

  useEffect(() => {
    if (!apiAvailable || typeof window === 'undefined') return undefined;
    let disposed = false;
    let source: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (disposed) return;
      setStreamState(source ? 'reconnecting' : 'connecting');
      source = new EventSource(agentRunEventsUrl(runId), { withCredentials: true });
      source.onopen = () => {
        if (!disposed) setStreamState('live');
      };
      const handleEvent = (event: MessageEvent) => {
        try {
          const parsed = JSON.parse(event.data) as AgentRun | AgentEvent;
          if (event.type === 'run.snapshot') {
            setRun(parsed as AgentRun);
          } else {
            setRun((current) => {
              if (!current) return current;
              const incoming = parsed as AgentEvent;
              const prior = current.events || [];
              const events = prior.some((item) => item.id === incoming.id) ? prior : [...prior, incoming];
              return { ...current, events, latestEventSequence: Math.max(current.latestEventSequence || 0, incoming.sequence || 0) };
            });
          }
          void reload(true);
        } catch {
          // The next durable snapshot will repair an incomplete browser event.
        }
      };
      source.addEventListener('run.snapshot', handleEvent);
      eventNames.forEach((name) => source?.addEventListener(name, handleEvent));
      source.onerror = () => {
        source?.close();
        source = null;
        if (!disposed) {
          setStreamState('reconnecting');
          reconnectTimer = setTimeout(connect, 2000);
        }
      };
    };

    connect();
    return () => {
      disposed = true;
      source?.close();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, [apiAvailable, reload, runId]);

  const pendingWaits = useMemo(
    () => (run?.waits || []).filter((wait) => wait.status === 'pending'),
    [run?.waits]
  );

  const resumeWait = async (wait: AgentWait) => {
    if (!wait.resumeToken) {
      setNotice({ type: 'error', text: '该等待项没有可用的恢复令牌，请刷新运行状态。' });
      return;
    }
    setResumingWaitId(wait.id);
    try {
      const next = await resumeAdminAgentRun(runId, {
        waitId: wait.id,
        resumeToken: wait.resumeToken,
        payload: { response: (resumeText[wait.id] || '').trim() || '[管理员确认继续]' },
      });
      setRun(next);
      setNotice({ type: 'success', text: '恢复输入已安全记录，并已重新排队。' });
    } catch (error: unknown) {
      setNotice({ type: 'error', text: toErrorMessage(error, '恢复 Agent 运行失败') });
    } finally {
      setResumingWaitId(null);
    }
  };

  const cancelRun = async () => {
    if (!run || !run.canCancel || cancelling) return;
    if (typeof window !== 'undefined' && !window.confirm('请求取消该 Agent 运行？正在执行的 Worker 将在安全边界停止。')) return;
    setCancelling(true);
    try {
      const next = await cancelAdminAgentRun(run.id, 'cancelled_by_admin_console');
      setRun(next);
      setNotice({ type: 'success', text: '已发出取消请求。' });
    } catch (error: unknown) {
      setNotice({ type: 'error', text: toErrorMessage(error, '取消 Agent 运行失败') });
    } finally {
      setCancelling(false);
    }
  };

  if (!run) {
    return (
      <AgenticPlatformLayout user={user} active="runs">
        <section className="card agentic-panel agentic-not-found">
          <h2>未能加载运行记录</h2>
          <p>{notice?.text || '该运行不存在、平台未启用，或当前会话没有访问权限。'}</p>
          <Link className="button ghost" href="/admin/agentic-platform">
            返回运行控制台
          </Link>
        </section>
      </AgenticPlatformLayout>
    );
  }

  const observability = run.observability;
  const latencyEntries = Object.entries(observability?.latencyMs || {});

  return (
    <AgenticPlatformLayout user={user} active="runs">
      <section className="card agentic-panel agentic-run-header">
        <div>
          <div className="agentic-run-header__meta">
            <span className={`agentic-status agentic-status--${run.status}`}>{statusLabel[run.status] || run.status}</span>
            <span className="agentic-stream-state" data-state={streamState}>
              SSE {streamState === 'live' ? '已连接' : streamState === 'reconnecting' ? '重连中' : streamState}
            </span>
          </div>
          <h2>{run.runKind === 'deep_research' ? 'DeepResearch 运行' : 'Agent 运行'}</h2>
          <p className="agentic-run-header__goal">{run.goal || '未记录目标'}</p>
          <p className="agentic-muted">
            {run.id} · Thread {run.threadId} · 创建于 {formatTime(run.createdAt)}
          </p>
        </div>
        <div className="agentic-run-header__actions">
          <button className="button ghost small" type="button" onClick={() => void reload()} disabled={refreshing}>
            {refreshing ? '刷新中…' : '刷新状态'}
          </button>
          {run.canCancel && (
            <button className="button ghost danger small" type="button" onClick={() => void cancelRun()} disabled={cancelling}>
              {cancelling ? '请求中…' : '取消运行'}
            </button>
          )}
        </div>
      </section>

      {notice && <p className={`agentic-notice ${notice.type}`}>{notice.text}</p>}

      <section className="agentic-metric-grid" aria-label="运行概览">
        <article className="card agentic-metric"><span>步骤</span><strong>{observability?.steps ?? 0}</strong></article>
        <article className="card agentic-metric"><span>事件</span><strong>{run.latestEventSequence}</strong></article>
        <article className="card agentic-metric"><span>Artifact</span><strong>{run.artifacts?.length || 0}</strong></article>
        <article className="card agentic-metric"><span>Token</span><strong>{observability?.usage.totalTokens ?? 0}</strong></article>
      </section>

      <section className="agentic-detail-grid">
        <article className="card agentic-panel">
          <span className="agentic-kicker">PLAN & STEP</span>
          <h3>计划与步骤</h3>
          {(observability?.plan || []).length === 0 && (run.steps || []).length === 0 ? (
            <p className="agentic-empty">任务已持久化，等待 Worker 产出首个策略决定。</p>
          ) : (
            <ol className="agentic-step-list">
              {(run.steps || []).map((step) => (
                <li key={step.id}>
                  <div><strong>#{step.index + 1} · {step.node}</strong><span>{step.status}</span></div>
                  <p>{step.actionType || '等待策略动作'}{step.skillName ? ` · ${step.skillName}` : ''}</p>
                  {step.errorCode && <small>错误：{step.errorCode}</small>}
                </li>
              ))}
            </ol>
          )}
        </article>

        <article className="card agentic-panel">
          <span className="agentic-kicker">SEARCH & TOOL</span>
          <h3>检索查询与工具</h3>
          <div className="agentic-subsection">
            <h4>Search Query</h4>
            {(observability?.searchQueries || []).length ? (
              <ul className="agentic-plain-list">
                {observability?.searchQueries.map((item) => <li key={`${item.sequence}-${item.query}`}>#{item.sequence} · {item.query}</li>)}
              </ul>
            ) : <p className="agentic-empty">暂无可展示的检索查询。</p>}
          </div>
          <div className="agentic-subsection">
            <h4>Tool</h4>
            {(observability?.tools || []).length ? (
              <ul className="agentic-plain-list">
                {observability?.tools.map((item) => <li key={item.stepId}>{item.skillName} · {item.status}</li>)}
              </ul>
            ) : <p className="agentic-empty">暂无工具调用。</p>}
          </div>
        </article>

        <article className="card agentic-panel">
          <span className="agentic-kicker">EVIDENCE & CONTEXT</span>
          <h3>证据图谱与上下文</h3>
          <p className="agentic-muted">
            Evidence Ledger Artifact：{observability?.evidenceGraph.artifactCount || 0} 个；节点 {observability?.evidenceGraph.nodes.length || 0}，边 {observability?.evidenceGraph.edges.length || 0}。
          </p>
          <div className="agentic-subsection">
            <h4>Context Compression</h4>
            {(observability?.contextCompression || []).length ? (
              <ul className="agentic-plain-list">
                {observability?.contextCompression.map((item) => <li key={item.sequence}>#{item.sequence} · {formatJson(item.payload)}</li>)}
              </ul>
            ) : <p className="agentic-empty">暂无上下文压缩事件。</p>}
          </div>
        </article>

        <article className="card agentic-panel">
          <span className="agentic-kicker">VERIFY & COST</span>
          <h3>验证与资源</h3>
          <p>Verifier：{(observability?.verifier || []).length ? `${observability?.verifier.length} 个结构化结果` : '暂无结果'}</p>
          <dl className="agentic-definition-list">
            <div><dt>输入 Token</dt><dd>{observability?.usage.inputTokens ?? 0}</dd></div>
            <div><dt>输出 Token</dt><dd>{observability?.usage.outputTokens ?? 0}</dd></div>
            <div><dt>成本</dt><dd>{observability?.usage.cost ?? 0}</dd></div>
            <div><dt>Latency</dt><dd>{latencyEntries.length ? latencyEntries.map(([key, value]) => `${key}: ${value}ms`).join(' · ') : '--'}</dd></div>
          </dl>
        </article>
      </section>

      <section className="card agentic-panel">
        <div className="agentic-panel__heading">
          <div><span className="agentic-kicker">WAIT / RESUME</span><h3>等待管理员输入</h3></div>
          <span className="agentic-note">恢复令牌仅在 Wait 仍为 pending 时可用一次。</span>
        </div>
        {pendingWaits.length === 0 ? <p className="agentic-empty">当前没有等待输入的步骤。</p> : (
          <div className="agentic-wait-list">
            {pendingWaits.map((wait) => (
              <article key={wait.id} className="agentic-wait-card">
                <div>
                  <strong>{wait.type}</strong>
                  <pre>{formatJson(wait.request)}</pre>
                </div>
                <textarea
                  value={resumeText[wait.id] || ''}
                  onChange={(event) => setResumeText((current) => ({ ...current, [wait.id]: event.target.value }))}
                  rows={3}
                  placeholder="输入管理员确认或补充信息"
                />
                <button className="button primary small" type="button" onClick={() => void resumeWait(wait)} disabled={resumingWaitId === wait.id}>
                  {resumingWaitId === wait.id ? '恢复中…' : 'Resume'}
                </button>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="card agentic-panel">
        <div className="agentic-panel__heading">
          <div><span className="agentic-kicker">ARTIFACTS & EVENTS</span><h3>产物与事件</h3></div>
          <Link className="button ghost small" href={`/admin/agentic-platform/artifacts?runId=${encodeURIComponent(run.id)}`}>查看全部 Artifact</Link>
        </div>
        <div className="agentic-artifact-events">
          <div>
            <h4>Artifact</h4>
            {(run.artifacts || []).length ? (
              <ul className="agentic-plain-list">
                {run.artifacts?.map((artifact) => <li key={artifact.id}>{artifact.artifactType} · v{artifact.version} · {artifact.artifactKey}</li>)}
              </ul>
            ) : <p className="agentic-empty">暂无持久化 Artifact。</p>}
          </div>
          <div>
            <h4>Event stream</h4>
            {(run.events || []).length ? (
              <ul className="agentic-event-list">
                {run.events?.slice(-12).map((event) => <li key={event.id}><span>#{event.sequence}</span><strong>{event.name}</strong><small>{formatTime(event.occurredAt)}</small></li>)}
              </ul>
            ) : <p className="agentic-empty">暂无事件。</p>}
          </div>
        </div>
        <p className="agentic-privacy-note">此页不显示私有 CoT、原始模型推理或密钥类字段。</p>
      </section>
    </AgenticPlatformLayout>
  );
}

export const getServerSideProps: GetServerSideProps<AgentRunPageProps> = async (ctx) => {
  const rawId = ctx.params?.id;
  const runId = typeof rawId === 'string' ? rawId : '';
  const access = resolveAgenticAdminAccess(ctx, `/admin/agentic-platform/runs/${encodeURIComponent(runId)}`);
  if (access.redirect || !access.session.user) return { redirect: access.redirect! };

  let initialRun: AgentRun | null = null;
  let apiAvailable = true;
  if (runId && access.session.token) {
    try {
      initialRun = await fetchAdminAgentRunForSsr(runId, access.session.token, getRequestOrigin(ctx.req));
    } catch {
      apiAvailable = false;
    }
  }
  return { props: { user: access.session.user, runId, initialRun, apiAvailable } };
};
