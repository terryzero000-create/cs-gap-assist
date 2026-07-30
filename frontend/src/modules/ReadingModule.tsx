import type {
  ChangeEvent,
  ChangeEventHandler,
  Dispatch,
  FormEventHandler,
  SetStateAction,
} from 'react';

import { ReadingQA } from '../components/PaperUpload/ReadingQA';
import type {
  PaperUploadResponse,
  ReadingQAHistoryItem,
  ReadingQAResponse,
} from '../types';

interface ReadingModuleProps {
  answer: ReadingQAResponse | null;
  failedUploadId: string | null;
  history: ReadingQAHistoryItem[];
  isAsking: boolean;
  isUploading: boolean;
  onAsk: FormEventHandler<HTMLFormElement>;
  onClearHistory: () => void;
  onClearSelection: () => void;
  onRemove: (docId: string) => void;
  onReupload: (docId: string, event: ChangeEvent<HTMLInputElement>) => void;
  onRestoreHistory: (item: ReadingQAHistoryItem) => void;
  onRetry: () => void;
  onSelect: (docId: string, checked: boolean) => void;
  onSelectAll: () => void;
  onUpload: ChangeEventHandler<HTMLInputElement>;
  papers: PaperUploadResponse[];
  qaError: string | null;
  question: string;
  selectedDocIds: string[];
  setQuestion: Dispatch<SetStateAction<string>>;
  uploadError: string | null;
  uploadStage: string | null;
}

export function ReadingModule(props: ReadingModuleProps) {
  return (
    <section className="workspace" aria-label="论文问答工作区">
      <aside className="sidebar">
        <div className="panel-header">
          <h2>论文</h2>
          <span className="status-pill">已选 {props.selectedDocIds.length} 篇</span>
        </div>
        <label className="file-button full-width">
          {props.isUploading ? `处理中：${props.uploadStage ?? 'received'}` : '上传 PDF'}
          <input
            accept="application/pdf"
            disabled={props.isUploading}
            multiple
            onChange={props.onUpload}
            type="file"
          />
        </label>
        {props.uploadError ? <p className="error-banner" role="alert">{props.uploadError}</p> : null}
        {props.failedUploadId ? (
          <button
            className="secondary-button full-width"
            disabled={props.isUploading}
            onClick={props.onRetry}
            type="button"
          >
            重试上传
          </button>
        ) : null}
        <div className="selection-actions">
          <button className="secondary-button" onClick={props.onSelectAll} type="button">全选</button>
          <button className="secondary-button" onClick={props.onClearSelection} type="button">清空</button>
        </div>
        <ul className="paper-list">
          {props.papers.map((paper) => (
            <li className="paper-list-item" key={paper.doc_id}>
              <label className="paper-row">
                <input
                  checked={props.selectedDocIds.includes(paper.doc_id)}
                  disabled={paper.reupload_required}
                  onChange={(event) => props.onSelect(paper.doc_id, event.target.checked)}
                  type="checkbox"
                />
                <span>
                  <strong>{paper.title}</strong>
                  <small>{paper.chunk_count > 0 ? `${paper.chunk_count} 个片段` : '已在知识库'}</small>
                  {paper.reupload_required ? <small>需要重新上传原始 PDF</small> : null}
                </span>
              </label>
              {paper.reupload_required ? (
                <label className="file-button">
                  重新上传
                  <input
                    accept="application/pdf"
                    disabled={props.isUploading}
                    onChange={(event) => props.onReupload(paper.doc_id, event)}
                    type="file"
                  />
                </label>
              ) : null}
              <button className="link-button" onClick={() => props.onRemove(paper.doc_id)} type="button">
                移除
              </button>
              {paper.warnings.map((warning, index) => (
                <small className="paper-warning" key={`${paper.warning_codes[index]}:${warning}`}>
                  {paper.warning_codes[index] ?? 'UNCLASSIFIED_WARNING'} · {warning}
                </small>
              ))}
            </li>
          ))}
        </ul>
      </aside>
      <ReadingQA
        error={props.qaError}
        history={props.history}
        isAsking={props.isAsking}
        onAsk={props.onAsk}
        onClearHistory={props.onClearHistory}
        onRestoreHistory={props.onRestoreHistory}
        paperCount={props.papers.length}
        question={props.question}
        result={props.answer}
        selectedPaperCount={props.selectedDocIds.length}
        setQuestion={props.setQuestion}
      />
    </section>
  );
}
