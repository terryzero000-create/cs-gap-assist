import type { ExperimentPlan } from '../../types';

interface ExperimentPlanCardProps {
  plan: ExperimentPlan;
}

export function ExperimentPlanCard({ plan }: ExperimentPlanCardProps) {
  return (
    <article className="plan-card">
      <header className="plan-card-header">
        <span>实验方案</span>
        <code>{plan.experiment_id.slice(0, 8)}</code>
      </header>
      <h3>{plan.objective}</h3>
      <div className="plan-grid">
        <section>
          <h4>数据集</h4>
          <ul>
            {plan.datasets.map((dataset) => (
              <li key={dataset}>{dataset}</li>
            ))}
          </ul>
        </section>
        <section>
          <h4>评价指标</h4>
          <ul>
            {plan.metrics.map((metric) => (
              <li key={metric}>{metric}</li>
            ))}
          </ul>
        </section>
        <section>
          <h4>基线方法</h4>
          <ul>
            {plan.baselines.map((baseline) => (
              <li key={baseline}>{baseline}</li>
            ))}
          </ul>
        </section>
        <section>
          <h4>风险</h4>
          <ul>
            {plan.risks.map((risk) => (
              <li key={risk}>{risk}</li>
            ))}
          </ul>
        </section>
      </div>
      <section className="steps">
        <h4>实验步骤</h4>
        <ol>
          {plan.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </section>
      <footer className="support-papers">
        {plan.support_refs.length > 0
          ? plan.support_refs.map((reference) => (
            <span key={reference.id}>
              {reference.is_available === false ? (
                <span className="evidence-unavailable">来源已删除 · {reference.title}</span>
              ) : reference.canonical_url.startsWith('http') ? (
                <a href={reference.canonical_url} rel="noreferrer" target="_blank">{reference.title}</a>
              ) : reference.title}
            </span>
          ))
          : plan.support_papers.map((paper) => <span key={paper}>{paper}</span>)}
      </footer>
    </article>
  );
}
