import { fetchBackend } from './apiBase';
import { ensureApiSuccess, unwrapApiResponse } from './apiEnvelope';

export interface CaptchaPayload {
  captchaId: string;
  imageBase64: string;
}

export interface LocalDevInfoPayload {
  enabled: boolean;
  quickLoginEnabled: boolean;
  developerUsername: string;
}

export interface LoginPayload {
  identifier: string;
  password: string;
  captchaId: string;
  captchaCode: string;
  rememberMe?: boolean;
}

export interface RegisterVerificationPayload {
  username: string;
  email: string;
  password: string;
  captchaId: string;
  captchaCode: string;
}

export interface RegistrationPayload {
  registrationTicket: string;
  purpose: 'REGISTER';
}

export interface RegistrationTicketPayload {
  email: string;
  code: string;
  purpose: 'REGISTER';
}

export interface PasswordResetSendPayload {
  identifier: string;
  newPassword: string;
  captchaId: string;
  captchaCode: string;
}

export interface PasswordResetConfirmPayload {
  identifier: string;
  newPassword: string;
  code: string;
}

export interface VerificationSendResult {
  email: string;
  expiresInSeconds: number;
  resendAfterSeconds: number;
}

export interface RegistrationTicketResult {
  registrationTicket: string;
  expiresInSeconds: number;
}

export const fetchCaptchaPayload = async () => {
  const response = await fetchBackend('/captchas');
  return unwrapApiResponse<CaptchaPayload>(response, '获取验证码失败');
};

export const fetchLocalDevInfo = async () => {
  const response = await fetchBackend('/healthz');
  const data = await unwrapApiResponse<{ localDev?: Partial<LocalDevInfoPayload> }>(response, '加载运行信息失败');
  const localDev = data.localDev;
  if (!localDev) {
    return null;
  }
  return {
    enabled: localDev.enabled === true,
    quickLoginEnabled: localDev.quickLoginEnabled === true,
    developerUsername:
      typeof localDev.developerUsername === 'string' && localDev.developerUsername
        ? localDev.developerUsername
        : 'developer',
  };
};

export const loginWithPassword = async (payload: LoginPayload) => {
  const response = await fetchBackend('/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return ensureApiSuccess(response, '登录失败');
};

export const loginWithLocalDev = async () => {
  const response = await fetchBackend('/dev-session', { method: 'POST' });
  return ensureApiSuccess(response, '进入 local-dev 账号失败');
};

export const completeRegistration = async (payload: RegistrationPayload) => {
  const response = await fetchBackend('/registrations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return ensureApiSuccess(response, '注册失败');
};

export const issueRegistrationTicket = async (payload: RegistrationTicketPayload) => {
  const response = await fetchBackend('/registration-tickets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const envelope = await ensureApiSuccess<RegistrationTicketResult>(response, '验证码验证失败');
  return envelope.data;
};

export const sendRegistrationVerification = async (payload: RegisterVerificationPayload) => {
  const response = await fetchBackend('/registration-verifications', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const envelope = await ensureApiSuccess<VerificationSendResult>(response, '发送验证码失败');
  return envelope.data;
};

export const sendPasswordResetCode = async (payload: PasswordResetSendPayload) => {
  const response = await fetchBackend('/password-resets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const envelope = await ensureApiSuccess<VerificationSendResult>(response, '发送验证码失败');
  return envelope.data;
};

export const confirmPasswordReset = async (payload: PasswordResetConfirmPayload) => {
  const response = await fetchBackend('/password-resets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return ensureApiSuccess(response, '重置失败');
};
