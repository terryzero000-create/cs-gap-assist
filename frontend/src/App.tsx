import './style.css';

const modules = ['论文精读问答', 'Research Gap分析', '文献支撑实验建议', '引用演化图谱', '个人知识库'];

export function App() {
  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">CS Gap Assist</p>
        <h1>从论文精读到实验建议的一站式科研Gap助手</h1>
        <p>上传论文、检索新文献、生成有证据支撑的研究空白，并把知识沉淀到个人知识库。</p>
      </section>
      <section className="grid">
        {modules.map((item) => (
          <article className="card" key={item}>{item}</article>
        ))}
      </section>
    </main>
  );
}