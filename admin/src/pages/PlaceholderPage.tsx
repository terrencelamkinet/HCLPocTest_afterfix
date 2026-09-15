export function PlaceholderPage({ title, onNav }: { title: string; onNav: (p: string) => void }) {
  return (
    <div className="panel" style={{ textAlign: 'center', padding: '60px 20px' }}>
      <div style={{ fontSize: 40 }}>🚧</div>
      <h2 style={{ marginTop: 10 }}>{title} — P2 開發中</h2>
      <div className="note" style={{ marginTop: 8 }}>此頁面需要新的後端端點（稽核／通知規則／平台設定）— 已列入待辦（SPEC v1）</div>
      <div style={{ marginTop: 16 }}>
        <button className="btn ghost" onClick={() => onNav('reports')}>← 返報表中心</button>
      </div>
    </div>
  )
}
