import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ResearchPlanModule } from './ResearchPlanModule';
import type { ResearchPlanAgentResponse } from '../types';

const duplicateWarningResult: ResearchPlanAgentResponse = {
  agent_steps: [],
  routes: [],
  final_cards: [],
  evidence_status: 'local_only',
  warnings: ['arXiv returned no results.', 'arXiv returned no results.'],
  warning_codes: ['ARXIV_EMPTY', 'ARXIV_EMPTY'],
};

describe('ResearchPlanModule', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders repeated external warnings without duplicate React keys', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    render(
      <ResearchPlanModule
        canRun={false}
        currentExperimentResult=""
        error={null}
        isLoadingPapers={false}
        isRunning={false}
        onClearSelection={() => undefined}
        onRefresh={() => undefined}
        onRun={() => undefined}
        onSelectAll={() => undefined}
        onTogglePaper={() => undefined}
        papers={[]}
        researchDirection=""
        result={duplicateWarningResult}
        selectedDocIds={[]}
        setCurrentExperimentResult={() => undefined}
        setResearchDirection={() => undefined}
      />,
    );

    const warningItems = screen.getAllByRole('listitem').filter((item) => (
      item.textContent?.includes('arXiv returned no results.')
    ));
    expect(warningItems).toHaveLength(2);
    expect(consoleError).not.toHaveBeenCalledWith(expect.stringContaining('duplicate key'));
  });
});
