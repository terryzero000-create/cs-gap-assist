import type { ExperimentPlan } from '../../types';

interface ExperimentPlanCardProps {
  plan: ExperimentPlan;
}

export function ExperimentPlanCard({ plan }: ExperimentPlanCardProps) {
  return (
    <article className="plan-card">
      <header className="plan-card-header">
        <span>Experiment</span>
        <code>{plan.experiment_id.slice(0, 8)}</code>
      </header>
      <h3>{plan.objective}</h3>
      <div className="plan-grid">
        <section>
          <h4>Datasets</h4>
          <ul>
            {plan.datasets.map((dataset) => (
              <li key={dataset}>{dataset}</li>
            ))}
          </ul>
        </section>
        <section>
          <h4>Metrics</h4>
          <ul>
            {plan.metrics.map((metric) => (
              <li key={metric}>{metric}</li>
            ))}
          </ul>
        </section>
        <section>
          <h4>Baselines</h4>
          <ul>
            {plan.baselines.map((baseline) => (
              <li key={baseline}>{baseline}</li>
            ))}
          </ul>
        </section>
        <section>
          <h4>Risks</h4>
          <ul>
            {plan.risks.map((risk) => (
              <li key={risk}>{risk}</li>
            ))}
          </ul>
        </section>
      </div>
      <section className="steps">
        <h4>Steps</h4>
        <ol>
          {plan.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </section>
      <footer className="support-papers">
        {plan.support_papers.map((paper) => (
          <span key={paper}>{paper}</span>
        ))}
      </footer>
    </article>
  );
}
