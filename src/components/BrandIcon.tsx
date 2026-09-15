/**
 * PenguinCRM BrandIcon — 品牌 monoline icons（由 brand kit PNG 裁切）
 *
 * Mapping 跟 DESIGN_GUIDE.md 第 3 節（每 set 16 個，順序由左上到右下）：
 *   set1 = 客戶與銷售流程   set2 = 系統與安全   set3 = 資料管理
 *   set4 = AI 與客服        set5 = 帳戶與工作流程
 */
const ICON_PATHS: Record<string, string> = {
  // set1 — 客戶與銷售流程
  contacts: '/assets/icons/cut/set1_icon01.png',   // 聯絡人卡片
  funnel: '/assets/icons/cut/set1_icon02.png',     // 銷售漏斗
  deal: '/assets/icons/cut/set1_icon03.png',       // 握手交易
  calendar: '/assets/icons/cut/set1_icon04.png',   // 日曆
  email: '/assets/icons/cut/set1_icon05.png',      // 電郵
  phone: '/assets/icons/cut/set1_icon06.png',      // 電話
  tasks: '/assets/icons/cut/set1_icon07.png',      // 任務清單
  dashboard: '/assets/icons/cut/set1_icon08.png',  // 儀表板
  target: '/assets/icons/cut/set1_icon09.png',     // 目標
  company: '/assets/icons/cut/set1_icon10.png',    // 公司
  invoice: '/assets/icons/cut/set1_icon11.png',    // 發票
  bell: '/assets/icons/cut/set1_icon12.png',       // 通知鈴
  automation: '/assets/icons/cut/set1_icon13.png', // 自動化齒輪
  ai: '/assets/icons/cut/set1_icon14.png',         // AI 助理
  cloud: '/assets/icons/cut/set1_icon15.png',      // 雲端同步
  search: '/assets/icons/cut/set1_icon16.png',     // 搜尋
  // set2 — 系統與安全
  settings: '/assets/icons/cut/set2_icon01.png',   // 設定
  team: '/assets/icons/cut/set2_icon02.png',       // 團隊
  security: '/assets/icons/cut/set2_icon03.png',   // 安全鎖
  report: '/assets/icons/cut/set2_icon04.png',     // 報表
  filter: '/assets/icons/cut/set2_icon05.png',     // 篩選
  tag: '/assets/icons/cut/set2_icon06.png',        // 標籤
  rating: '/assets/icons/cut/set2_icon07.png',     // 評分
  chat: '/assets/icons/cut/set2_icon08.png',       // 對話
  folder: '/assets/icons/cut/set2_icon09.png',     // 資料夾
  upload: '/assets/icons/cut/set2_icon10.png',     // 上傳下載
  link: '/assets/icons/cut/set2_icon11.png',       // 連結
  map: '/assets/icons/cut/set2_icon12.png',        // 地圖
  wallet: '/assets/icons/cut/set2_icon13.png',     // 錢包
  clock: '/assets/icons/cut/set2_icon14.png',      // 時鐘
  video: '/assets/icons/cut/set2_icon15.png',      // 視像會議
  globe: '/assets/icons/cut/set2_icon16.png',      // 地球
  // set3 — 資料管理
  add: '/assets/icons/cut/set3_icon01.png',        // 新增
  import: '/assets/icons/cut/set3_icon02.png',     // 匯出匯入
  sort: '/assets/icons/cut/set3_icon03.png',       // 排序
  edit: '/assets/icons/cut/set3_icon04.png',       // 編輯刪除
  attachment: '/assets/icons/cut/set3_icon05.png', // 附件
  print: '/assets/icons/cut/set3_icon06.png',      // 列印
  share: '/assets/icons/cut/set3_icon07.png',      // 分享
  sync: '/assets/icons/cut/set3_icon08.png',       // 同步
  lock: '/assets/icons/cut/set3_icon09.png',       // 鎖
  chart: '/assets/icons/cut/set3_icon10.png',      // 圖表
  satisfaction: '/assets/icons/cut/set3_icon11.png', // 滿意度
  priority: '/assets/icons/cut/set3_icon12.png',   // 優先級
  alarm: '/assets/icons/cut/set3_icon13.png',      // 提醒鬧鐘
  // set4 — AI 與客服
  aiBrain: '/assets/icons/cut/set4_icon01.png',    // AI 大腦
  robot: '/assets/icons/cut/set4_icon02.png',      // 機械人助理
  voice: '/assets/icons/cut/set4_icon03.png',      // 語音
  knowledge: '/assets/icons/cut/set4_icon04.png',  // 知識庫
  faq: '/assets/icons/cut/set4_icon05.png',        // FAQ
  headset: '/assets/icons/cut/set4_icon06.png',    // 客服耳機
  livechat: '/assets/icons/cut/set4_icon07.png',   // 即時對話
  review: '/assets/icons/cut/set4_icon08.png',     // 評論
  recommend: '/assets/icons/cut/set4_icon09.png',  // 推薦
  megaphone: '/assets/icons/cut/set4_icon10.png',  // 行銷喇叭
  rocket: '/assets/icons/cut/set4_icon11.png',     // 火箭
  social: '/assets/icons/cut/set4_icon12.png',     // 社交分享
  qr: '/assets/icons/cut/set4_icon13.png',         // QR code
  mobile: '/assets/icons/cut/set4_icon14.png',     // 手機
  desktop: '/assets/icons/cut/set4_icon15.png',    // 電腦
  // set5 — 帳戶與工作流程
  login: '/assets/icons/cut/set5_icon01.png',      // 登入
  logout: '/assets/icons/cut/set5_icon02.png',     // 登出
  mfa: '/assets/icons/cut/set5_icon03.png',        // 雙重驗證
  database: '/assets/icons/cut/set5_icon04.png',   // 資料庫
  api: '/assets/icons/cut/set5_icon05.png',        // API 插頭
  puzzle: '/assets/icons/cut/set5_icon06.png',     // 整合拼圖
  workflow: '/assets/icons/cut/set5_icon07.png',   // 流程圖
  kanban: '/assets/icons/cut/set5_icon08.png',     // Kanban 板
  gantt: '/assets/icons/cut/set5_icon09.png',      // Gantt 圖
  budget: '/assets/icons/cut/set5_icon10.png',     // 預算
  currency: '/assets/icons/cut/set5_icon11.png',   // 匯率
  discount: '/assets/icons/cut/set5_icon12.png',   // 折扣
  renew: '/assets/icons/cut/set5_icon13.png',      // 續約
  contract: '/assets/icons/cut/set5_icon14.png',   // 合約
  meeting: '/assets/icons/cut/set5_icon15.png',    // 會議
  presentation: '/assets/icons/cut/set5_icon16.png', // 簡報
}

export function BrandIcon({ name, size = 18, className = '' }: {
  name: string
  size?: number
  className?: string
}) {
  const src = ICON_PATHS[name]
  if (!src) return null
  return (
    <img
      src={src}
      alt=""
      width={size}
      height={size}
      className={`pcrm-brand-icon ${className}`}
      style={{ width: size, height: size, objectFit: 'contain' }}
      loading="lazy"
    />
  )
}

export const BRAND_ICON_NAMES = Object.keys(ICON_PATHS)
export default BrandIcon
