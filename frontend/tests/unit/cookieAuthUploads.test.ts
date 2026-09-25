import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createMarketItem } from '../../lib/market';
import { sendStagedUploadFormData } from '../../lib/stagedUpload';
import { requestMaterialUploadAuthorization } from '../../lib/uploadAuthorization';
import { sendUploadFormData } from '../../lib/uploadSubmit';

const SITE_ORIGIN = 'https://study-hub.cn';

class FakeXhr {
  static instances: FakeXhr[] = [];
  static nextResponse: unknown = null;
  withCredentials = false;
  withCredentialsAtSend: boolean | null = null;
  headers: Record<string, string> = {};
  upload: Record<string, unknown> = {};
  responseType = '';
  responseText = '';
  timeout = 0;
  status = 0;
  response: unknown = null;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  ontimeout: (() => void) | null = null;

  constructor() {
    FakeXhr.instances.push(this);
  }

  open() {}

  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }

  send() {
    this.withCredentialsAtSend = this.withCredentials;
    this.status = 200;
    this.response = FakeXhr.nextResponse;
    this.onload?.();
  }
}

const jsonResponse = (data: unknown) =>
  new Response(JSON.stringify({ ok: true, data }), { headers: { 'content-type': 'application/json' } });

const headerNames = (init: RequestInit | undefined) =>
  Object.keys((init?.headers as Record<string, string> | undefined) || {}).map((name) => name.toLowerCase());

describe('browser uploads authenticate with the HttpOnly session cookie', () => {
  beforeEach(() => {
    FakeXhr.instances = [];
    vi.stubEnv('NEXT_PUBLIC_API_BASE', '');
    vi.stubGlobal('window', { location: { origin: SITE_ORIGIN } });
    vi.stubGlobal('XMLHttpRequest', FakeXhr);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it('requests upload authorization with credentials and no bearer header', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) =>
      jsonResponse({ uploadToken: 'upload-token', expiresInSeconds: 60, remainingDailySubmissions: 1, remainingDailyBytes: 1 })
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(requestMaterialUploadAuthorization('submission-1', [])).resolves.toMatchObject({ uploadToken: 'upload-token' });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${SITE_ORIGIN}/api/material-upload-authorizations`);
    expect(init?.credentials).toBe('include');
    expect(headerNames(init)).not.toContain('authorization');
  });

  it('sends staged uploads with the session cookie and the upload token only', async () => {
    FakeXhr.nextResponse = { ok: true, data: { stagedUploadToken: 'staged', files: 1 } };

    await expect(
      sendStagedUploadFormData(`${SITE_ORIGIN}/api/material-uploads/stage`, new FormData(), {
        uploadToken: 'upload-token',
        onProgress: () => undefined,
        requestRef: { current: null },
      })
    ).resolves.toEqual({ stagedUploadToken: 'staged', files: 1 });
    const xhr = FakeXhr.instances[0];
    expect(xhr.withCredentialsAtSend).toBe(true);
    expect(xhr.headers).toEqual({ 'X-StudyHub-Upload-Token': 'upload-token' });
  });

  it('submits materials with the session cookie and no bearer header', async () => {
    FakeXhr.nextResponse = { ok: true, data: { id: 7 } };

    await expect(
      sendUploadFormData(`${SITE_ORIGIN}/api/materials`, 'POST', new FormData(), {
        uploadToken: 'upload-token',
        onProgress: () => undefined,
        requestRef: { current: null },
      })
    ).resolves.toMatchObject({ data: { id: 7 } });
    const xhr = FakeXhr.instances[0];
    expect(xhr.withCredentialsAtSend).toBe(true);
    expect(Object.keys(xhr.headers).map((name) => name.toLowerCase())).not.toContain('authorization');
  });

  it('creates market items with credentials and no bearer header', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ id: 3, title: 'Book' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(createMarketItem(new FormData(), SITE_ORIGIN)).resolves.toMatchObject({ id: 3 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${SITE_ORIGIN}/api/market`);
    expect(init?.method).toBe('POST');
    expect(init?.credentials).toBe('include');
    expect(headerNames(init)).not.toContain('authorization');
  });
});

describe('pages never serialize the session token into props', () => {
  it.each(['pages/upload.tsx', 'pages/market/sell.tsx', 'pages/admin/index.tsx'])('%s', (relativePath) => {
    const source = readFileSync(join(process.cwd(), relativePath), 'utf8');
    expect(source).not.toMatch(/token:\s*session\.token/);
  });
});
