import { FormEvent } from 'react';
import AppImage from '../AppImage';

interface CaptchaState {
  captchaId: string;
  imageBase64: string;
}

interface PasswordFormState {
  oldPassword: string;
  newPassword: string;
  confirm: string;
}

interface EmailResetFormState {
  identifier: string;
  newPassword: string;
  confirm: string;
  code: string;
}

type AlertMessage = { type: 'success' | 'error'; message: string } | null;

interface MeSecuritySectionProps {
  userEmail?: string | null;
  adminQq: string;
  passwordForm: PasswordFormState;
  pwdLoading: boolean;
  pwdMessage: AlertMessage;
  emailResetForm: EmailResetFormState;
  resetCaptcha: CaptchaState;
  resetCaptchaCode: string;
  emailResetLoading: boolean;
  emailResetCooldown: number;
  emailResetMessage: AlertMessage;
  onPasswordFormChange: (patch: Partial<PasswordFormState>) => void;
  onEmailResetFormChange: (patch: Partial<EmailResetFormState>) => void;
  onResetCaptchaCodeChange: (value: string) => void;
  onPasswordSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onEmailResetSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onFetchResetCaptcha: () => void;
  onSendEmailResetCode: () => void;
}

export default function MeSecuritySection({
  userEmail,
  adminQq,
  passwordForm,
  pwdLoading,
  pwdMessage,
  emailResetForm,
  resetCaptcha,
  resetCaptchaCode,
  emailResetLoading,
  emailResetCooldown,
  emailResetMessage,
  onPasswordFormChange,
  onEmailResetFormChange,
  onResetCaptchaCodeChange,
  onPasswordSubmit,
  onEmailResetSubmit,
  onFetchResetCaptcha,
  onSendEmailResetCode,
}: MeSecuritySectionProps) {
  return (
    <section className="card" id="security">
      <div className="card-title">修改密码</div>
      <div className="security-block">
        <h4>已记得旧密码</h4>
        <form className="form-grid" onSubmit={onPasswordSubmit}>
          <div className="form-item full">
            <label htmlFor="oldPassword">旧密码</label>
            <input
              id="oldPassword"
              type="password"
              value={passwordForm.oldPassword}
              onChange={(e) => onPasswordFormChange({ oldPassword: e.target.value })}
              required
            />
          </div>
          <div className="form-item full">
            <label htmlFor="newPassword">新密码</label>
            <input
              id="newPassword"
              type="password"
              value={passwordForm.newPassword}
              onChange={(e) => onPasswordFormChange({ newPassword: e.target.value })}
              placeholder="不少于 6 位"
              required
            />
          </div>
          <div className="form-item full">
            <label htmlFor="confirmPassword">确认新密码</label>
            <input
              id="confirmPassword"
              type="password"
              value={passwordForm.confirm}
              onChange={(e) => onPasswordFormChange({ confirm: e.target.value })}
              required
            />
          </div>
          <div className="form-item">
            <button className="button primary" type="submit" disabled={pwdLoading}>
              {pwdLoading ? '提交中...' : '更新密码'}
            </button>
          </div>
        </form>
        <p className="help-text">推荐常规方式修改；若遗忘旧密码，可尝试下方邮箱验证。</p>
        {pwdMessage && <p className={pwdMessage.type === 'error' ? 'error-text' : 'success-text'}>{pwdMessage.message}</p>}
      </div>
      <div className="divider" style={{ margin: '16px 0', borderTop: '1px dashed #e0e4ef' }} />
      <div className="security-block">
        <h4>忘记旧密码（邮箱验证）</h4>
        <form className="form-grid" onSubmit={onEmailResetSubmit}>
          <div className="form-item full">
            <label htmlFor="reset-identifier">账号 / 邮箱</label>
            <input
              id="reset-identifier"
              value={emailResetForm.identifier}
              onChange={(e) => onEmailResetFormChange({ identifier: e.target.value })}
              placeholder="请输入已绑定的邮箱或账号"
              required
            />
            <p className="help-text">
              {userEmail ? `验证码将发送至：${userEmail}` : '需先绑定邮箱后才可通过邮箱重置密码。'}
            </p>
          </div>
          <div className="form-item full">
            <label htmlFor="reset-new-password">新密码</label>
            <input
              id="reset-new-password"
              type="password"
              value={emailResetForm.newPassword}
              onChange={(e) => onEmailResetFormChange({ newPassword: e.target.value })}
              placeholder="不少于 6 位"
              required
            />
          </div>
          <div className="form-item full">
            <label htmlFor="reset-confirm-password">确认新密码</label>
            <input
              id="reset-confirm-password"
              type="password"
              value={emailResetForm.confirm}
              onChange={(e) => onEmailResetFormChange({ confirm: e.target.value })}
              required
            />
          </div>
          <div className="form-item full">
            <label htmlFor="reset-captcha">图形验证码</label>
            <div className="captcha-row">
              <input
                id="reset-captcha"
                value={resetCaptchaCode}
                onChange={(e) => onResetCaptchaCodeChange(e.target.value)}
                placeholder="请输入图形验证码"
                required
              />
              {resetCaptcha.imageBase64 ? (
                <AppImage
                  src={resetCaptcha.imageBase64}
                  alt="验证码"
                  className="captcha-image"
                  onClick={onFetchResetCaptcha}
                  role="button"
                  aria-label="点击刷新验证码"
                />
              ) : (
                <button className="button ghost" type="button" onClick={onFetchResetCaptcha} disabled={emailResetLoading}>
                  获取验证码
                </button>
              )}
            </div>
          </div>
          <div className="form-item full">
            <label htmlFor="reset-code">邮箱验证码</label>
            <div className="captcha-row">
              <input
                id="reset-code"
                value={emailResetForm.code}
                onChange={(e) => onEmailResetFormChange({ code: e.target.value })}
                placeholder="输入邮箱验证码"
                required
              />
              <button
                className="button ghost"
                type="button"
                disabled={emailResetLoading || emailResetCooldown > 0 || !emailResetForm.identifier}
                onClick={onSendEmailResetCode}
              >
                {emailResetCooldown > 0 ? `重新发送 (${emailResetCooldown}s)` : '发送验证码'}
              </button>
            </div>
          </div>
          <div className="form-item">
            <button className="button primary" type="submit" disabled={emailResetLoading}>
              {emailResetLoading ? '提交中...' : '通过邮箱重置'}
            </button>
          </div>
        </form>
        <p className="help-text">若邮箱无法使用，仍可联系管理员协助处理（QQ群 {adminQq}）。</p>
        {emailResetMessage && (
          <p className={emailResetMessage.type === 'error' ? 'error-text' : 'success-text'}>
            {emailResetMessage.message}
          </p>
        )}
      </div>
    </section>
  );
}
