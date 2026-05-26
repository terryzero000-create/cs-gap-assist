interface ExperimentPlanCardProps {
  objective: string;
  datasets: string[];
  metrics: string[];
  baselines: string[];
}

export function ExperimentPlanCard({ objective, datasets, metrics, baselines }: ExperimentPlanCardProps) {
  return (
    <article>
      <h3>{objective}</h3>
      <p>数据集：{datasets.join('、')}</p>
      <p>评估指标：{metrics.join('、')}</p>
      <p>对比项：{baselines.join('、')}</p>
    </article>
  );
}
