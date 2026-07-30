import { KnowledgeBasePanel } from '../components/KnowledgeBase/KnowledgeBasePanel';

export function KnowledgeModule({
  onAskWithPaper,
}: {
  onAskWithPaper: (docId: string) => void | Promise<void>;
}) {
  return (
    <section className="citation-workspace" aria-label="知识库">
      <KnowledgeBasePanel onAskWithPaper={onAskWithPaper} />
    </section>
  );
}
