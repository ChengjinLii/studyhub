import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/router';
import { Comment, CommentListResponse } from '../../types/material';
import { SessionUser } from '../../types/user';
import { fetchComments, createComment } from '../../lib/api';
import CommentInput from './CommentInput';
import CommentItem from './CommentItem';

interface CommentSectionProps {
  materialId: number;
  user: SessionUser | null;
  initialCount?: number;
}

export default function CommentSection({ materialId, user, initialCount = 0 }: CommentSectionProps) {
  const router = useRouter();
  const [comments, setComments] = useState<Comment[]>([]);
  const [meta, setMeta] = useState<CommentListResponse['meta'] | null>(null);
  const [sort, setSort] = useState<'latest' | 'hottest'>('latest');
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitMessage, setSubmitMessage] = useState('');
  const [submitError, setSubmitError] = useState('');
  const totalCount = useMemo(() => meta?.total ?? initialCount, [meta, initialCount]);

  const loadComments = useCallback(
    async (opts?: { page?: number; sort?: string; silent?: boolean }) => {
      const targetPage = opts?.page ?? page;
      const targetSort = opts?.sort ?? sort;
      if (!opts?.silent) {
        setLoading(true);
        setError('');
      }
      try {
        const resp = await fetchComments({
          materialId,
          sort: targetSort,
          page: targetPage,
          size: 10,
        });
        setComments(resp.items);
        setMeta(resp.meta);
      } catch (err: any) {
        setError(err.message || '评论加载失败');
      } finally {
        if (!opts?.silent) {
          setLoading(false);
        }
      }
    },
    [materialId, page, sort]
  );

  useEffect(() => {
    let mounted = true;
    (async () => {
      if (!mounted) return;
      await loadComments();
    })();
    return () => {
      mounted = false;
    };
  }, [loadComments]);

  const requireLogin = () => {
    if (!user) {
      router.push({
        pathname: '/login',
        query: { next: router.asPath },
      });
      return false;
    }
    return true;
  };

  const handleCreate = async (content: string) => {
    if (!requireLogin()) return;
    setSubmitting(true);
    setSubmitError('');
    setSubmitMessage('');
    try {
      await createComment({ materialId, content });
      setSubmitMessage('评论发布成功！');
      await loadComments({ page: 0, silent: true });
      setPage(0);
    } catch (err: any) {
      setSubmitError(err.message || '评论失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleReplyAdded = (parentId: number) => {
    setComments((prev) =>
      prev.map((item) => (item.id === parentId ? { ...item, replyCount: item.replyCount + 1 } : item))
    );
  };

  const handleDeleted = (commentId: number) => {
    setComments((prev) => prev.filter((item) => item.id !== commentId));
    setMeta((prev) => (prev ? { ...prev, total: Math.max(0, prev.total - 1) } : prev));
  };

  const handleUpdated = (updated: Comment) => {
    setComments((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
  };

  return (
    <section className="card comment-section">
      <header className="comment-header">
        <div>
          <h3>评论区</h3>
          <p className="muted">共有 {totalCount} 条评论</p>
        </div>
        <div className="sort-tabs">
          {['latest', 'hottest'].map((key) => (
            <button
              key={key}
              className={sort === key ? 'active' : ''}
              onClick={() => {
                setSort(key as 'latest' | 'hottest');
                setPage(0);
                loadComments({ page: 0, sort: key, silent: true });
              }}
            >
              {key === 'latest' ? '最新' : '最热'}
            </button>
          ))}
        </div>
      </header>
      <div className="comment-input-wrapper">
        {user ? (
          <>
            <CommentInput onSubmit={handleCreate} loading={submitting} />
            {submitMessage && <p className="success">{submitMessage}</p>}
            {submitError && <p className="error">{submitError}</p>}
          </>
        ) : (
          <div className="login-prompt">
            请 <a className="login-link" href={`/login?next=${encodeURIComponent(router.asPath)}`}>登录</a> 后参与讨论
          </div>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {loading ? (
        <p>评论加载中...</p>
      ) : comments.length === 0 ? (
        <p className="muted">还没有评论，快来抢沙发吧！</p>
      ) : (
        <div>
          {comments.map((comment) => (
            <CommentItem
              key={comment.id}
              comment={comment}
              currentUser={user}
              requireLogin={requireLogin}
              onReplyAdded={handleReplyAdded}
              onDeleted={handleDeleted}
              onUpdated={handleUpdated}
            />
          ))}
        </div>
      )}
      {meta && meta.total > meta.size && (
        <div className="pagination">
          <button disabled={page <= 0} onClick={() => setPage((prev) => Math.max(0, prev - 1))}>
            上一页
          </button>
          <span>
            第 {page + 1} / {Math.ceil(meta.total / meta.size)} 页
          </span>
          <button
            disabled={(page + 1) * meta.size >= meta.total}
            onClick={() => setPage((prev) => prev + 1)}
          >
            下一页
          </button>
        </div>
      )}
      <style jsx>{`
        .comment-section {
          margin-top: 24px;
        }
        .comment-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
        }
        .muted {
          color: var(--text-muted);
          font-size: 13px;
        }
        .sort-tabs button {
          margin-left: 8px;
          border: none;
          background: none;
          cursor: pointer;
          color: var(--text-muted);
        }
        .sort-tabs button.active {
          color: var(--text-color);
          font-weight: 600;
        }
        .comment-input-wrapper {
          margin-bottom: 16px;
        }
        .login-prompt {
          background: var(--bg-soft);
          padding: 12px;
          border-radius: 6px;
        }
        .error {
          color: var(--danger);
          margin-top: 8px;
        }
        .success {
          color: var(--success);
          margin-top: 8px;
        }
        .pagination {
          padding-top: 12px;
          display: flex;
          justify-content: center;
          gap: 16px;
          align-items: center;
        }
        .pagination button {
          border: 1px solid var(--border-color);
          background: #fff;
          padding: 6px 12px;
          border-radius: 4px;
          cursor: pointer;
        }
        .pagination button:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
      `}</style>
    </section>
  );
}
