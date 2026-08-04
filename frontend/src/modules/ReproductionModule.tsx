import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';

import { ApiClientError, runReproductionAgent } from '../api/client';
import type {
  PaperRecord,
  ReproductionAgentResponse,
  ReproductionMode,
} from '../types';

const modes: ReproductionMode[] = ['standard', 'focused', 'template'];
const modeLabels: Record<ReproductionMode, string> = {
  standard: '标准复现',
  focused: '聚焦公式/算法',
  template: '模板优先',
};

function readableError(error: unknown): string {
  if (error instanceof ApiClientError) {
    return `无法运行复现实验室 Agent。（${error.errorCode}）${error.message}`;
  }
  return error instanceof Error ? error.message : '无法运行复现实验室 Agent。';
}

export function ReproductionModule({
  isLoadingPapers,
  onRefresh,
  papers,
}: {
  isLoadingPapers: boolean;
  onRefresh: () => Promise<void>;
  papers: PaperRecord[];
}) {
  const [selectedPaperId, setSelectedPaperId] = useState('');
  const [mode, setMode] = useState<ReproductionMode>('standard');
  const [requirement, setRequirement] = useState('请辅助我复现论文的主要实验。');
  const [result, setResult] = useState<ReproductionAgentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  useEffect(() => {
    setSelectedPaperId((current) => (
      current && papers.some((paper) => paper.doc_id === current)
        ? current
        : papers[0]?.doc_id || ''
    ));
  }, [papers]);

  async function run(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedPaperId) {
      setError('请先选择一篇已上传论文。');
      return;
    }
    setIsRunning(true);
    setError(null);
    setResult(null);
    try {
      setResult(await runReproductionAgent({
        paper_id: selectedPaperId,
        mode,
        user_requirement: requirement.trim() || '请辅助我复现论文的主要实验。',
      }));
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <section className="workspace" aria-label="复现实验室">
      <aside className="sidebar">
        <div className="panel-header">
          <h2>复现实验室</h2>
          <button className="secondary-button" type="button" onClick={() => void onRefresh()} disabled={isLoadingPapers}>
            {isLoadingPapers ? '加载中' : '刷新'}
          </button>
        </div>
        <form className="reproduction-form" onSubmit={(event) => void run(event)}>
          <label htmlFor="reproduction-paper">选择论文</label>
          <select
            id="reproduction-paper"
            value={selectedPaperId}
            onChange={(event) => setSelectedPaperId(event.target.value)}
            disabled={isLoadingPapers || papers.length === 0}
          >
            {papers.length === 0 ? <option value="">还没有上传论文</option> : null}
            {papers.map((paper) => <option value={paper.doc_id} key={paper.doc_id}>{paper.title}</option>)}
          </select>
          <label htmlFor="reproduction-mode">复现模式</label>
          <select id="reproduction-mode" value={mode} onChange={(event) => setMode(event.target.value as ReproductionMode)}>
            {modes.map((item) => <option value={item} key={item}>{modeLabels[item]}</option>)}
          </select>
          <label htmlFor="reproduction-requirement">复现需求</label>
          <textarea
            id="reproduction-requirement"
            value={requirement}
            onChange={(event) => setRequirement(event.target.value)}
            placeholder="例如：请整理主要实验的复现目标、数据集、指标和代码模板。"
          />
          <button type="submit" disabled={isRunning || !selectedPaperId}>
            {isRunning ? 'Agent 运行中' : '运行复现 Agent'}
          </button>
        </form>
        {!isLoadingPapers && papers.length === 0 ? <p className="muted">请先在论文问答或知识库中上传论文。</p> : null}
      </aside>
      <section className="analysis-panel" aria-label="复现实验室结果">
        {error ? <p className="error-banner">{error}</p> : null}
        {result?.warnings.length ? (
          <ul className="warning-list">
            {result.warnings.map((warning, index) => (
              <li key={`${result.warning_codes[index]}:${warning}`}>
                <strong>{result.warning_codes[index] ?? 'UNCLASSIFIED_WARNING'}</strong> · {warning}
              </li>
            ))}
          </ul>
        ) : null}
        <div className="agent-grid">
          <section className="summary-panel">
            <h2>Agent 执行过程</h2>
            {result ? (
              <ol className="agent-step-list">
                {result.agent_steps.map((step) => (
                  <li key={step.step_index}>
                    <strong>{step.step_index}. {step.tool_name}</strong>
                    <p>{step.thought}</p><small>{step.observation.summary}</small><em>{step.next_decision}</em>
                  </li>
                ))}
              </ol>
            ) : <p className="muted">运行后这里会显示工具调用、观察结果和下一步决策。</p>}
          </section>
          <section className="research-card">
            <h2>复现报告</h2>
            {result ? <ReportView result={result} /> : <p className="muted">报告会在 Agent 完成后生成。</p>}
          </section>
        </div>
      </section>
    </section>
  );
}

function ReportView({ result }: { result: ReproductionAgentResponse }) {
  const report = result.report;
  return (
    <div className="report-sections">
      <p>{report.goal_understanding}</p>
      <ReportList title="复现目标" items={report.reproduction_targets} />
      <ReportList title="数据集" items={report.datasets} />
      <ReportList title="指标" items={report.metrics} />
      <ReportList title="Baseline" items={report.baselines} />
      <ReportList title="公式/算法线索" items={report.formula_or_algorithm_notes} />
      <ReportList title="实施计划" items={report.implementation_plan} />
      <ReportList title="风险" items={report.risks} />
      <ReportList title="限制" items={report.limitations} />
      <ReportList title="不做承诺" items={report.non_claims} />
      {report.code_template ? <section><h3>代码模板</h3><pre>{report.code_template}</pre></section> : null}
      {report.simulation_template ? <section><h3>仿真模板</h3><pre>{report.simulation_template}</pre></section> : null}
    </div>
  );
}

function ReportList({ title, items }: { title: string; items: string[] }) {
  const visibleItems = items.length > 0 ? items : ['unknown'];
  return (
    <section>
      <h3>{title}</h3>
      <ul>{visibleItems.map((item) => <li key={item}>{formatReproductionField(item)}</li>)}</ul>
    </section>
  );
}

export function formatReproductionField(item: string): string {
  const normalized = item.trim();
  if (normalized.toLowerCase() === 'unknown') {
    return '论文上下文未提供';
  }
  if (normalized.toLowerCase().startsWith('unknown:')) {
    return `论文上下文未提供：${normalized.slice('unknown:'.length).trim()}`;
  }
  return item;
}
