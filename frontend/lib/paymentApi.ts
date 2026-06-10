import { fetchBackend } from './apiBase';
import { ensureApiSuccess, readApiEnvelope } from './apiEnvelope';
import { extractErrorMessage } from './errors';

export interface PaymentStatusResult {
  status?: string;
  materialId?: number | null;
  requestId?: number | null;
}

export interface AlipayPaymentResult {
  status?: string;
  form?: string | null;
  gatewayUrl?: string | null;
}

const fetchPaymentStatus = async (endpoint: string) => {
  const response = await fetchBackend(endpoint);
  const json = await readApiEnvelope<PaymentStatusResult>(response);
  return { response, json };
};

export const fetchOrderStatus = async (orderNo: string, forceCheck = false) => {
  const isRequestContribution = orderNo.startsWith('RQ');
  const forceSuffix = forceCheck ? '&force=1' : '';
  const materialEndpoint = `/orders/status?orderNo=${encodeURIComponent(orderNo)}${forceSuffix}`;
  const requestEndpoint = `/requests/contributions/status?orderNo=${encodeURIComponent(orderNo)}${forceSuffix}`;
  let result = await fetchPaymentStatus(isRequestContribution ? requestEndpoint : materialEndpoint);
  if (result.response.status === 401) {
    return { unauthorized: true, data: null };
  }
  if ((!result.response.ok || !result.json.ok) && !isRequestContribution) {
    result = await fetchPaymentStatus(`/requests/contributions/status?orderNo=${encodeURIComponent(orderNo)}`);
  }
  if (!result.response.ok || !result.json.ok) {
    throw new Error(extractErrorMessage(result.json, '查询订单状态失败'));
  }
  return { unauthorized: false, data: result.json.data || {} };
};

export const createAlipayPayment = async (materialId: number, signal?: AbortSignal) => {
  const response = await fetchBackend('/alipay-payments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ materialId }),
    signal,
  });
  if (response.status === 401) {
    return { unauthorized: true, data: null };
  }
  const envelope = await ensureApiSuccess<AlipayPaymentResult>(response, '发起支付失败');
  return { unauthorized: false, data: envelope.data || {} };
};
