import { useEffect, useMemo, useState } from 'react';

import { listGapHistory, suggestExperiments } from './api/client';
import { ExperimentPlanCard } from './components/ExperimentSuggest/ExperimentPlanCard';
import './style.css';
import type { ExperimentPlan, GapItem } from './types';

export function App() {
  const [gaps, setGaps] = useState<GapItem[]>([]);
  const [selectedGapId, setSelectedGapId] = useState('');
  const [manualGapId, setManualGapId] = useState('');
  const [topic, setTopic] = useState('');
  const [plans, setPlans] = useState<ExperimentPlan[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoadingGaps, setIsLoadingGaps] = useState(false);
  const [isSuggesting, setIsSuggesting] = useState(false);

  const selectedGap = useMemo(() => gaps.find((gap) => gap.gap_id === selectedGapId), [gaps, selectedGapId]);
  const activeGapId = selectedGap?.gap_id ?? manualGapId.trim();
  const canSuggest = activeGapId.length > 0 && !isSuggesting;

  useEffect(() => {
    void loadGaps();
  }, []);

  async function loadGaps(): Promise<void> {
    setIsLoadingGaps(true);
    setError(null);
    try {
      const result = await listGapHistory();
      setGaps(result.gaps);
      setWarnings(result.warnings);
      setSelectedGapId((current) => current || result.gaps[0]?.gap_id || '');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load gap history');
    } finally {
      setIsLoadingGaps(false);
    }
  }

  async function handleSuggest(): Promise<void> {
    if (!activeGapId) {
      return;
    }
    setIsSuggesting(true);
    setError(null);
    try {
      const trimmedTopic = topic.trim();
      const result = await suggestExperiments(activeGapId, trimmedTopic.length > 0 ? trimmedTopic : undefined);
      setPlans(result.experiments);
      setWarnings(result.warnings);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not suggest experiments');
    } finally {
      setIsSuggesting(false);
    }
  }

  function selectGap(gapId: string): void {
    setSelectedGapId(gapId);
    setManualGapId('');
    setTopic('');
  }

  function updateManualGapId(value: string): void {
    setManualGapId(value);
    if (value.trim()) {
      setSelectedGapId('');
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">CS Gap Assist</p>
          <h1>Experiment Suggestion Workbench</h1>
        </div>
        <button className="secondary-button" type="button" onClick={() => void loadGaps()} disabled={isLoadingGaps}>
          {isLoadingGaps ? 'Loading' : 'Refresh gaps'}
        </button>
      </header>

      <section className="workspace">
        <aside className="gap-panel" aria-label="Gap history">
          <div className="panel-heading">
            <h2>Stored gaps</h2>
            <span>{gaps.length}</span>
          </div>
          <div className="gap-list">
            {gaps.length === 0 ? (
              <p className="muted">No stored gaps found.</p>
            ) : (
              gaps.map((gap) => (
                <button
                  className={gap.gap_id === selectedGapId ? 'gap-row selected' : 'gap-row'}
                  key={gap.gap_id}
                  type="button"
                  onClick={() => selectGap(gap.gap_id)}
                >
                  <span className="value-level">{gap.value_level}</span>
                  <strong>{gap.title}</strong>
                  <small>{gap.description}</small>
                </button>
              ))
            )}
          </div>

          <div className="manual-gap">
            <label htmlFor="manual-gap-id">Gap ID</label>
            <input
              id="manual-gap-id"
              value={manualGapId}
              onChange={(event) => updateManualGapId(event.target.value)}
              placeholder="gap-123"
            />
          </div>
        </aside>

        <section className="suggestion-panel" aria-label="Experiment suggestions">
          <section className="selected-gap">
            <div>
              <p className="eyebrow">Selected gap</p>
              <h2>{selectedGap?.title ?? (activeGapId || 'No gap selected')}</h2>
              {selectedGap ? <p>{selectedGap.description}</p> : null}
            </div>
            {selectedGap ? <span className="value-badge">{selectedGap.value_level}</span> : null}
          </section>

          <div className="suggest-form">
            <label htmlFor="topic">Optional topic context</label>
            <textarea
              id="topic"
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              placeholder="Longitudinal RAG robustness under deployment drift"
            />
            <button type="button" onClick={() => void handleSuggest()} disabled={!canSuggest}>
              {isSuggesting ? 'Generating' : 'Suggest experiments'}
            </button>
          </div>

          {error ? <p className="error-banner">{error}</p> : null}
          {warnings.length > 0 ? (
            <ul className="warning-list">
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}

          <div className="plans">
            {plans.length === 0 ? (
              <p className="muted">Experiment plans will appear here.</p>
            ) : (
              plans.map((plan) => <ExperimentPlanCard key={plan.experiment_id} plan={plan} />)
            )}
          </div>
        </section>
      </section>
    </main>
  );
}
