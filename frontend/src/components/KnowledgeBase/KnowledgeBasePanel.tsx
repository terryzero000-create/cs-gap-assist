interface KnowledgeBasePanelProps {
  paperCount: number;
  noteCount: number;
}

export function KnowledgeBasePanel({ paperCount, noteCount }: KnowledgeBasePanelProps) {
  return (
    <section>
      <h2>个人知识库</h2>
      <p>已收藏/上传论文：{paperCount}</p>
      <p>研究笔记：{noteCount}</p>
      <p>支持按论文、Gap历史、笔记和标签统一检索。</p>
    </section>
  );
}
