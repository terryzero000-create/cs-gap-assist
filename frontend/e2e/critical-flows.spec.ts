import { expect, test } from '@playwright/test';

const paper = {
  doc_id: 'doc-1',
  title: 'Grounded RAG Paper',
  created_at: '2026-07-30T00:00:00Z',
  is_favorite: false,
  tags: [],
  active_revision_id: 'revision-1',
  ingestion_status: 'ready',
  reupload_required: false,
};

async function unlock(page: import('@playwright/test').Page, papers = [paper]) {
  await page.route('**/api/v1/papers', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ papers }),
  }));
  await page.goto('/');
  await expect(page.getByText('Grounded RAG Paper')).toBeVisible();
}

test('async upload polls and exposes retry for a retryable failure', async ({ page }) => {
  await unlock(page);
  await page.route('**/api/v1/paper-uploads', (route) => route.fulfill({
    status: 202,
    contentType: 'application/json',
    body: JSON.stringify({
      upload_id: 'upload-1',
      doc_id: 'doc-2',
      revision_id: 'revision-2',
      title: 'new.pdf',
      status: 'received',
      status_url: '/api/v1/paper-uploads/upload-1',
      retryable: false,
      chunk_count: 0,
      warnings: [],
      warning_codes: [],
    }),
  }));
  await page.route('**/api/v1/paper-uploads/upload-1', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      upload_id: 'upload-1',
      doc_id: 'doc-2',
      revision_id: 'revision-2',
      title: 'new.pdf',
      status: 'failed',
      status_url: '/api/v1/paper-uploads/upload-1',
      retryable: true,
      error_code: 'OCR_REQUIRED',
      error: 'OCR dependency is unavailable.',
      chunk_count: 0,
      warnings: [],
      warning_codes: [],
    }),
  }));

  await page.locator('input[type=file]').first().setInputFiles({
    name: 'new.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.7 fixture'),
  });

  await expect(page.getByRole('alert')).toContainText('OCR_REQUIRED');
  await expect(page.getByRole('button', { name: '重试上传' })).toBeVisible();
});

test('QA and Research Plan use fake-backend grounded responses', async ({ page }) => {
  await unlock(page);
  await page.route('**/api/v1/reading/qa', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      answer: '该论文报告了漂移下的性能下降。[S1]',
      sources: [{
        source_id: 'S1',
        doc_id: 'doc-1',
        title: paper.title,
        page: 2,
        chunk_id: 'chunk-1',
        text: 'Evidence',
        score: 0.9,
      }],
      evidence_status: 'local_only',
      warnings: [],
      warning_codes: [],
    }),
  }));
  await page.getByRole('checkbox').first().check();
  await page.getByPlaceholder(/例如/).first().fill('论文发现了什么？');
  await page.getByRole('button', { name: '提问' }).click();
  await expect(page.getByText(/性能下降/)).toBeVisible();

  await page.getByRole('button', { name: /研究路线/ }).click();
  await page.route('**/api/v1/research-plan-agent/run', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      agent_steps: [],
      routes: [],
      final_cards: [{
        title: '漂移鲁棒性路线',
        background: '本地证据',
        research_gap: '长期评测不足',
        entry_point: '先复现',
        experiment_suggestion: '跨域评测',
        recommended_papers: ['local:doc-1:chunk-1'],
        recommended_refs: [{
          id: 'local:doc-1:chunk-1',
          title: paper.title,
          source: 'local',
          canonical_url: '/api/v1/knowledge/papers/doc-1#chunk-chunk-1',
          doc_id: 'doc-1',
          chunk_id: 'chunk-1',
          page: 2,
        }],
        risks: ['样本量'],
        next_action: '复现 baseline',
      }],
      evidence_status: 'local_only',
      warnings: [],
      warning_codes: [],
    }),
  }));
  await page.getByLabel('研究方向').fill('RAG 漂移鲁棒性');
  await page.getByRole('button', { name: '运行 Agent' }).click();
  await expect(page.getByText('漂移鲁棒性路线')).toBeVisible();
});
