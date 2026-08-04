import { render, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ExperimentPlanCard } from './ExperimentSuggest/ExperimentPlanCard';
import { GapList } from './GapAnalysis/GapList';
import type { EvidenceRef } from '../types';


const deletedEvidence: EvidenceRef = {
  source: 'local',
  id: 'local:deleted:chunk',
  title: 'deleted.pdf',
  canonical_url: '/api/v1/knowledge/papers/deleted#chunk-chunk',
  doc_id: 'deleted',
  chunk_id: 'chunk',
  page: 1,
  is_available: false,
  unavailable_reason: 'source_deleted',
};


describe('deleted evidence rendering', () => {
  it('marks deleted Gap evidence without creating a link', () => {
    const view = render(<GapList gaps={[{
      gap_id: 'gap',
      title: 'Historical gap',
      value_level: 'high',
      description: 'Retained history',
      evidence_papers: [deletedEvidence.id],
      evidence_refs: [deletedEvidence],
      trust_status: 'local_only',
      created_at: '2026-08-03T00:00:00Z',
    }]} />);

    const scoped = within(view.container);
    expect(scoped.getByText('来源已删除 · deleted.pdf')).toBeInTheDocument();
    expect(scoped.queryByRole('link', { name: 'deleted.pdf' })).not.toBeInTheDocument();
  });

  it('marks deleted experiment support without creating a link', () => {
    const view = render(<ExperimentPlanCard plan={{
      experiment_id: 'experiment',
      gap_id: 'gap',
      objective: 'Historical experiment',
      datasets: ['dataset'],
      metrics: ['metric'],
      baselines: ['baseline'],
      steps: ['run'],
      risks: ['source deleted'],
      support_papers: [deletedEvidence.id],
      support_refs: [deletedEvidence],
      trust_status: 'local_only',
    }} />);

    const scoped = within(view.container);
    expect(scoped.getByText('来源已删除 · deleted.pdf')).toBeInTheDocument();
    expect(scoped.queryByRole('link', { name: 'deleted.pdf' })).not.toBeInTheDocument();
  });
});
