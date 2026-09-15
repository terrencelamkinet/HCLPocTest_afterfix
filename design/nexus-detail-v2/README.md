# NEXUS Detail Page V2 — AI-Native Record Layout

重新設計 Company/Contact/Deal/Project/Task 等所有 Detail Page 嘅排版，解決現有純 Tab 列表「資訊扁平、要逐個 Tab 撳先見到重點」嘅問題。設計參考 Salesforce Lightning、HubSpot、Attio 三大業界標準,再加入 NEXUS 獨有嘅 AI-native 差異化功能。

## 檔案結構

```
nexus-detail-v2/
├── components/
│   ├── NexusDetailPageV2.tsx              ← 核心 Layout Component（Header/Highlight/AI Card/Tabs/Sidebar）
│   └── CompaniesDetailPageV2.example.tsx  ← 實際整合範例（沿用你現有 Tab components）
├── styles/
│   └── nexus-detail-v2.css                ← 完整樣式（延伸自 NEXUS Design Guide token）
├── preview/
│   ├── preview.html                       ← 可直接瀏覽器打開嘅 Before/After 對比 Demo
│   ├── compare-table.png                  ← 競品對比表截圖
│   ├── frame-1.png                        ← Before：現有純 Tab 列表排版
│   ├── frame-2.png                        ← After：Desktop 1280px 完整新排版
│   └── frame-3.png                        ← After：Mobile 375px 響應式排版
└── README.md
```

## 競品對比：業界標準 Record Page 設計語言

| 設計元素 | Salesforce Lightning | HubSpot | Attio | **NEXUS CRM（本次設計）** |
|---|---|---|---|---|
| 頁面結構 | Header + Related List 直向堆疊,需大量捲動 | 左側固定屬性,右側 Tab | Highlight Widget 橫列 + 側邊分組 + 主區 Tab | 融合 Attio 側邊分組 + Salesforce Highlight Panel + **AI Insight Card 置頂** |
| 關鍵指標 | 需另建 Dashboard/Component | 散落各處 | 頂部最多 6 個 Highlight Widget | Highlight Widget + **AI 自動判斷邊個指標最需要關注**(如逾期任務標紅) |
| AI 摘要 | Einstein Copilot 需手動觸發,另開對話窗 | Breeze Copilot 摘要要切去 Intelligence Tab | 暫無原生 AI 摘要 | **AI Insight Card 直接置頂**,一開 Record 即見摘要/風險/機會,唔使額外點擊 |
| 資料豐富化 | 需 Data Cloud/第三方整合 | Breeze Intelligence 200M+ 資料庫,一鍵 Enrich | 需 API 整合,非原生 | 沿用一鍵填寫/名片掃描,**側邊欄藍點標記 AI 填寫嘅欄位** |
| 時間軸 | Activity Timeline 需另加入頁面 | 時間軸整合 Email/Call/Meeting,體驗成熟 | Activity Tab 顯示關聯紀錄 | 統一 Timeline 融合 Task/Touchpoint/Note/**AI 偵測事件**(紫色邊框標記) |
| 關聯記錄 | Related List 表格,較呆板 | 側邊 Card 顯示 | Relationship Tab | Related Record Grid Card,hover 浮動效果 |
| Mobile 體驗 | 需另外設計 App,Web 版較弱 | 尚可但 Tab 密集 | 一般 | Sidebar 自動摺落主欄下方,Tab sticky,完全響應式 |

## 新排版核心結構(見 preview.html)

1. **Sticky Header** — Breadcrumb + Avatar + 公司名/人名 + Industry/Size/地區一行顯示 + Edit/Ask AI 按鈕
2. **Highlight Widget Row** — 6 個關鍵指標橫向排列(Open Deals、Pipeline Value、Contacts、Overdue Tasks、Last Touch、Health Score),逾期/風險自動標紅色箭頭
3. **AI Insight Card**(核心差異化)— 置頂顯示 AI 生成嘅客戶摘要,自動列出機會標籤(💡 升級機會)同風險標籤(⚠ 逾期任務),右上角顯示更新時間同手動刷新按鈕
4. **雙欄主體**:
   - 左側主欄:Tab 導覽(Overview/Timeline/Contacts/Deals/Projects/Tasks/Notes)+ 統一 Timeline 顯示所有活動,AI 偵測事件用紫色邊框圓點標記
   - 右側 Sidebar:分組欄位(General Info / Ownership / Related),AI 填寫嘅欄位有藍點標記,分組可摺疊
5. **Mobile 響應式** — Sidebar 自動摺落主欄下方,AI Insight Card 保留置頂,Highlight Widget 縮成 3 個最重要指標

## 如何將現有資料引入 AI(具體實作建議)

你目前 `CompanyDetailTabs.tsx`/`ContactDetailTabs.tsx` 已經有齊 Touchpoints、Notes、Tasks、Activities 呢啲原始資料,只需要加一個後端 endpoint 做 AI 摘要:

```
POST /api/v1/ai/entity-insight
Body: { entity_type: "company", entity_id: "xxx" }
Response: {
  summary: "...",
  tags: [{ label: "...", kind: "opportunity" | "risk" | "info" }],
  generatedAt: "2026-08-10T10:00:00Z"
}
```

後端邏輯:抽取該 entity 最近 30 日嘅 Touchpoints + Notes + Activities + 關聯 Deal/Project 狀態,組成 prompt 餵入 LLM,生成摘要同標籤。呢個 pattern 完全對應 Salesforce Einstein「Summarize Record」同 HubSpot Breeze Copilot 嘅做法,但 NEXUS 直接置頂顯示,體驗更快。

`useAIInsight` hook(已寫在 `NexusDetailPageV2.tsx`)負責 call 呢個 API,並支援手動 refresh。

## Timeline 嘅 AI 偵測事件

`UnifiedTimeline` component 支援 `aiDetected: true` 標記,用嚟顯示 AI 從會議記錄/名片掃描/Email 自動偵測到嘅事件(例如「AI 偵測:客戶提到想升級系統」)。實作時,建議喺你現有嘅 Touchpoint/Note 建立流程中,加一個背景 job 分析內容,自動生成呢類 Timeline Event 並存入資料庫,標記 `source: "ai_extracted"`。

## 整合步驟

1. 複製 `components/NexusDetailPageV2.tsx` 同 `styles/nexus-detail-v2.css` 入你嘅 `src/`
2. 喺入口檔案 import CSS
3. 參考 `CompaniesDetailPageV2.example.tsx`,將你現有嘅 `ContactsTab`/`DealsTab`/`ProjectsTab` 等 Tab component 原封不動放入 `tabs` prop 嘅 `render()` 內 —— **唔需要重寫呢啲 Tab component**,只需要換底層 Layout
4. 對 Contact/Deal/Project/Task 嘅 Detail Page 重複同一步驟,只需要調整 `highlights`、`sidebarSections`、`subline` 內容(呢啲 module 特有嘅欄位)
5. 後端新增 `/api/v1/ai/entity-insight` endpoint

## 下一步智能化建議

- **Health Score 演算法**:根據互動頻率、逾期任務數、Deal 進度自動計算 0-100 分,喺 Highlight Widget 顯示趨勢箭頭
- **AI 建議下一步行動**:喺 AI Insight Card 底部加一個「建議行動」按鈕,例如「發送跟進 Email」、「安排會議」,一click 自動建立 Task/Touchpoint
- **跨記錄關聯偵測**:AI 發現同一 Company 下多個 Contact 都提到同一個需求時,自動合併顯示為單一機會卡片
- **語音/文字輸入快速記錄**:Timeline 頂部加一個輸入框,講/打完直接生成 Touchpoint,AI 自動分類同摘要
