import { EvidenceStatusBadge } from '../components/EvidenceStatusBadge';
import type { PaperRecord, ResearchPlanAgentResponse } from '../types';

interface ResearchPlanModuleProps {
  canRun: boolean;
  currentExperimentResult: string;
  error: string | null;
  isLoadingPapers: boolean;
  isRunning: boolean;
  onClearSelection: () => void;
  onRefresh: () => void;
  onRun: () => void;
  onSelectAll: () => void;
  onTogglePaper: (docId: string) => void;
  papers: PaperRecord[];
  researchDirection: string;
  result: ResearchPlanAgentResponse | null;
  selectedDocIds: string[];
  setCurrentExperimentResult: (value: string) => void;
  setResearchDirection: (value: string) => void;
}

export function ResearchPlanModule(props: ResearchPlanModuleProps) {
  return (
    <section className="workspace" aria-label="研究路线规划 Agent">
      <aside className="sidebar">
        <div className="panel-header">
          <h2>已选论文</h2>
          <button className="secondary-button" type="button" onClick={props.onRefresh} disabled={props.isLoadingPapers}>
            {props.isLoadingPapers ? '加载中' : '刷新'}
          </button>
        </div>
        <div className="selection-actions">
          <button className="secondary-button" type="button" onClick={props.onSelectAll}>全选</button>
          <button className="secondary-button" type="button" onClick={props.onClearSelection}>清空</button>
        </div>
        <div className="paper-list">
          {props.papers.length === 0 ? (
            <p className="muted">还没有上传论文。</p>
          ) : props.papers.map((paper) => (
            <label className="paper-row" key={paper.doc_id}>
              <input
                type="checkbox"
                checked={props.selectedDocIds.includes(paper.doc_id)}
                disabled={paper.reupload_required}
                onChange={() => props.onTogglePaper(paper.doc_id)}
              />
              <span>
                <strong>{paper.title}</strong>
                <small>
                  {paper.reupload_required
                    ? '需要重新上传原始 PDF'
                    : new Date(paper.created_at).toLocaleDateString('zh-CN')}
                </small>
              </span>
            </label>
          ))}
        </div>
      </aside>
      <section className="analysis-panel" aria-label="研究路线规划 Agent">
        <div className="research-plan-form">
          <label htmlFor="research-direction">研究方向</label>
          <textarea
            id="research-direction"
            value={props.researchDirection}
            onChange={(event) => props.setResearchDirection(event.target.value)}
            placeholder="例如：面向生产漂移场景的 RAG 鲁棒性评估"
          />
          <label htmlFor="experiment-result">当前实验结果（可选）</label>
          <textarea
            id="experiment-result"
            value={props.currentExperimentResult}
            onChange={(event) => props.setCurrentExperimentResult(event.target.value)}
            placeholder="例如：BM25 baseline 在跨领域测试集上 F1 明显下降"
          />
          <button type="button" onClick={props.onRun} disabled={!props.canRun}>
            {props.isRunning ? 'Agent 运行中' : '运行 Agent'}
          </button>
        </div>
        {props.error ? <p className="error-banner">{props.error}</p> : null}
        {props.result?.warnings.length ? (
          <ul className="warning-list">
            {props.result.warnings.map((warning, index) => (
              <li key={`${props.result?.warning_codes[index]}:${warning}`}>
                <strong>{props.result?.warning_codes[index] ?? 'UNCLASSIFIED_WARNING'}</strong> · {warning}
              </li>
            ))}
          </ul>
        ) : null}
        <EvidenceStatusBadge status={props.result?.evidence_status} />
        <div className="agent-grid">
          <section className="summary-panel">
            <h2>Agent 执行过程</h2>
            {props.result ? (
              <ol className="agent-step-list">
                {props.result.agent_steps.map((step) => (
                  <li key={step.step_index}>
                    <strong>{step.step_index}. {step.tool_name}</strong>
                    <p>{step.thought}</p>
                    <small>{step.observation}</small>
                    <em>{step.next_decision}</em>
                  </li>
                ))}
              </ol>
            ) : <p className="muted">运行后这里会显示工具调用、观察结果和下一步决策。</p>}
          </section>
          <section className="research-card-list">
            <h2>研究路线</h2>
            {props.result?.routes.length ? props.result.routes.map((route) => (
              <article className="route-card" key={route.gap.gap_id}>
                <div className="route-card-header">
                  <div><p className="eyebrow">Research Gap</p><h3>{route.gap.title}</h3></div>
                  <span className={`value-badge value-badge-${route.gap.value_level}`}>
                    {route.gap.value_level === 'high' ? '高价值' : '中价值'}
                  </span>
                </div>
                <p>{route.gap.description}</p>
                {route.experiments.map((experiment) => (
                  <section className="route-experiment" key={experiment.experiment_id}>
                    <h4>{experiment.objective}</h4>
                    <div className="plan-grid">
                      <section><h4>数据集</h4><ul>{experiment.datasets.map((item) => <li key={item}>{item}</li>)}</ul></section>
                      <section><h4>指标</h4><ul>{experiment.metrics.map((item) => <li key={item}>{item}</li>)}</ul></section>
                      <section><h4>Baseline</h4><ul>{experiment.baselines.map((item) => <li key={item}>{item}</li>)}</ul></section>
                      <section><h4>风险</h4><ul>{experiment.risks.map((item) => <li key={item}>{item}</li>)}</ul></section>
                    </div>
                    <section className="steps"><h4>实验步骤</h4><ol>{experiment.steps.map((item) => <li key={item}>{item}</li>)}</ol></section>
                    <div className="support-papers">{experiment.support_papers.map((item) => <span key={item}>{item}</span>)}</div>
                  </section>
                ))}
              </article>
            )) : <p className="muted">Agent 会在这里输出串联 Gap 与实验建议后的研究路线。</p>}
            <h2>课题执行卡</h2>
            {props.result ? props.result.final_cards.map((card) => (
              <article className="research-card" key={card.title}>
                <h3>{card.title}</h3>
                <p><strong>研究背景：</strong>{card.background}</p>
                <p><strong>Research Gap: </strong>{card.research_gap}</p>
                <p><strong>可行切入点：</strong>{card.entry_point}</p>
                <p><strong>实验建议：</strong>{card.experiment_suggestion}</p>
                <p><strong>下一步行动：</strong>{card.next_action}</p>
                <h4>推荐阅读论文</h4>
                <ul>
                  {card.recommended_refs.map((paper) => (
                    <li key={paper.id}>
                      <a href={paper.canonical_url} rel="noreferrer" target="_blank">{paper.title}</a>
                      <small>{paper.source} · {paper.id}</small>
                    </li>
                  ))}
                </ul>
                <h4>风险提示</h4>
                <ul>{card.risks.map((risk) => <li key={risk}>{risk}</li>)}</ul>
              </article>
            )) : <p className="muted">课题执行卡会在 Agent 完成后生成。</p>}
          </section>
        </div>
      </section>
    </section>
  );
}
