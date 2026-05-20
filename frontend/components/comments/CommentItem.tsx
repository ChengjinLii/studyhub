import { useEffect, useState } from 'react';
import { Comment, CommentListResponse } from '../../types/material';
import { SessionUser } from '../../types/user';
import {
  fetchCommentReplies,
  createComment,
  likeComment,
  unlikeComment,
  deleteComment,
  updateComment,
  reportComment,
} from '../../lib/api';
import { toErrorMessage } from '../../lib/errors';
import { formatDateTime } from '../../lib/format';
import AppImage from '../AppImage';
import CommentInput from './CommentInput';
import StarRating from '../StarRating';

interface CommentItemProps {
  comment: Comment;
  currentUser: SessionUser | null;
  requireLogin: () => boolean;
  onReplyAdded: (parentId: number, reply: Comment) => void;
  onDeleted: (commentId: number) => void;
  onUpdated: (comment: Comment) => void;
}

export default function CommentItem({
  comment,
  currentUser,
  requireLogin,
  onReplyAdded,
  onDeleted,
  onUpdated,
}: CommentItemProps) {
  const [local, setLocal] = useState(comment);
  const [replies, setReplies] = useState<Comment[]>(comment.replies ?? []);
  const [repliesMeta, setRepliesMeta] = useState<CommentListResponse['meta'] | null>(null);
  const [repliesLoading, setRepliesLoading] = useState(false);
  const [replying, setReplying] = useState(false);
  const [editing, setEditing] = useState(false);
  const [actionError, setActionError] = useState('');
  const [avatarBroken, setAvatarBroken] = useState(false);

  useEffect(() => {
    setLocal(comment);
    setAvatarBroken(false);
  }, [comment]);

  const canManage = currentUser && (currentUser.id === local.user.id || (currentUser.roleMask & 8) === 8);

  const handleToggleReplies = async () => {
    if (replies.length > 0) {
      setReplies([]);
      setRepliesMeta(null);
      return;
    }
    setRepliesLoading(true);
    setActionError('');
    try {
      const resp = await fetchCommentReplies(local.id, 0, 20);
      setReplies(resp.items);
      setRepliesMeta(resp.meta);
    } catch (err: unknown) {
      setActionError(toErrorMessage(err, '加载回复失败'));
    } finally {
      setRepliesLoading(false);
    }
  };

  const handleLikeToggle = async () => {
    if (!requireLogin()) return;
    setActionError('');
    try {
      const result = local.hasLiked ? await unlikeComment(local.id) : await likeComment(local.id);
      const updated = { ...local, hasLiked: !local.hasLiked, likeCount: result.likeCount };
      setLocal(updated);
      onUpdated(updated);
    } catch (err: unknown) {
      setActionError(toErrorMessage(err, '操作失败'));
    }
  };

  const handleDelete = async () => {
    if (!requireLogin()) return;
    if (!confirm('确定删除该评论？')) return;
    setActionError('');
    try {
      await deleteComment(local.id);
      onDeleted(local.id);
    } catch (err: unknown) {
      setActionError(toErrorMessage(err, '删除失败'));
    }
  };

  const handleEdit = async (content: string) => {
    if (!requireLogin()) return;
    setActionError('');
    try {
      const updated = await updateComment(local.id, content);
      setLocal(updated);
      onUpdated(updated);
      setEditing(false);
    } catch (err: unknown) {
      setActionError(toErrorMessage(err, '更新失败'));
    }
  };

  const handleReply = async (content: string) => {
    if (!requireLogin()) return;
    setActionError('');
    try {
      const reply = await createComment({
        materialId: local.materialId,
        parentId: local.id,
        content,
      });
      setReplies((prev) => [reply, ...prev]);
      const updated = { ...local, replyCount: local.replyCount + 1 };
      setLocal(updated);
      onReplyAdded(local.id, reply);
      setReplying(false);
    } catch (err: unknown) {
      setActionError(toErrorMessage(err, '回复失败'));
    }
  };

  const handleReport = async () => {
    if (!requireLogin()) return;
    const reason = prompt('请输入举报理由（示例：广告、辱骂等）')?.trim();
    if (!reason) return;
    setActionError('');
    try {
      await reportComment(local.id, reason, '');
      alert('感谢反馈，我们会尽快处理。');
    } catch (err: unknown) {
      setActionError(toErrorMessage(err, '举报失败'));
    }
  };

  return (
    <article className="comment-item" id={`comment-${local.id}`}>
      <aside className="avatar">
        <div className="avatar-circle">
          {local.user.avatar && !avatarBroken ? (
            <AppImage
              src={local.user.avatar}
              alt={local.user.nickname}
              width={40}
              height={40}
              loading="lazy"
              onError={() => setAvatarBroken(true)}
            />
          ) : (
            local.user.nickname[0]
          )}
        </div>
      </aside>
      <section className="content">
        <header className="meta">
          <div className="info">
            <span className="nickname">{local.user.nickname}</span>
            {local.user.isAuthor && <span className="badge">作者</span>}
            <span className="time">{formatDateTime(local.createdAt)}</span>
            {local.edited && <span className="muted">（已编辑）</span>}
            {typeof local.rating === 'number' && local.rating > 0 && (
              <span className="user-rating">
                <StarRating value={local.rating} readOnly size={18} />
                <span className="rating-text">{local.rating} 分</span>
              </span>
            )}
          </div>
          <div className="actions">
            {!local.deleted && <button onClick={handleReport}>举报</button>}
            {canManage && !local.deleted && (
              <>
                <button onClick={() => setEditing((prev) => !prev)}>编辑</button>
                <button onClick={handleDelete}>删除</button>
              </>
            )}
          </div>
        </header>
        {local.deleted ? (
          <p className="deleted">该评论已被删除</p>
        ) : editing ? (
          <CommentInput initialValue={local.content} onSubmit={handleEdit} onCancel={() => setEditing(false)} minRows={2} />
        ) : (
          <p className="text">{local.content}</p>
        )}
        <footer className="toolbar">
          <button onClick={handleLikeToggle} disabled={local.deleted}>
            {local.hasLiked ? '取消点赞' : '点赞'}（{local.likeCount}）
          </button>
          <button onClick={() => setReplying((prev) => !prev)} disabled={local.deleted}>
            回复
          </button>
          {local.replyCount > 0 && (
            <button onClick={handleToggleReplies} disabled={repliesLoading}>
              {replies.length ? '收起回复' : `查看回复（${local.replyCount}）`}
            </button>
          )}
        </footer>
        {actionError && <p className="error">{actionError}</p>}
        {replying && !local.deleted && (
          <div className="reply-box">
            <CommentInput onSubmit={handleReply} onCancel={() => setReplying(false)} minRows={2} />
          </div>
        )}
        {replies.length > 0 && (
          <div className="reply-list">
            {replies.map((reply) => (
              <CommentItem
                key={reply.id}
                comment={reply}
                currentUser={currentUser}
                requireLogin={requireLogin}
                onReplyAdded={() => undefined}
                onDeleted={(id) => setReplies((prev) => prev.filter((item) => item.id !== id))}
                onUpdated={(updated) =>
                  setReplies((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
                }
              />
            ))}
          </div>
        )}
      </section>
      <style jsx>{`
        .comment-item {
          display: flex;
          gap: 12px;
          padding: 16px 0;
          border-bottom: 1px solid var(--border-color);
        }
        .avatar-circle {
          width: 40px;
          height: 40px;
          border-radius: 50%;
          background: var(--bg-soft);
          display: flex;
          align-items: center;
          justify-content: center;
          font-weight: bold;
          overflow: hidden;
        }
        .content {
          flex: 1;
        }
        .meta {
          display: flex;
          justify-content: space-between;
          font-size: 14px;
          color: var(--text-muted);
        }
        .nickname {
          font-weight: 600;
          margin-right: 8px;
        }
        .user-rating {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          margin-left: 12px;
          font-size: 13px;
          color: var(--text-muted);
        }
        .user-rating :global(.star-rating) {
          gap: 2px;
        }
        .badge {
          background: rgba(37, 99, 235, 0.1);
          color: var(--brand-primary);
          margin-right: 8px;
          padding: 2px 6px;
          border-radius: 4px;
          font-size: 12px;
        }
        .actions button,
        .toolbar button {
          background: none;
          border: none;
          color: var(--text-muted);
          cursor: pointer;
          margin-right: 12px;
        }
        .actions button:hover,
        .toolbar button:hover {
          color: var(--text-color);
        }
        .text {
          margin: 8px 0;
          white-space: pre-wrap;
        }
        .deleted {
          color: #999;
          font-style: italic;
        }
        .reply-list {
          margin-top: 12px;
          padding-left: 32px;
          border-left: 2px solid var(--border-color);
        }
        .error {
          color: var(--danger);
          font-size: 12px;
        }
      `}</style>
    </article>
  );
}
