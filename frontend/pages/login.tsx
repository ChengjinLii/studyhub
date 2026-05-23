import { GetServerSideProps } from 'next';
import { useRouter } from 'next/router';
import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from 'react';
import AppImage from '../components/AppImage';
import NavBar from '../components/NavBar';
import { readSession } from '../lib/auth';
import { fetchBackend } from '../lib/apiBase';
import { toErrorMessage } from '../lib/errors';
import { SessionUser } from '../types/user';

type AuthMode = 'login' | 'register';

interface LoginPageProps {
  user: SessionUser | null;
}

interface CaptchaState {
  captchaId: string;
  imageBase64: string;
}

interface LocalDevInfo {
  enabled: boolean;
  quickLoginEnabled: boolean;
  developerUsername: string;
}

export default function Login({ user }: LoginPageProps) {
  const router = useRouter();
  const nextPath = useMemo(() => {
    if (typeof router.query.next === 'string' && router.query.next.startsWith('/')) {
      return router.query.next;
    }
    return '/';
  }, [router.query.next]);

  const [mode, setMode] = useState<AuthMode>('login');
  const [loginForm, setLoginForm] = useState({ identifier: '', password: '', captchaCode: '', rememberMe: false });
  const [registerForm, setRegisterForm] = useState({
    username: '',
    email: '',
    password: '',
    confirm: '',
    captchaCode: '',
    code: '',
  });
  const [resetForm, setResetForm] = useState({ identifier: '', newPassword: '', confirm: '', code: '' });
  const [resetCooldown, setResetCooldown] = useState(0);
  const [resetMsg, setResetMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [captcha, setCaptcha] = useState<CaptchaState>({ captchaId: '', imageBase64: '' });
  const [localDevInfo, setLocalDevInfo] = useState<LocalDevInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [devLoginLoading, setDevLoginLoading] = useState(false);
  const [resetLoading, setResetLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [cooldown, setCooldown] = useState(0);
  const [showReset, setShowReset] = useState(false);
  const [resetCaptcha, setResetCaptcha] = useState<{ captchaId: string; imageBase64: string }>({
    captchaId: '',
    imageBase64: '',
  });
  const [resetCaptchaCode, setResetCaptchaCode] = useState('');
  const isRedirecting = success.includes('正在跳转');
  const authStatusText = error || (isRedirecting ? '' : success);
  const authStatusTone = error ? 'error' : success ? 'success' : 'idle';
  const localDevQuickLoginEnabled = Boolean(localDevInfo?.enabled && localDevInfo.quickLoginEnabled);
  const localDevUsername = localDevInfo?.developerUsername || 'developer';

  const handleLoginInput =
    (field: keyof typeof loginForm) =>
    (e: ChangeEvent<HTMLInputElement>): void => {
      if (field === 'rememberMe') {
        setLoginForm((prev) => ({ ...prev, rememberMe: e.target.checked }));
        return;
      }
      setLoginForm((prev) => ({ ...prev, [field]: e.target.value }));
    };

  const handleRegisterInput =
    (field: keyof typeof registerForm) =>
    (e: ChangeEvent<HTMLInputElement>): void => {
      setRegisterForm((prev) => ({ ...prev, [field]: e.target.value }));
    };

  const fetchCaptcha = async () => {
    try {
      const resp = await fetchBackend('/captchas');
      const json = await resp.json();
      if (!resp.ok || !json.ok || !json.data) {
        throw new Error(json.msg || '获取验证码失败');
      }
      setCaptcha(json.data);
      setLoginForm((prev) => ({ ...prev, captchaCode: '' }));
      setRegisterForm((prev) => ({ ...prev, captchaCode: '' }));
    } catch (err: unknown) {
      setError(toErrorMessage(err, '获取验证码失败'));
    }
  };

  useEffect(() => {
    void fetchCaptcha();
  }, []);

  useEffect(() => {
    let active = true;
    const fetchRuntimeInfo = async () => {
      try {
        const resp = await fetchBackend('/healthz');
        const json = await resp.json();
        if (!active || !resp.ok || !json.ok || !json.data?.localDev) {
          return;
        }
        const localDevPayload = json.data.localDev;
        setLocalDevInfo({
          enabled: localDevPayload.enabled === true,
          quickLoginEnabled: localDevPayload.quickLoginEnabled === true,
          developerUsername:
            typeof localDevPayload.developerUsername === 'string' && localDevPayload.developerUsername
              ? localDevPayload.developerUsername
              : 'developer',
        });
      } catch {
        if (active) {
          setLocalDevInfo(null);
        }
      }
    };
    void fetchRuntimeInfo();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => {
      setCooldown((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  useEffect(() => {
    if (resetCooldown <= 0) return;
    const timer = setInterval(() => {
      setResetCooldown((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [resetCooldown]);

  const fetchResetCaptcha = async () => {
    try {
      const resp = await fetchBackend('/captchas');
      const json = await resp.json();
      if (!resp.ok || !json.ok || !json.data) {
        throw new Error(json.msg || '获取验证码失败');
      }
      setResetCaptcha(json.data);
      setResetCaptchaCode('');
    } catch (err: unknown) {
      setResetMsg({ type: 'error', text: toErrorMessage(err, '获取验证码失败') });
    }
  };

  const submitLogin = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setSuccess('');
    if (!captcha.captchaId) {
      setError('请先获取验证码');
      setLoading(false);
      return;
    }
    try {
      const payload = {
        identifier: loginForm.identifier,
        password: loginForm.password,
        captchaId: captcha.captchaId,
        captchaCode: loginForm.captchaCode,
        rememberMe: loginForm.rememberMe,
      };
      const resp = await fetchBackend('/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '登录失败');
      }
      setSuccess('登录成功，正在跳转...');
      router.replace(nextPath || '/');
    } catch (err: unknown) {
      setError(toErrorMessage(err, '登录失败'));
    } finally {
      setLoading(false);
      fetchCaptcha();
    }
  };

  const submitDevLogin = async () => {
    setDevLoginLoading(true);
    setError('');
    setSuccess('');
    try {
      const resp = await fetchBackend('/dev-session', {
        method: 'POST',
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '进入 local-dev 账号失败');
      }
      setSuccess('local-dev 账号已就绪，正在跳转...');
      router.replace(nextPath || '/');
    } catch (err: unknown) {
      setError(toErrorMessage(err, '进入 local-dev 账号失败'));
    } finally {
      setDevLoginLoading(false);
    }
  };

  const submitRegister = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setSuccess('');
    if (registerForm.password !== registerForm.confirm) {
      setError('两次输入的密码不一致');
      setLoading(false);
      return;
    }
    if (!captcha.captchaId) {
      setError('请先获取验证码');
      setLoading(false);
      return;
    }
    try {
      const resp = await fetchBackend('/registrations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: registerForm.email,
          code: registerForm.code,
          purpose: 'REGISTER',
        }),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '注册失败');
      }
      setSuccess('注册并登录成功，正在跳转...');
      router.replace(nextPath || '/');
    } catch (err: unknown) {
      setError(toErrorMessage(err, '注册失败'));
    } finally {
      setLoading(false);
    }
  };

  const sendRegisterCode = async () => {
    setError('');
    setSuccess('');
    if (registerForm.password !== registerForm.confirm) {
      setError('两次输入的密码不一致');
      return;
    }
    if (!captcha.captchaId) {
      setError('请先获取验证码');
      return;
    }
    setLoading(true);
    try {
      const payload = {
        username: registerForm.username,
        email: registerForm.email,
        password: registerForm.password,
        captchaId: captcha.captchaId,
        captchaCode: registerForm.captchaCode,
      };
      const resp = await fetchBackend('/registration-verifications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '发送验证码失败');
      }
      const resendSeconds = json.data?.resendAfterSeconds ?? 60;
      setCooldown(resendSeconds);
      setSuccess('验证码已发送至邮箱，请在 5 分钟内完成验证。建议使用国内邮箱，未收到请查看垃圾邮件或稍后重试。');
    } catch (err: unknown) {
      setError(toErrorMessage(err, '发送验证码失败'));
    } finally {
      setLoading(false);
      fetchCaptcha();
    }
  };

  const sendResetCode = async () => {
    setResetMsg(null);
    if (resetForm.newPassword !== resetForm.confirm) {
      setResetMsg({ type: 'error', text: '两次输入的新密码不一致' });
      return;
    }
    if (!resetCaptcha.captchaId || !resetCaptchaCode) {
      setResetMsg({ type: 'error', text: '请先完成图形验证码' });
      return;
    }
    setResetLoading(true);
    try {
      const resp = await fetchBackend('/password-resets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          identifier: resetForm.identifier,
          newPassword: resetForm.newPassword,
          captchaId: resetCaptcha.captchaId,
          captchaCode: resetCaptchaCode,
        }),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '发送验证码失败');
      }
      setResetCooldown(json.data?.resendAfterSeconds ?? 60);
      setResetMsg({ type: 'success', text: '验证码已发送，请查收邮箱' });
    } catch (err: unknown) {
      setResetMsg({ type: 'error', text: toErrorMessage(err, '发送验证码失败') });
    } finally {
      setResetLoading(false);
    }
  };

  const confirmReset = async () => {
    setResetMsg(null);
    if (!resetForm.code) {
      setResetMsg({ type: 'error', text: '请输入验证码' });
      return;
    }
    setResetLoading(true);
    try {
      const resp = await fetchBackend('/password-resets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          identifier: resetForm.identifier,
          newPassword: resetForm.newPassword,
          code: resetForm.code,
        }),
      });
      const json = await resp.json();
      if (!resp.ok || !json.ok) {
        throw new Error(json.msg || '重置失败');
      }
      setResetMsg({ type: 'success', text: '重置成功，请使用新密码登录' });
      setResetCooldown(0);
      setResetForm((prev) => ({ ...prev, code: '' }));
      setLoginForm((prev) => ({ ...prev, identifier: resetForm.identifier }));
    } catch (err: unknown) {
      setResetMsg({ type: 'error', text: toErrorMessage(err, '重置失败') });
    } finally {
      setResetLoading(false);
    }
  };

  const switchMode = (nextMode: AuthMode) => {
    setMode(nextMode);
    setError('');
    setSuccess('');
    setResetMsg(null);
    setResetCooldown(0);
    if (nextMode === 'register') {
      fetchCaptcha();
    }
  };

  return (
    <>
      <NavBar user={user} />
      <main className="container login-page">
        <div className="login-shell">
          <aside className="login-aside">
            <div className="login-brand">StudyHub · 学汇</div>
            <h1 className="login-title">让知识流动起来</h1>
            <p className="login-subtitle">登录后即可投稿、定价分享、获取资料与逛校园集市，和同校同学一起共建知识库。</p>
            <div className="login-highlights">
              <div className="login-highlight">
                <span className="login-highlight__dot" aria-hidden="true" />
                <div>
                  <strong>轻量协作</strong>
                  <span>一键投稿，帮助更多同学高效备考。</span>
                </div>
              </div>
              <div className="login-highlight">
                <span className="login-highlight__dot" aria-hidden="true" />
                <div>
                  <strong>定价收益</strong>
                  <span>可为资料设置小额定价，获得收益与认可。</span>
                </div>
              </div>
              <div className="login-highlight">
                <span className="login-highlight__dot" aria-hidden="true" />
                <div>
                  <strong>资料获取</strong>
                  <span>海量资料快速检索，按需下载更省时间。</span>
                </div>
              </div>
              <div className="login-highlight">
                <span className="login-highlight__dot" aria-hidden="true" />
                <div>
                  <strong>校园集市</strong>
                  <span>买卖同校好物，让闲置重新焕发生命力。</span>
                </div>
              </div>
            </div>
          </aside>
          <section className="card login-card">
            <div className="login-card__header">
              <div>
                <p className="login-card__eyebrow">账号入口</p>
                <h2>{mode === 'login' ? '欢迎回来' : '创建新账号'}</h2>
              </div>
            </div>
            {localDevQuickLoginEnabled && (
              <div className="login-dev-card">
                <div className="login-dev-card__copy">
                  <span className="login-dev-card__eyebrow">Local Dev</span>
                  <strong>本地开发环境已就绪</strong>
                  <p>
                    预置账号 <code>{localDevUsername}</code> 已可直接进入；常规登录、注册与找回密码流程仍然保留，方便联调认证链路。
                  </p>
                </div>
                <button
                  className="button primary login-dev-card__button"
                  type="button"
                  onClick={submitDevLogin}
                  disabled={devLoginLoading || loading || isRedirecting}
                >
                  {devLoginLoading ? '正在进入...' : `快捷登录 ${localDevUsername}`}
                </button>
              </div>
            )}
            <div className="login-tabs" role="tablist" aria-label="登录注册切换">
              <button
                type="button"
                className={`login-tab ${mode === 'login' ? 'active' : ''}`}
                onClick={() => switchMode('login')}
                aria-selected={mode === 'login'}
                role="tab"
              >
                账号 / 邮箱登录
              </button>
              <button
                type="button"
                className={`login-tab ${mode === 'register' ? 'active' : ''}`}
                onClick={() => switchMode('register')}
                aria-selected={mode === 'register'}
                role="tab"
              >
                邮箱注册
              </button>
            </div>

            <div className="login-mode-shell">
            <form className="form-grid login-form" onSubmit={mode === 'login' ? submitLogin : submitRegister}>
              {mode === 'login' ? (
                <>
                  <div className="form-item full">
                    <label htmlFor="identifier">账号 / 邮箱</label>
                    <input
                      id="identifier"
                      value={loginForm.identifier}
                      onChange={handleLoginInput('identifier')}
                      placeholder="输入用户名或邮箱"
                      required
                    />
                  </div>
                  <div className="form-item full">
                    <label htmlFor="password">密码</label>
                    <input
                      id="password"
                      type="password"
                      value={loginForm.password}
                      onChange={handleLoginInput('password')}
                      placeholder="不少于 6 位"
                      required
                    />
                  </div>
                  <div className="form-item full">
                    <label htmlFor="captcha">验证码</label>
                    <div className="captcha-row">
                      <input
                        id="captcha"
                        value={loginForm.captchaCode}
                        onChange={handleLoginInput('captchaCode')}
                        placeholder="请输入图形验证码"
                        required
                      />
                      {captcha.imageBase64 ? (
                        <AppImage
                          src={captcha.imageBase64}
                          alt="验证码"
                          className="captcha-image"
                          onClick={fetchCaptcha}
                          role="button"
                          aria-label="点击刷新验证码"
                        />
                      ) : (
                        <button className="button ghost" type="button" onClick={fetchCaptcha} disabled={loading}>
                          获取验证码
                        </button>
                      )}
                    </div>
                    <p className="help-text">不区分大小写，输入任意大小写均可通过。</p>
                  </div>
                  <div className="form-item full remember-row">
                    <label className="remember-label">
                      <input
                        type="checkbox"
                        checked={loginForm.rememberMe}
                        onChange={handleLoginInput('rememberMe')}
                      />
                      <span>7天内免登录</span>
                    </label>
                  </div>
                </>
              ) : (
                <>
                  <div className="form-item full">
                    <label className="spaced-label" htmlFor="reg-username">用户名</label>
                    <input
                      id="reg-username"
                      value={registerForm.username}
                      onChange={handleRegisterInput('username')}
                      placeholder="支持中文 / 英文 / 数字 / 下划线，3-32 个字符"
                      maxLength={32}
                      required
                    />
                  </div>
                  <div className="form-item full">
                    <label className="spaced-label" htmlFor="reg-email">邮箱</label>
                    <input
                      id="reg-email"
                      type="email"
                      value={registerForm.email}
                      onChange={handleRegisterInput('email')}
                      placeholder="请输入有效邮箱，便于登录与找回密码"
                      required
                    />
                    <p className="help-text">建议使用国内邮箱（如 QQ/163/126），若未收到验证码请检查垃圾邮件。</p>
                  </div>
                  <div className="form-item full">
                    <label className="spaced-label" htmlFor="reg-password">设置密码</label>
                    <input
                      id="reg-password"
                      type="password"
                      value={registerForm.password}
                      onChange={handleRegisterInput('password')}
                      placeholder="不少于 6 位"
                      required
                    />
                  </div>
                  <div className="form-item full">
                    <label className="spaced-label" htmlFor="reg-confirm">确认密码</label>
                    <input
                      id="reg-confirm"
                      type="password"
                      value={registerForm.confirm}
                      onChange={handleRegisterInput('confirm')}
                      placeholder="再次输入密码"
                      required
                    />
                  </div>
                  <div className="form-item full">
                    <label className="spaced-label" htmlFor="reg-captcha">图形验证码</label>
                    <div className="captcha-row">
                      <input
                        id="reg-captcha"
                        value={registerForm.captchaCode}
                        onChange={handleRegisterInput('captchaCode')}
                        placeholder="请输入图形验证码"
                        required
                      />
                      {captcha.imageBase64 ? (
                        <AppImage
                          src={captcha.imageBase64}
                          alt="验证码"
                          className="captcha-image"
                          onClick={fetchCaptcha}
                          role="button"
                          aria-label="点击刷新验证码"
                        />
                      ) : (
                        <button className="button ghost" type="button" onClick={fetchCaptcha} disabled={loading}>
                          获取验证码
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="form-item full">
                    <label className="spaced-label" htmlFor="reg-code">邮箱验证码</label>
                    <div className="captcha-row login-code-row">
                      <input
                        id="reg-code"
                        value={registerForm.code}
                        onChange={handleRegisterInput('code')}
                        placeholder="输入邮箱验证码"
                        maxLength={10}
                        required
                      />
                      <button
                        className="button ghost"
                        type="button"
                        disabled={loading || cooldown > 0}
                        onClick={sendRegisterCode}
                      >
                        {cooldown > 0 ? `重发 (${cooldown}s)` : '发送验证码'}
                      </button>
                    </div>
                  </div>
                </>
              )}
              <div className={`form-item full form-actions login-actions${mode === 'register' ? ' login-actions--compact' : ''}`}>
                <button
                  className="button primary login-submit-button"
                  type="submit"
                  disabled={loading || devLoginLoading || isRedirecting}
                  aria-busy={loading || devLoginLoading || isRedirecting}
                >
                  {(loading || isRedirecting) && (
                    <span className="button-icon login-submit-spinner" aria-hidden="true">
                      <svg viewBox="0 0 24 24" focusable="false">
                        <circle cx="12" cy="12" r="8" />
                      </svg>
                    </span>
                  )}
                  {mode === 'login'
                    ? isRedirecting
                      ? '登录成功，正在跳转...'
                      : loading
                        ? '处理中...'
                        : '登录'
                    : isRedirecting
                      ? '注册成功，正在跳转...'
                      : loading
                        ? '处理中...'
                        : '完成注册并登录'}
                </button>
                {mode === 'login' ? (
                  <button
                    type="button"
                    className="button ghost login-secondary-button"
                    onClick={() => {
                      setShowReset(true);
                      setResetMsg(null);
                      fetchResetCaptcha();
                    }}
                  >
                    忘记密码？
                  </button>
                ) : (
                  <button
                    type="button"
                    className="button ghost login-secondary-button"
                    onClick={() => switchMode('login')}
                  >
                    返回登录
                  </button>
                )}
              </div>
            </form>

            <div
              className={`login-status-slot ${authStatusTone !== 'idle' ? `is-${authStatusTone}` : ''}`}
              aria-live="polite"
            >
              {authStatusText && (
                <p className={error ? 'error-text' : 'success-text'}>
                  {authStatusText}
                </p>
              )}
            </div>
            </div>
            {showReset && (
              <div
                className="login-reset-overlay"
                onClick={() => {
                  setShowReset(false);
                  setResetMsg(null);
                  setResetCooldown(0);
                }}
              >
                <div
                  className="reset-panel login-reset-panel"
                  role="dialog"
                  aria-modal="true"
                  aria-label="重置密码"
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="login-reset-panel__header">
                    <div>
                      <div className="login-card__eyebrow">找回账号</div>
                      <div className="card-title">重置密码</div>
                    </div>
                    <button
                      className="login-reset-panel__close"
                      type="button"
                      aria-label="关闭重置密码面板"
                      onClick={() => {
                        setShowReset(false);
                        setResetMsg(null);
                        setResetCooldown(0);
                      }}
                    >
                      ×
                    </button>
                  </div>
                  <form
                    className="form-grid"
                    onSubmit={(e) => {
                      e.preventDefault();
                      confirmReset();
                    }}
                  >
                    <div className="form-item full">
                      <label className="spaced-label" htmlFor="reset-identifier">账号 / 邮箱</label>
                      <input
                        id="reset-identifier"
                        value={resetForm.identifier}
                        onChange={(e) => setResetForm((prev) => ({ ...prev, identifier: e.target.value }))}
                        placeholder="请输入注册时的用户名或邮箱"
                        required
                      />
                    </div>
                    <div className="form-item full">
                      <label className="spaced-label" htmlFor="reset-password">新密码</label>
                      <input
                        id="reset-password"
                        type="password"
                        value={resetForm.newPassword}
                        onChange={(e) => setResetForm((prev) => ({ ...prev, newPassword: e.target.value }))}
                        placeholder="不少于 6 位"
                        required
                      />
                    </div>
                    <div className="form-item full">
                      <label className="spaced-label" htmlFor="reset-confirm">确认新密码</label>
                      <input
                        id="reset-confirm"
                        type="password"
                        value={resetForm.confirm}
                        onChange={(e) => setResetForm((prev) => ({ ...prev, confirm: e.target.value }))}
                        placeholder="再次输入新密码"
                        required
                      />
                    </div>
                    <div className="form-item full">
                      <label htmlFor="reset-captcha">图形验证码</label>
                      <div className="captcha-row">
                        <input
                          id="reset-captcha"
                          value={resetCaptchaCode}
                          onChange={(e) => setResetCaptchaCode(e.target.value)}
                          placeholder="请输入图形验证码"
                          required
                        />
                        {resetCaptcha.imageBase64 ? (
                          <AppImage
                            src={resetCaptcha.imageBase64}
                            alt="验证码"
                            className="captcha-image"
                            onClick={fetchResetCaptcha}
                            role="button"
                            aria-label="点击刷新验证码"
                          />
                        ) : (
                          <button className="button ghost" type="button" onClick={fetchResetCaptcha} disabled={resetLoading}>
                            获取验证码
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="form-item full">
                      <label className="spaced-label" htmlFor="reset-code">邮箱验证码</label>
                      <div className="captcha-row small-gap" style={{ alignItems: 'center' }}>
                        <input
                          id="reset-code"
                          value={resetForm.code}
                          onChange={(e) => setResetForm((prev) => ({ ...prev, code: e.target.value }))}
                          placeholder="输入邮箱验证码"
                          required
                          style={{ maxWidth: '220px' }}
                        />
                        <button
                          className="button ghost wide-button"
                          type="button"
                          disabled={resetLoading || resetCooldown > 0}
                          onClick={sendResetCode}
                        >
                          {resetCooldown > 0 ? `重发 (${resetCooldown}s)` : '发送重置邮件'}
                        </button>
                      </div>
                    </div>
                    <div className="form-item form-actions login-reset-actions">
                      <button
                        className="button ghost"
                        type="button"
                        onClick={() => {
                          setShowReset(false);
                          setResetMsg(null);
                          setResetCooldown(0);
                        }}
                      >
                        取消
                      </button>
                      <button className="button primary" type="submit" disabled={resetLoading}>
                        {resetLoading ? '处理中...' : '提交验证码并重置'}
                      </button>
                    </div>
                  </form>
                  {resetMsg && <p className={resetMsg.type === 'error' ? 'error-text' : 'success-text'}>{resetMsg.text}</p>}
                </div>
              </div>
            )}
          </section>
        </div>
      </main>
    </>
  );
}

export const getServerSideProps: GetServerSideProps<LoginPageProps> = async (ctx) => {
  const session = readSession(ctx.req);
  const next = typeof ctx.query.next === 'string' && ctx.query.next.startsWith('/') ? ctx.query.next : '/';
  if (session.user) {
    return {
      redirect: {
        destination: next,
        permanent: false,
      },
    };
  }
  return {
    props: {
      user: null,
    },
  };
};
