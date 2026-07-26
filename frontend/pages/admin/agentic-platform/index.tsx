import { FormEvent, useState } from 'react';
import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useRouter } from 'next/router';
import AgenticPlatformLayout from '../../../components/admin/AgenticPlatformLayout';
import {
  AgentRun,
  AgentRunList,
  createAdminAgentRun,
  fetchAdminAgentRuns,
  fetchAdminAgentRunsForSsr,
} from '../../../lib/agenticApi';
import { resolveAgenticAdminAccess } from '../../../lib/agenticAdminAccess';
import { getRequestOrigin } from '../../../lib/apiBase';
import { toErrorMessage } from '../../../lib/errors';
import { SessionUser } from '../../../types/user';

interface AgenticPlatformPageProps {
  user: SessionUser;
  initialRuns: AgentRunList;
  apiAvailable: boolean;
}

const formatTime = (value: string | null) => {
  if (!value) return '--';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false });
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

export default function AgenticPlatformPage({ user, initialRuns, apiAvailable }: AgenticPlatformPageProps) {
  const router = useRouter();
  const [runs, setRuns] = useState(initialRuns);
  const [goal, setGoal] = useState('');
  const [creating, setCreating] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(
    apiAvailable ? null : { type: 'error', text: 'Agentic Platform 当前未启用；管理员接口保持关闭。' }
  );

  const reload = async () => {
    setRefreshing(true);
    try {
      setRuns(await fetchAdminAgentRuns());
      setNotice(null);
    } catch (error: unknown) {
      setNotice({ type: 'error', text: toErrorMessage(error, '加载运行记录失败') });
    } finally {
      setRefreshing(false);
    }
  };

  const submitRun = async (event: FormEvent) => {
    event.preventDefault();
    const normalizedGoal = goal.trim();
    if (!normalizedGoal) {
      setNotice({ type: 'error', text: '请先填写 Agent 的目标。' });
      return;
    }
    setCreating(true);
    try {
      const run = await createAdminAgentRun({
        goal: normalizedGoal,
        idempotencyKey: `console-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
      });
      setGoal('');
      await router.push(`/admin/agentic-platform/runs/${encodeURIComponent(run.id)}`);
    } catch (error: unknown) {
      setNotice({ type: 'error', text: toErrorMessage(error, '创建 Agent 运行失败') });
    } finally {
      setCreating(false);
    }
  };

  return (
    <AgenticPlatformLayout user={user} active="runs">
      <section className="agentic-platform__split">
        <article className="card agentic-panel">
          <div className="agentic-panel__heading">
            <div>
              <span className="agentic-kicker">NEW RUN</span>
              <h2>发起通用 Agent 任务</h2>
            </div>
            <Link className="button ghost small" href="/admin/agentic-platform/research">
              发起 DeepResearch
            </Link>
          </div>
          <p className="agentic-muted">
            请求会被持久化为 Shadow Mode 队列任务。后续 Worker 将把它交给可替换的 Agent Policy，不在控制台内硬编码检索或工具顺序。
          </p>
          <form className="agentic-form" onSubmit={submitRun}>
            <label htmlFor="agent-goal">任务目标</label>
            <textarea
              id="agent-goal"
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              placeholder="例如：比较内部资料的覆盖范围，并产出仅供管理员审核的学习建议。"
              maxLength={4000}
              rows={5}
            />
            <div className="agentic-form__actions">
              <button className="button primary" type="submit" disabled={creating}>
                {creating ? '正在创建…' : '创建排队任务'}
              </button>
              <span className="agentic-note">不会直接向学生发布内容。</span>
            </div>
          </form>
          {notice && <p className={`agentic-notice ${notice.type}`}>{notice.text}</p>}
        </article>

        <article className="card agentic-panel agentic-panel--status">
          <span className="agentic-kicker">CONTROL PLANE</span>
          <h2>运行态边界</h2>
          <ul className="agentic-checklist">
            <li>Run / Wait / Job / Artifact 持久化，刷新后可恢复查看。</li>
            <li>SSE 只传递结构化状态与安全事件，重连时读取最新快照。</li>
            <li>恢复令牌由一次性 Wait 状态约束；取消只请求安全终止路径。</li>
          </ul>
        </article>
      </section>

      <section className="card agentic-panel agentic-runs-panel">
        <div className="agentic-panel__heading">
          <div>
            <span className="agentic-kicker">DURABLE RUNS</span>
            <h2>最近运行</h2>
          </div>
          <button className="button ghost small" type="button" onClick={() => void reload()} disabled={refreshing}>
            {refreshing ? '刷新中…' : '刷新'}
          </button>
        </div>
        {runs.items.length === 0 ? (
          <p className="agentic-empty">还没有可见的 Agent 运行记录。</p>
        ) : (
          <div className="agentic-table-wrap">
            <table className="agentic-table">
              <thead>
                <tr>
                  <th>运行</th>
                  <th>类型</th>
                  <th>状态</th>
                  <th>目标</th>
                  <th>创建时间</th>
                </tr>
              </thead>
              <tbody>
                {runs.items.map((run: AgentRun) => (
                  <tr key={run.id}>
                    <td>
                      <Link className="agentic-run-link" href={`/admin/agentic-platform/runs/${encodeURIComponent(run.id)}`}>
                        {run.id.slice(0, 18)}…
                      </Link>
                    </td>
                    <td>{run.runKind === 'deep_research' ? 'DeepResearch' : '通用任务'}</td>
                    <td>
                      <span className={`agentic-status agentic-status--${run.status}`}>{statusLabel[run.status] || run.status}</span>
                    </td>
                    <td className="agentic-table__goal">{run.goal || '--'}</td>
                    <td>{formatTime(run.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </AgenticPlatformLayout>
  );
}

export const getServerSideProps: GetServerSideProps<AgenticPlatformPageProps> = async (ctx) => {
  const access = resolveAgenticAdminAccess(ctx, '/admin/agentic-platform');
  if (access.redirect || !access.session.user) return { redirect: access.redirect! };

  let initialRuns: AgentRunList = { items: [], meta: { limit: 30, total: 0 } };
  let apiAvailable = true;
  if (access.session.token) {
    try {
      initialRuns = await fetchAdminAgentRunsForSsr(access.session.token, getRequestOrigin(ctx.req));
    } catch {
      apiAvailable = false;
    }
  }
  return { props: { user: access.session.user, initialRuns, apiAvailable } };
};
