import { useState } from 'react';

interface CommentInputProps {
  onSubmit: (content: string) => Promise<void> | void;
  onCancel?: () => void;
  placeholder?: string;
  autoFocus?: boolean;
  minRows?: number;
  loading?: boolean;
  initialValue?: string;
}

export default function CommentInput({
  onSubmit,
  onCancel,
  placeholder,
  autoFocus,
  minRows = 3,
  loading,
  initialValue = '',
}: CommentInputProps) {
  const [value, setValue] = useState(initialValue);
  const [error, setError] = useState('');

  const handleSubmit = async () => {
    if (!value.trim()) {
      setError('请输入评论内容');
      return;
    }
    setError('');
    await onSubmit(value.trim());
    setValue('');
  };

  return (
    <div className="comment-input">
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder ?? '写下你的看法...'}
        rows={minRows}
        disabled={loading}
        autoFocus={autoFocus}
      />
      {error && <p className="form-error">{error}</p>}
      <div className="comment-input__actions">
        {onCancel && (
          <button type="button" className="button ghost" onClick={onCancel} disabled={loading}>
            取消
          </button>
        )}
        <button type="button" className="button primary" onClick={handleSubmit} disabled={loading}>
          {loading ? '发送中...' : '发布'}
        </button>
      </div>
      <style jsx>{`
        .comment-input textarea {
          width: 100%;
          border: 1px solid #ddd;
          border-radius: 6px;
          padding: 12px;
          resize: vertical;
        }
        .comment-input__actions {
          margin-top: 8px;
          display: flex;
          justify-content: flex-end;
          gap: 8px;
        }
        .form-error {
          color: #d93025;
          font-size: 12px;
          margin-top: 4px;
        }
      `}</style>
    </div>
  );
}
