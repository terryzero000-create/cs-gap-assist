import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import { App } from './App';

afterEach(() => {
  vi.unstubAllGlobals();
});

test('requires an API key and stores it only in sessionStorage', async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ papers: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
  vi.stubGlobal('fetch', fetchMock);
  const user = userEvent.setup();

  render(<App />);
  expect(screen.getByRole('heading', { name: '连接本地研究工作台' })).toBeInTheDocument();
  await user.type(screen.getByLabelText('API Key'), 'test-token');
  await user.click(screen.getByRole('button', { name: '进入工作台' }));

  expect(window.sessionStorage.getItem('cs-gap-assist-api-key')).toBe('test-token');
  expect(window.localStorage.getItem('cs-gap-assist-api-key')).toBeNull();
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  const init = fetchMock.mock.calls[0][1] as RequestInit;
  expect(new Headers(init.headers).get('Authorization')).toBe('Bearer test-token');
});

test('renders a structured backend error code without matching English text', async () => {
  window.sessionStorage.setItem('cs-gap-assist-api-key', 'test-token');
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: 'backend unavailable',
          code: 503,
          error_code: 'INDEX_NOT_READY',
          retryable: true,
          details: {},
        }),
        { status: 503, headers: { 'Content-Type': 'application/json' } },
      ),
    ),
  );

  render(<App />);

  expect(await screen.findByText(/INDEX_NOT_READY/)).toBeInTheDocument();
  expect(screen.getByText(/可稍后重试/)).toBeInTheDocument();
});
