import { GetServerSideProps } from 'next';
import Link from 'next/link';
import { useState } from 'react';
import AgenticPlatformLayout from '../../../components/admin/AgenticPlatformLayout';
import {
  AgentArtifactList,
  fetchAdminAgentArtifacts,
  fetchAdminAgentArtifactsForSsr,
} from '../../../lib/agenticApi';
import { resolveAgenticAdminAccess } from '../../../lib/agenticAdminAccess';
import { getRequestOrigin } from '../../../lib/apiBase';
import { toErrorMessage } from '../../../lib/errors';
import { SessionUser } from '../../../types/user';

interface AgentArtifactsPageProps {
  user: SessionUser;
  initialArtifacts: AgentArtifactList;
  apiAvailable: boolean;
}

const formatTime = (value: string | null) => {
  if (!value) return '--';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false });
};

const previewText = (value: unknown) => {
  if (value === null || value === undefined) return '无内联预览';
  try {
    const rendered = JSON.stringify(value, null, 2);
    return rendered.length > 1200 ? `${rendered.slice(0, 1200)}…` : rendered;
  } catch {
    return String(value);
  }
};

export default function AgentArtifactsPage({ user, initialArtifacts, apiAvailable }: AgentArtifactsPageProps) {
  const [artifacts, setArtifacts] = useState(initialArtifacts);
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(
    apiAvailable ? null : { type: 'error', text: 'Agentic Platform 当前未启用或不可访问。' }
  );

  const reload = async () => {
    setRefreshing(true);
    try {
      setArtifacts(await fetchAdminAgentArtifacts());
      setNotice(null);
    } catch (error: unknown) {
      setNotice({ type: 'error', text: toErrorMessage(error, '加载 Artifact 失败') });
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <AgenticPlatformLayout user={user} active="artifacts">
      <section className="card agentic-panel">
        <div className="agentic-panel__heading">
          <div>
            <span className="agentic-kicker">VERSIONED ARTIFACTS</span>
            <h2>管理员预览产物</h2>
          </div>
          <button className="button ghost small" type="button" onClick={() => void reload()} disabled={refreshing}>
            {refreshing ? '刷新中…' : '刷新'}
          </button>
        </div>
        <p className="agentic-muted">仅展示可审核的结构化 Artifact 元数据与安全预览；原始模型输出、私有推理和运行事件不会出现在此列表。</p>
        {notice && <p className={`agentic-notice ${notice.type}`}>{notice.text}</p>}
        {artifacts.items.length === 0 ? (
          <p className="agentic-empty">尚无 Agent Artifact。DeepResearch、学习计划与练习产物会在被父运行接受后出现在这里。</p>
        ) : (
          <div className="agentic-artifact-grid">
            {artifacts.items.map((artifact) => (
              <article className="agentic-artifact-card" key={artifact.id}>
                <div className="agentic-artifact-card__top">
                  <span className="agentic-status agentic-status--queued">{artifact.artifactType}</span>
                  <span>v{artifact.version}</span>
                </div>
                <h3>{artifact.artifactKey}</h3>
                <p className="agentic-muted">{artifact.id} · {formatTime(artifact.createdAt)}</p>
                <pre>{previewText(artifact.preview)}</pre>
                {artifact.runId && (
                  <Link className="button ghost small" href={`/admin/agentic-platform/runs/${encodeURIComponent(artifact.runId)}`}>
                    查看运行
                  </Link>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
    </AgenticPlatformLayout>
  );
}

export const getServerSideProps: GetServerSideProps<AgentArtifactsPageProps> = async (ctx) => {
  const access = resolveAgenticAdminAccess(ctx, '/admin/agentic-platform/artifacts');
  if (access.redirect || !access.session.user) return { redirect: access.redirect! };
  let initialArtifacts: AgentArtifactList = { items: [], meta: { limit: 50, total: 0 } };
  let apiAvailable = true;
  if (access.session.token) {
    try {
      initialArtifacts = await fetchAdminAgentArtifactsForSsr(access.session.token, getRequestOrigin(ctx.req));
    } catch {
      apiAvailable = false;
    }
  }
  return { props: { user: access.session.user, initialArtifacts, apiAvailable } };
};
