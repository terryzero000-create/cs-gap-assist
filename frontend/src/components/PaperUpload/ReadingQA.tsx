import { useState } from 'react';
import type { Dispatch, FormEvent, ReactNode, SetStateAction } from 'react';

import type { ReadingQAHistoryItem, ReadingQAResponse } from '../../types';
import { EvidenceStatusBadge } from '../EvidenceStatusBadge';

interface ReadingQAProps {
  error: string | null;
  history: ReadingQAHistoryItem[];
  isAsking: boolean;
  onAsk: (event: FormEvent<HTMLFormElement>) => void;
  onClearHistory: () => void;
  onRestoreHistory: (item: ReadingQAHistoryItem) => void;
  paperCount: number;
  question: string;
  result: ReadingQAResponse | null;
  selectedPaperCount: number;
  setQuestion: Dispatch<SetStateAction<string>>;
}

function renderAnswerWithCitationLinks(answer: string, sourceCount: number): ReactNode[] {
  return answer.split(/(\[(\d+)\])/g).reduce<ReactNode[]>((parts, token, index, tokens) => {
    const citationNumber = Number(token.match(/^\[(\d+)\]$/)?.[1]);
    const isDuplicateCapture = index > 0 && tokens[index - 1] === `[${token}]`;
    if (isDuplicateCapture) {
      return parts;
    }
    if (citationNumber >= 1 && citationNumber <= sourceCount) {
      parts.push(
        <a className="citation-link" href={`#source-${citationNumber}`} key={`${token}-${index}`}>
          {token}
        </a>,
      );
      return parts;
    }
    if (token) {
      parts.push(token);
    }
    return parts;
  }, []);
}

function formatAnswerMarkdown(question: string, result: ReadingQAResponse): string {
  const sources = result.sources
    .map((source, index) => `${index + 1}. 第 ${source.page} 页，${source.chunk_id}\n\n${source.text}`)
    .join('\n\n');

  return `# 简牍论文问答\n\n## 问题\n\n${question}\n\n## 回答\n\n${result.answer}\n\n## 来源片段\n\n${sources || '无来源片段'}\n`;
}

function formatWarning(warning: string): string {
  if (warning.includes('Xfyun Spark embedding failed')) {
    return '';
  }
  if (warning.includes('Local bge-m3 embedding request failed')) {
    return '本地 bge-m3 暂不可用。请启动 Ollama 并运行 `ollama pull bge-m3`，以启用本地语义检索。';
  }
  if (warning.includes('mock embeddings') || warning.includes('mock vectors')) {
    return '当前使用本地测试向量，检索效果仅供开发验证。';
  }
  if (warning.includes('OPENAI_API_KEY missing')) {
    return '当前选择的 OpenAI 对话模型不可用；请配置相应密钥或切换到 DeepSeek。';
  }
  if (warning.includes('DEEPSEEK_API_KEY missing')) {
    return 'DeepSeek 当前不可用；系统只展示真实来源片段，不会生成研究结论。';
  }
  if (warning.includes('Synthetic mock chat')) {
    return '当前回答来自显式开发测试模型，不会作为可信结果持久化。';
  }
  return warning;
}

export function ReadingQA({
  error,
  history,
  isAsking,
  onAsk,
  onClearHistory,
  onRestoreHistory,
  paperCount,
  question,
  result,
  selectedPaperCount,
  setQuestion,
}: ReadingQAProps) {
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const canAsk = selectedPaperCount > 0 && question.trim().length > 0 && !isAsking;
  const selectionMessage = paperCount === 0 ? '请先上传 PDF' : selectedPaperCount > 0 ? `将检索 ${selectedPaperCount} 篇论文` : '请选择至少一篇论文';

  async function copyAnswer() {
    if (!result) {
      return;
    }
    await navigator.clipboard.writeText(formatAnswerMarkdown(question, result));
    setActionMessage('已复制回答');
  }

  function exportAnswer() {
    if (!result) {
      return;
    }
    const blob = new Blob([formatAnswerMarkdown(question, result)], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `jiandu-reading-qa-${Date.now()}.md`;
    link.click();
    URL.revokeObjectURL(url);
    setActionMessage('已导出 Markdown');
  }

  return (
    <section className="qa-panel">
      <form className="question-form" onSubmit={onAsk}>
        <label htmlFor="question">问题</label>
        <textarea
          id="question"
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="例如：这篇论文的方法解决了什么问题？"
          rows={5}
          value={question}
        />
        <div className="form-actions">
          <span>{selectionMessage}</span>
          <button disabled={!canAsk} type="submit">{isAsking ? '生成中...' : '提问'}</button>
        </div>
      </form>

      {error ? <p className="alert" role="alert">{error}</p> : null}

      <section className="answer-panel" aria-live="polite">
        <div className="section-heading">
          <h2>回答</h2>
          {result ? (
            <div className="answer-actions">
              <button className="secondary-button" onClick={copyAnswer} type="button">复制</button>
              <button className="secondary-button" onClick={exportAnswer} type="button">导出</button>
            </div>
          ) : null}
        </div>
        {result ? (
          <>
            {actionMessage ? <p className="action-message">{actionMessage}</p> : null}
            <EvidenceStatusBadge status={result.evidence_status} />
            <p className="answer-text">{renderAnswerWithCitationLinks(result.answer, result.sources.length)}</p>
            {Array.from(new Set(result.warnings.map(formatWarning).filter(Boolean))).map((warning) => (
              <p className="warning" key={warning}>{warning}</p>
            ))}
            <h3>来源片段</h3>
            <ol className="source-list">
              {result.sources.map((source, index) => (
                <li id={`source-${index + 1}`} key={source.chunk_id}>
                  <div className="source-meta">
                    <span>来源 {index + 1}</span>
                    <span>第 {source.page} 页</span>
                    <span>相关度 {source.score.toFixed(2)}</span>
                  </div>
                  <p>{source.text}</p>
                </li>
              ))}
            </ol>
          </>
        ) : (
          <p className="empty-state">回答和引用片段会显示在这里。</p>
        )}
      </section>

      <section className="history-panel">
        <div className="section-heading">
          <h2>问答历史</h2>
          <div className="history-heading-actions">
            <span>{history.length} 条</span>
            {history.length > 0 ? (
              <button className="secondary-button" onClick={onClearHistory} type="button">清空</button>
            ) : null}
          </div>
        </div>
        {history.length > 0 ? (
          <ol className="history-list">
            {history.map((item) => (
              <li key={item.id}>
                <button className="history-item" onClick={() => onRestoreHistory(item)} type="button">
                  <span className="history-question">{item.question}</span>
                  <span className="history-meta">
                    {item.createdAt} · {item.paperTitles.length} 篇论文 · {item.result.sources.length} 条来源
                  </span>
                </button>
              </li>
            ))}
          </ol>
        ) : (
          <p className="empty-state">本次会话的问题会保存在这里，方便回看和继续追问。</p>
        )}
      </section>
    </section>
  );
}
