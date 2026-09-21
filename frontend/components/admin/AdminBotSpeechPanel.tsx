import { FormEvent, useCallback, useEffect, useState } from 'react';
import {
  BotSpeechMessage,
  BotSpeechMessageInput,
  BotSpeechStyle,
  createAdminBotSpeechMessage,
  fetchAdminBotSpeechMessages,
  revokeAdminBotSpeechMessage,
  updateAdminBotSpeechMessage,
} from '../../lib/botSpeechApi';
import { toErrorMessage } from '../../lib/errors';
import { formatDateTime } from '../../lib/format';
import { useAppDialog } from '../AppDialogProvider';

type Notice = { type: 'success' | 'error'; text: string } | null;

interface SpeechForm {
  message: string;
  displayStyle: BotSpeechStyle;
  displayDurationSeconds: string;
  priority: string;
  startsAt: string;
  endsAt: string;
}

const EMPTY_FORM: SpeechForm = {
  message: '',
  displayStyle: 'STANDARD',
  displayDurationSeconds: '8',
  priority: '50',
  startsAt: '',
  endsAt: '',
};

const STATUS_LABELS: Record<BotSpeechMessage['status'], string> = {
  DRAFT: '草稿',
  SCHEDULED: '待发布',
  PUBLISHED: '显示中',
  EXPIRED: '已结束',
  REVOKED: '已撤回',
};

const STYLE_LABELS: Record<BotSpeechStyle, string> = {
  STANDARD: '普通气泡',
  EMPHASIS: '强调气泡',
  TYPEWRITER: '打字机效果',
};

const toLocalInput = (value: string | null) => {
  if (!value) return '';
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
};

const toPayload = (form: SpeechForm, publish: boolean): BotSpeechMessageInput => ({
  message: form.message.trim(),
  displayStyle: form.displayStyle,
  displayDurationSeconds: Number(form.displayDurationSeconds),
  priority: Number(form.priority),
  startsAt: form.startsAt ? new Date(form.startsAt).toISOString() : null,
  endsAt: form.endsAt ? new Date(form.endsAt).toISOString() : null,
  publish,
});

export default function AdminBotSpeechPanel() {
  const dialog = useAppDialog();
  const [messages, setMessages] = useState<BotSpeechMessage[]>([]);
  const [form, setForm] = useState<SpeechForm>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [revokingId, setRevokingId] = useState<number | null>(null);
  const [notice, setNotice] = useState<Notice>(null);

  const reload = useCallback(async () => {
    const data = await fetchAdminBotSpeechMessages();
    setMessages(data.items);
  }, []);

  useEffect(() => {
    void reload()
      .catch((error: unknown) => setNotice({ type: 'error', text: toErrorMessage(error, '加载宠物台词队列失败') }))
      .finally(() => setLoading(false));
  }, [reload]);

  const resetForm = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
  };

  const submit = async (publish: boolean) => {
    const payload = toPayload(form, publish);
    if (!payload.message) {
      setNotice({ type: 'error', text: '气泡台词不能为空' });
      return;
    }
    if (payload.endsAt && payload.startsAt && new Date(payload.endsAt) <= new Date(payload.startsAt)) {
      setNotice({ type: 'error', text: '结束时间必须晚于开始时间' });
      return;
    }
    setSaving(true);
    setNotice(null);
    try {
      if (editingId === null) {
        await createAdminBotSpeechMessage(payload);
      } else {
        await updateAdminBotSpeechMessage(editingId, payload);
      }
      await reload();
      resetForm();
      window.dispatchEvent(new Event('bot-speech:refresh'));
      setNotice({ type: 'success', text: publish ? '台词已进入发布队列' : '草稿已保存' });
    } catch (error: unknown) {
      setNotice({ type: 'error', text: toErrorMessage(error, '保存宠物台词失败') });
    } finally {
      setSaving(false);
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void submit(false);
  };

  const editMessage = (item: BotSpeechMessage) => {
    setEditingId(item.id);
    setForm({
      message: item.message,
      displayStyle: item.displayStyle,
      displayDurationSeconds: String(item.displayDurationSeconds),
      priority: String(item.priority),
      startsAt: toLocalInput(item.startsAt),
      endsAt: toLocalInput(item.endsAt),
    });
    setNotice(null);
    document.getElementById('bot-speech-message')?.focus();
  };

  const revokeMessage = async (item: BotSpeechMessage) => {
    const confirmed = await dialog.confirm({
      title: '撤回宠物台词',
      message: `确定撤回“${item.message}”吗？已打开网页会在下一次同步时移除。`,
      confirmText: '确认撤回',
      danger: true,
    });
    if (!confirmed) return;
    setRevokingId(item.id);
    setNotice(null);
    try {
      await revokeAdminBotSpeechMessage(item.id);
      await reload();
      if (editingId === item.id) resetForm();
      window.dispatchEvent(new Event('bot-speech:refresh'));
      setNotice({ type: 'success', text: '台词已撤回' });
    } catch (error: unknown) {
      setNotice({ type: 'error', text: toErrorMessage(error, '撤回宠物台词失败') });
    } finally {
      setRevokingId(null);
    }
  };

  return (
    <section id="admin-bot-speech" className="card admin-section admin-speech-panel">
      <div className="card-title">悬浮宠物台词</div>
      <p className="help-text">台词按优先级从高到低进入显示队列；同优先级按发布时间先后显示。撤回后客户端最迟 15 秒移除。</p>
      <form className="form-grid admin-speech-form" onSubmit={handleSubmit}>
        <div className="form-item admin-speech-form__message">
          <label htmlFor="bot-speech-message">气泡台词</label>
          <textarea
            id="bot-speech-message"
            className="input"
            rows={3}
            maxLength={120}
            placeholder="例如：今天也要记得收藏喜欢的学习资料哦！"
            value={form.message}
            onChange={(event) => setForm((current) => ({ ...current, message: event.target.value }))}
          />
          <span className="help-text">{form.message.length}/120 字</span>
        </div>
        <div className="admin-speech-form__options">
          <div className="form-item">
            <label htmlFor="bot-speech-style">显示形式</label>
            <select
              id="bot-speech-style"
              className="input"
              value={form.displayStyle}
              onChange={(event) => setForm((current) => ({ ...current, displayStyle: event.target.value as BotSpeechStyle }))}
            >
              {Object.entries(STYLE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </div>
          <div className="form-item">
            <label htmlFor="bot-speech-duration">显示时长（秒）</label>
            <input
              id="bot-speech-duration"
              className="input"
              type="number"
              min={0}
              max={60}
              value={form.displayDurationSeconds}
              onChange={(event) => setForm((current) => ({ ...current, displayDurationSeconds: event.target.value }))}
            />
            <span className="help-text">0 表示显示到用户手动关闭</span>
          </div>
          <div className="form-item">
            <label htmlFor="bot-speech-priority">队列优先级</label>
            <input
              id="bot-speech-priority"
              className="input"
              type="number"
              min={0}
              max={100}
              value={form.priority}
              onChange={(event) => setForm((current) => ({ ...current, priority: event.target.value }))}
            />
          </div>
          <div className="form-item">
            <label htmlFor="bot-speech-start">开始显示（可选）</label>
            <input
              id="bot-speech-start"
              className="input"
              type="datetime-local"
              value={form.startsAt}
              onChange={(event) => setForm((current) => ({ ...current, startsAt: event.target.value }))}
            />
          </div>
          <div className="form-item">
            <label htmlFor="bot-speech-end">结束显示（可选）</label>
            <input
              id="bot-speech-end"
              className="input"
              type="datetime-local"
              value={form.endsAt}
              onChange={(event) => setForm((current) => ({ ...current, endsAt: event.target.value }))}
            />
          </div>
        </div>
        {notice && <p className={notice.type === 'error' ? 'error-text' : 'success-text'}>{notice.text}</p>}
        <div className="admin-speech-form__actions">
          <button className="button ghost" type="submit" disabled={saving}>{saving ? '保存中...' : '保存草稿'}</button>
          <button className="button primary" type="button" disabled={saving} onClick={() => void submit(true)}>
            {saving ? '处理中...' : form.startsAt ? '加入定时队列' : '立即发布'}
          </button>
          {editingId !== null && <button className="button ghost" type="button" onClick={resetForm}>取消编辑</button>}
        </div>
      </form>

      <div className="admin-speech-queue" aria-busy={loading}>
        <div className="admin-speech-queue__header">
          <strong>消息队列</strong>
          <span className="help-text">共 {messages.length} 条</span>
        </div>
        {!loading && messages.length === 0 && <p className="help-text">还没有台词，先创建第一条吧。</p>}
        {messages.map((item) => (
          <article key={item.id} className={`admin-speech-item status-${item.status.toLowerCase()}`}>
            <div className="admin-speech-item__content">
              <div className="admin-speech-item__meta">
                <span className="admin-speech-status">{STATUS_LABELS[item.status]}</span>
                <span>优先级 {item.priority}</span>
                <span>{STYLE_LABELS[item.displayStyle]}</span>
                <span>{item.displayDurationSeconds === 0 ? '手动关闭' : `${item.displayDurationSeconds} 秒`}</span>
              </div>
              <p>{item.message}</p>
              <div className="admin-speech-item__schedule">
                <span>开始：{item.startsAt ? formatDateTime(item.startsAt) : '立即'}</span>
                <span>结束：{item.endsAt ? formatDateTime(item.endsAt) : '长期'}</span>
                {item.updatedByUserId && <span>操作人 ID：{item.updatedByUserId}</span>}
              </div>
            </div>
            <div className="admin-speech-item__actions">
              {!['REVOKED', 'EXPIRED'].includes(item.status) && (
                <button className="button ghost small" type="button" onClick={() => editMessage(item)}>编辑</button>
              )}
              {!['REVOKED', 'EXPIRED'].includes(item.status) && (
                <button
                  className="button danger small"
                  type="button"
                  disabled={revokingId === item.id}
                  onClick={() => void revokeMessage(item)}
                >
                  {revokingId === item.id ? '撤回中...' : '撤回'}
                </button>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
