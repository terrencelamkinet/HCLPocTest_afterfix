import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSanitize from 'rehype-sanitize'
import type { Components } from 'react-markdown'

interface Props {
  content: string
  streaming?: boolean
}

export default function MarkdownMessage({ content, streaming }: Props) {
  const components: Partial<Components> = {
    table: ({ children }) => (
      <div className="md-table-wrapper">
        <div className="md-table-scroll">
          <table className="md-table">{children}</table>
        </div>
        {/* Mobile card list fallback — rendered via CSS media query swapping */}
        <div className="md-table-cards">
          {/* Cards are generated in JS as a fallback */}
        </div>
      </div>
    ),
    th: ({ children }) => <th className="md-th">{children}</th>,
    td: ({ children }) => <td className="md-td">{children}</td>,
    a: ({ href, children }) => (
      <a href={href} target="_blank" rel="noopener noreferrer nofollow">
        {children}
      </a>
    ),
    pre: ({ children }) => (
      <pre className="md-pre">{children}</pre>
    ),
    code: ({ className, children, ...props }) => {
      const isInline = !className
      return isInline ? (
        <code {...props}>{children}</code>
      ) : (
        <div className="md-code-block" style={{ position: 'relative' }}>
          <pre>
            <code className={className} {...props}>{children}</code>
          </pre>
          <button
            onClick={() => navigator.clipboard.writeText(String(children).replace(/\n$/, ''))}
            className="md-copy-btn"
            style={{
              position: 'absolute', top: 4, right: 4,
              padding: '2px 8px', fontSize: 11,
              border: '1px solid var(--color-border)',
              borderRadius: 4, background: 'var(--color-surface)',
              color: 'var(--color-text-muted)', cursor: 'pointer',
            }}
          >
            Copy
          </button>
        </div>
      )
    },
    img: ({ src, alt }) => (
      <img src={src} alt={alt || ''} loading="lazy" style={{ maxWidth: '100%', borderRadius: 6 }} />
    ),
  }

  return (
    <div className={`msg-md-body${streaming ? ' msg-md-streaming' : ''}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
