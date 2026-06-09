const ALLOWED_PAYMENT_METHODS = new Set(['GET', 'POST']);
const ALIPAY_GATEWAY_HOSTS = new Set(['openapi.alipay.com', 'openapi-sandbox.dl.alipaydev.com']);
const LOCAL_PAYMENT_PATHS = new Set(['/pay/result']);

export function navigateTrustedPaymentUrl(rawUrl: string) {
  if (typeof window === 'undefined') {
    throw new Error('当前环境无法跳转支付页面');
  }
  const url = resolveTrustedPaymentAction(rawUrl, window.location.origin);
  window.location.assign(url.href);
}

export function submitTrustedPaymentForm(container: HTMLElement, formHtml: string) {
  if (typeof window === 'undefined') {
    throw new Error('当前环境无法拉起支付表单');
  }
  const parser = new DOMParser();
  const parsed = parser.parseFromString(formHtml, 'text/html');
  const forms = Array.from(parsed.forms);
  if (forms.length !== 1) {
    throw new Error('支付表单格式异常');
  }
  const sourceForm = forms[0];
  const method = (sourceForm.getAttribute('method') || 'GET').trim().toUpperCase();
  if (!ALLOWED_PAYMENT_METHODS.has(method)) {
    throw new Error('支付表单方法不受支持');
  }
  const action = sourceForm.getAttribute('action') || '';
  const actionUrl = resolveTrustedPaymentAction(action, window.location.origin);

  const form = document.createElement('form');
  form.method = method;
  form.action = actionUrl.href;
  form.style.display = 'none';

  const target = (sourceForm.getAttribute('target') || '').trim();
  if (target && ['_self', '_blank', '_top'].includes(target)) {
    form.target = target;
  }

  const fields = Array.from(sourceForm.querySelectorAll('input')).filter((input) => Boolean(input.name));
  for (const field of fields) {
    const next = document.createElement('input');
    next.type = 'hidden';
    next.name = field.name;
    next.value = field.value;
    form.appendChild(next);
  }

  container.replaceChildren(form);
  HTMLFormElement.prototype.submit.call(form);
}

export function resolveTrustedPaymentAction(action: string, baseOrigin?: string) {
  const trimmed = action.trim();
  if (!trimmed) {
    throw new Error('支付表单缺少提交地址');
  }
  const origin =
    baseOrigin ||
    (typeof window !== 'undefined' && window.location?.origin ? window.location.origin : 'https://studyhub.local');
  const actionUrl = new URL(trimmed, origin);
  const isLocalPaymentReturn = actionUrl.origin === origin && LOCAL_PAYMENT_PATHS.has(actionUrl.pathname);
  const isAlipayGateway = actionUrl.protocol === 'https:' && ALIPAY_GATEWAY_HOSTS.has(actionUrl.hostname);
  if (!isLocalPaymentReturn && !isAlipayGateway) {
    throw new Error('支付表单提交地址不受信任');
  }
  return actionUrl;
}
