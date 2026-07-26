import { FormEvent, useState } from 'react';
import { GetServerSideProps } from 'next';
import { useRouter } from 'next/router';
import AgenticPlatformLayout from '../../../components/admin/AgenticPlatformLayout';
import { createAdminDeepResearch } from '../../../lib/agenticApi';
import { resolveAgenticAdminAccess } from '../../../lib/agenticAdminAccess';
import { toErrorMessage } from '../../../lib/errors';
import { SessionUser } from '../../../types/user';

interface DeepResearchPageProps {
  user: SessionUser;
}

export default function DeepResearchPage({ user }: DeepResearchPageProps) {
  const router = useRouter();
  const [question, setQuestion] = useState('');
  const [title, setTitle] = useState('');
  const [criteria, setCriteria] = useState('内部证据可追溯\n产物仅供管理员预览');
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const normalizedQuestion = question.trim();
    if (!normalizedQuestion) {
      setNotice({ type: 'error', text: '请填写研究问题。' });
      return;
    }
    setSubmitting(true);
    try {
      const successCriteria = criteria
        .split('\n')
        .map((item) => item.trim())
        .filter(Boolean);
      const run = await createAdminDeepResearch({
        question: normalizedQuestion,
        title: title.trim() || undefined,
        successCriteria,
        idempotencyKey: `research-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
      });
      await router.push(`/admin/agentic-platform/runs/${encodeURIComponent(run.id)}`);
    } catch (error: unknown) {
      setNotice({ type: 'error', text: toErrorMessage(error, '创建 DeepResearch 运行失败') });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AgenticPlatformLayout user={user} active="research">
      <section className="agentic-platform__split">
        <article className="card agentic-panel">
          <span className="agentic-kicker">DEEPRESEARCH</span>
          <h2>创建研究任务</h2>
          <p className="agentic-muted">
            默认仅允许已授权的 StudyHub 内部资料与 PDF 证据。外部 Web / Scholar 能力由服务端开关和环境适配器决定，不能由页面绕过。
          </p>
          <form className="agentic-form" onSubmit={submit}>
            <label htmlFor="research-title">管理员标题（可选）</label>
            <input id="research-title" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={512} />
            <label htmlFor="research-question">研究问题</label>
            <textarea
              id="research-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="例如：内部资料中，哪些证据最适合解释傅里叶变换的直觉和常见误区？"
              maxLength={4000}
              rows={6}
            />
            <label htmlFor="research-criteria">成功标准（每行一项）</label>
            <textarea id="research-criteria" value={criteria} onChange={(event) => setCriteria(event.target.value)} rows={3} maxLength={4000} />
            <div className="agentic-form__actions">
              <button className="button primary" type="submit" disabled={submitting}>
                {submitting ? '正在创建…' : '创建研究运行'}
              </button>
              <span className="agentic-note">提交后进入持久化队列，不同步伪造研究结果。</span>
            </div>
          </form>
          {notice && <p className={`agentic-notice ${notice.type}`}>{notice.text}</p>}
        </article>

        <article className="card agentic-panel agentic-panel--status">
          <span className="agentic-kicker">RESEARCH GUARANTEES</span>
          <h2>研究运行的可观察边界</h2>
          <ul className="agentic-checklist">
            <li>研究 Policy 自主选择检索、阅读、交叉验证、上下文管理与收尾动作。</li>
            <li>Evidence Ledger、Claim、Citation、冲突与未解决问题将作为结构化 Artifact 记录。</li>
            <li>管理员只在控制台预览产物；不会由此任务直接修改学生内容或发送通知。</li>
          </ul>
        </article>
      </section>
    </AgenticPlatformLayout>
  );
}

export const getServerSideProps: GetServerSideProps<DeepResearchPageProps> = async (ctx) => {
  const access = resolveAgenticAdminAccess(ctx, '/admin/agentic-platform/research');
  if (access.redirect || !access.session.user) return { redirect: access.redirect! };
  return { props: { user: access.session.user } };
};
