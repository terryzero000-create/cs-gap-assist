import { afterEach, expect, test, vi } from 'vitest';

import { setStoredApiKey, uploadPaper } from './client';

afterEach(() => {
  vi.unstubAllGlobals();
});

test('uploads asynchronously with an idempotency key and polls to ready', async () => {
  setStoredApiKey('secret');
  const task = {
    upload_id: 'upload-1',
    doc_id: 'doc-1',
    revision_id: 'revision-1',
    title: 'paper.pdf',
    status_url: '/api/v1/paper-uploads/upload-1',
    retryable: false,
    error_code: null,
    error: null,
    page_count: null,
    chunk_count: 0,
    warnings: [],
    warning_codes: [],
  };
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ ...task, status: 'received' }), {
        status: 202,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ ...task, status: 'ready', chunk_count: 3 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
  vi.stubGlobal('fetch', fetchMock);

  const result = await uploadPaper(
    new File(['%PDF-1.7 fixture'], 'paper.pdf', { type: 'application/pdf' }),
  );

  expect(result).toMatchObject({ doc_id: 'doc-1', chunk_count: 3 });
  const firstInit = fetchMock.mock.calls[0][1] as RequestInit;
  const firstHeaders = new Headers(firstInit.headers);
  expect(firstHeaders.get('Authorization')).toBe('Bearer secret');
  expect(firstHeaders.get('Idempotency-Key')).toBeTruthy();
  expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/paper-uploads/upload-1');
});
