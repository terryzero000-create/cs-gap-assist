import type { ReadingQAResponse } from '../../types';

interface ReadingQAProps {
  result: ReadingQAResponse | null;
}

export function ReadingQA({ result }: ReadingQAProps) {
  if (!result) {
    return <p>上传PDF后，可以围绕全文提问，答案会附带来源段落。</p>;
  }
  return (
    <section>
      <h2>论文精读问答</h2>
      <p>{result.answer}</p>
      <ol>
        {result.sources.map((source) => (
          <li key={source.chunk_id}>
            第 {source.page} 页：{source.text}
          </li>
        ))}
      </ol>
    </section>
  );
}
