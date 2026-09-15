import { PCRM_ICONS } from '../lib/pcrmIcons';

// Vite glob: 動態載入 svc icons（raw svg content）
const svcModules = import.meta.glob('../assets/svc-icons/*.svg', {
  eager: true,
  query: '?raw',
  import: 'default',
}) as Record<string, string>;

// name -> svg inner content（strip <svg> wrapper + 將 hardcoded stroke 換成 currentColor）
const ICON_CACHE: Record<string, string> = {};

/* 2026-09-15 SAST（AppScan：dangerouslySetInnerHTML in SvcIcon）—
   呢個 innerHTML 唯一來源係 repo 內嘅 .svg 檔 + pcrmIcons.ts（冇用戶輸入路徑），
   但仍然喺 ingest 時清走 script / foreignObject / on* handler，令呢個 sink 就算
   將來有人改到 icon 來源都唔會變成 XSS 出口。 */
function stripDangerousSvg(svg: string): string {
  return svg
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<foreignObject[\s\S]*?<\/foreignObject>/gi, '')
    .replace(/\son[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, '')
    .replace(/(href|xlink:href)\s*=\s*("|')\s*javascript:[^"']*\2/gi, '');
}

const ingest = (name: string, raw: string) => {
  const inner = stripDangerousSvg(raw
    .replace(/<svg[^>]*>/, '')
    .replace(/<\/svg>/, '')
    .replace(/stroke="#2563EB"/g, 'stroke="currentColor"'));
  ICON_CACHE[name] = inner;
};
for (const [path, raw] of Object.entries(svcModules)) {
  const file = path.split('/').pop() ?? '';
  ingest(file.replace(/-blue\.svg$/, ''), raw);
}
// 靜態 import（pcrmIcons.ts）— 後處理，新 kit 覆蓋同名舊 icons
for (const [name, raw] of Object.entries(PCRM_ICONS)) {
  ingest(name, raw);
}

interface SvcIconProps {
  name: string;                       // kebab-case: 'zap', 'trash-2', 'calendar-days'
  size?: number | string;             // default 24（同 lucide-react 一致）
  strokeWidth?: number | string;      // default 1.75（SVC 統一）
  color?: string;                     // stroke 顏色（default currentColor，由 CSS/context 控制）
  className?: string;
  style?: React.CSSProperties;
  onClick?: (e: React.MouseEvent<SVGSVGElement>) => void;
  title?: string;
  'aria-hidden'?: boolean | 'true' | 'false';
}

export default function SvcIcon({
  name, size = 24, strokeWidth = 1.75, color,
  className, style, onClick, title, 'aria-hidden': ariaHidden,
}: SvcIconProps) {
  const inner = ICON_CACHE[name];
  if (!inner) return null;
  // title 透過 <title> 子元素注入（React SVGProps 並無 title attribute，呢個做法 type-safe）
  const html = title ? `<title>${title.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</title>` + inner : inner;
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={['svc-icon', className].filter(Boolean).join(' ')}
      style={style}
      onClick={onClick}
      color={color}
      aria-hidden={ariaHidden}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
