export interface SlashItem {
  key: string
  label: string
  icon: string
}

interface Props {
  menuType: 'slash' | 'mention' | null
  menuIndex: number
  menuQuery: string
  slashCommands: SlashItem[]
  mentionResults: { id: string; label: string; type: string; sub: string }[]
  onSelect: (type: 'slash' | 'mention', item: any) => void
  onHover: (index: number) => void
}

export default function SlashMentionMenu({ menuType, menuIndex, menuQuery, slashCommands, mentionResults, onSelect, onHover }: Props) {
  if (!menuType) return null

  return (
    <div style={{
      position: 'absolute', bottom: '100%', left: 14, right: 14,
      maxHeight: 200, overflowY: 'auto',
      background: 'var(--color-surface-2)',
      border: '1px solid var(--color-border)',
      borderRadius: 'var(--radius-md) var(--radius-md) 0 0',
      boxShadow: '0 -4px 12px rgba(0,0,0,0.1)',
      zIndex: 200, marginBottom: 4,
      animation: 'fadeUp 150ms var(--ease-out) both',
    }}>
      {menuType === 'slash' ? (
        slashCommands.filter(c => c.key.includes(menuQuery)).map((cmd, i) => (
          <div key={cmd.key}
            onClick={() => onSelect('slash', cmd)}
            onMouseEnter={() => onHover(i)}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '8px 12px', cursor: 'pointer', fontSize: 12.5,
              background: i === menuIndex ? 'var(--color-surface-offset)' : 'transparent',
              color: 'var(--color-text)',
              borderBottom: '1px solid var(--color-divider)',
              transition: 'background var(--transition-interactive)',
            }}
          >
            <span style={{ fontSize: 14 }}>{cmd.icon}</span>
            <span style={{ fontWeight: 500 }}>/{cmd.key}</span>
            <span style={{ marginLeft: 'auto', color: 'var(--color-text-faint)', fontSize: 11 }}>{cmd.label}</span>
          </div>
        ))
      ) : (
        mentionResults.length === 0 ? (
          <div style={{ padding: '10px 12px', fontSize: 12, color: 'var(--color-text-faint)' }}>
            Type to search contacts, companies, deals…
          </div>
        ) : (
          mentionResults.map((item, i) => (
            <div key={`${item.type}-${item.id}`}
              onClick={() => onSelect('mention', item)}
              onMouseEnter={() => onHover(i)}
              style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '8px 12px', cursor: 'pointer', fontSize: 12.5,
                background: i === menuIndex ? 'var(--color-surface-offset)' : 'transparent',
                color: 'var(--color-text)',
                borderBottom: '1px solid var(--color-divider)',
                transition: 'background var(--transition-interactive)',
              }}
            >
              <span style={{
                width: 20, height: 20, borderRadius: 4, fontSize: 10, fontWeight: 700,
                display: 'grid', placeItems: 'center', flexShrink: 0,
                background: item.type === 'contact' ? 'var(--color-blue)' : item.type === 'company' ? 'var(--color-purple)' : 'var(--color-primary)',
                color: '#fff', textTransform: 'uppercase',
              }}>{item.type[0]}</span>
              <span style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.label}</span>
              {item.sub && <span style={{ marginLeft: 'auto', color: 'var(--color-text-faint)', fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 120 }}>{item.sub}</span>}
            </div>
          ))
        )
      )}
    </div>
  )
}
