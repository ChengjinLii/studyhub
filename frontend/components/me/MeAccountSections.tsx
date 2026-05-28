import { FormEvent } from 'react';
import Link from 'next/link';

type AlertMessage = { type: 'success' | 'error'; message: string } | null;

interface BindFormState {
  email: string;
  code: string;
}

interface MeAccountSectionsProps {
  adminQq: string;
  bindForm: BindFormState;
  bindVerified: boolean;
  bindLoading: boolean;
  bindCooldown: number;
  bindMessage: AlertMessage;
  currentEmail?: string | null;
  freeDownloadsLeft: number | string;
  onBindFormChange: (patch: Partial<BindFormState>) => void;
  onSendBindCode: () => void;
  onConfirmBindEmail: (event: FormEvent<HTMLFormElement>) => void;
}

export default function MeAccountSections({
  adminQq,
  bindForm,
  bindVerified,
  bindLoading,
  bindCooldown,
  bindMessage,
  currentEmail,
  freeDownloadsLeft,
  onBindFormChange,
  onSendBindCode,
  onConfirmBindEmail,
}: MeAccountSectionsProps) {
  return (
    <>
      <section className="card" id="email-binding">
        <div className="card-title">邮箱绑定</div>
        <form className="form-grid" onSubmit={onConfirmBindEmail}>
          <div className="form-item full">
            <label htmlFor="bind-email">邮箱地址</label>
            <input
              id="bind-email"
              type="email"
              value={bindForm.email}
              onChange={(e) => onBindFormChange({ email: e.target.value })}
              placeholder="输入要绑定的邮箱"
              required
            />
            <p className="help-text">
              状态：{bindVerified ? '已验证' : '未验证'} {currentEmail ? `(当前：${currentEmail})` : ''}
            </p>
          </div>
          <div className="form-item full">
            <label htmlFor="bind-code">邮箱验证码</label>
            <div className="captcha-row">
              <input
                id="bind-code"
                value={bindForm.code}
                onChange={(e) => onBindFormChange({ code: e.target.value })}
                placeholder="输入邮箱验证码"
                required
              />
              <button
                className="button ghost"
                type="button"
                disabled={bindLoading || bindCooldown > 0}
                onClick={onSendBindCode}
              >
                {bindCooldown > 0 ? `重新发送 (${bindCooldown}s)` : '发送验证码'}
              </button>
            </div>
          </div>
          <div className="form-item">
            <button className="button primary" type="submit" disabled={bindLoading}>
              {bindLoading ? '处理中...' : '确认绑定'}
            </button>
          </div>
        </form>
        {bindMessage && <p className={bindMessage.type === 'error' ? 'error-text' : 'success-text'}>{bindMessage.message}</p>}
      </section>

      <section className="card" id="download-quota">
        <div className="card-title">下载次数额度</div>
        <p>
          剩余：<strong>{freeDownloadsLeft}</strong> 次 / 200 次上限（含免费与付费资料）。
        </p>
        <p className="help-text">如需重置请联系管理员（QQ群 {adminQq}）。</p>
        <div className="inline-group" style={{ marginTop: 8 }}>
          <Link className="button ghost" href="/">
            去下载资料
          </Link>
          <Link className="button ghost" href="/join">
            关于我们
          </Link>
        </div>
      </section>
    </>
  );
}
