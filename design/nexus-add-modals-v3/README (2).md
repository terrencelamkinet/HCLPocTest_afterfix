# NEXUS CRM — 5 個 Add Modal 完整重新設計

依照 `NEXUS-Design-Guide-2026-Parametric.md` 全數參數（字級、間距、色彩 Token、動畫曲線、觸控標準、Safe Area）重新設計 **New Company / New Contact / New Task / New Project / New Touchpoint**，並涵蓋 Desktop、iPad、iOS Mobile、Android Mobile 四種形態。

## 檔案結構

```
nexus-add-modals-v3/
├── components/
│   ├── NexusSmartAddModal.tsx    ← 統一 Modal component（5 個 module 共用一份邏輯）
│   └── add-modal-configs.ts      ← 5 個 module 的欄位定義
├── styles/
│   └── nexus-modal-tokens.css    ← 完整 Design Token + Modal/Button/Field 樣式
├── preview/
│   ├── preview.html              ← 互動 Demo（可直接瀏覽器打開）
│   └── section-1~4.png           ← 截圖：Company / Contact+Duplicate / Mobile iOS vs Android / Project+Touchpoint
└── README.md
```

## 為何用「一個 Modal component + 5 份 config」而非寫 5 份 Modal

原有 codebase（`GenericListPage.tsx`）已經係 config-driven 架構，`NexusSmartAddModal` 延續呢個模式：所有 module 共用同一套 AI 邏輯（一鍵填寫、名片掃描、Duplicate Detection、Loading/Thinking 狀態），差異只在 `add-modal-configs.ts` 入面嘅 fields 定義。日後新增第 6 個 module 只需要加一個 config，唔使再寫一份 Modal。

## 完全對照 Design Guide 嘅實作細節

| Design Guide 規範 | 本次實作 |
|---|---|
| Mobile Input 字體 ≥16px（防 iOS zoom）| `.nx-field input` 在 `<768px` 強制 16px，`≥1280px` 降為 14px |
| Touch Target Mobile ≥44×44px | 所有 button/input height 統一 44-48px，`.nx-modal-x` 40×40px（Desktop 可接受 24px 底線，Mobile 一律 44px）|
| Modal 圓角 16px | `--radius-modal: 16px`，Mobile Bottom Sheet 只有頂部圓角 `16px 16px 0 0` |
| Modal 開啟動畫 250ms spring | `cubic-bezier(0.16,1,0.3,1)`，關閉 180ms `cubic-bezier(0.4,0,1,1)` 加速離場 |
| Safe Area (iOS Home Indicator) | `padding-bottom: env(safe-area-max-inset-bottom, 36px)` 加落 Mobile Modal |
| Light/Dark 色彩 Token | 完整複製 Design Guide Section 7 兩組 token，用 `[data-theme]` 切換 |
| Button Hover/Active/Disabled | `filter: brightness(0.92)` hover、`scale(0.97)` active、`opacity:0.5` disabled，全部跟 Guide 數值 |
| 8px Grid 間距 | `--space-1` 至 `--space-16` 全套引入，Modal padding/gap 全部對齊 |
| Skeleton/Thinking 動畫 | 三點跳動 `1.2s ease-in-out`，Loader spin `0.8s linear` |

## iOS vs Android 差異設計（見 section-3.png）

| 元素 | iOS | Android |
|---|---|---|
| Bottom Sheet 圓角 | 20px | 16px |
| Drag Handle | 頂部置中橫條，圓潤 | 較窄，符合 Material 語言 |
| 按鈕排列 | 垂直堆疊，Primary 喺上（拇指易觸及） | 水平並排，Cancel 左/Create 右 |
| 按鈕文字 | Title Case（Cancel／Create Task）| 全大寫（CANCEL／CREATE），Material 慣例 |
| 按鈕圓角 | 8-10px | 4px（Material You 較方正） |
| Close 按鈕形狀 | 方形圓角 | 圓形（Material icon button 慣例） |
| Safe Area | Home Indicator 底部留白 36px | 手勢導覽列較窄，留白按 Android 系統值調整 |

## 5 個 Module 個別重點

- **New Company**：只有通用 AI 一鍵填寫（貼上公司簡介/網站文字），冇名片掃描（B2B 公司冇「名片」概念）
- **New Contact**：**唯一**有名片掃描嘅 module，額外加咗 **Duplicate Detection**——AI 填完 Email/Phone 後自動 fuzzy match 現有 contacts，發現 88% 以上相似度會彈出黃色提示條，避免建立重複記錄
- **New Task**：專門做咗 Mobile Bottom Sheet 展示（見 section-3），因為 Task 通常喺手機上快速新增
- **New Project**：AI 一鍵填寫支援貼上會議記錄，自動拆解 Priority/Deadline/Budget/Company 多個欄位
- **New Touchpoint**：支援貼上 WhatsApp/Email 對話內容，AI 自動生成 Summary 欄位

## 整合步驟

1. 複製 `components/` 同 `styles/` 兩個資料夾入 `src/`
2. 喺入口檔案 import `nexus-modal-tokens.css`
3. 喺 `GenericListPage.tsx` 或各自 Page 入面，用 `<NexusSmartAddModal config={companyAddConfig} .../>` 取代原本 inline modal（5 個 module 各自 import 對應 config）
4. 後端新增 2 個 endpoint（沿用之前一輪已定義嘅 `/api/v1/ai/smart-fill` 同 `/api/v1/ai/scan-name-card`），再加一個 `GET {apiPath}/duplicate-check?name=` 做 fuzzy match

## 下一步智能化建議

- **跨欄位一致性檢查**：AI 填寫 Task 嘅 Due Date 早於今日時，即時標紅提示
- **語音輸入**（Mobile）：新增錄音按鈕，Sales 開完會即刻口述建 Task/Touchpoint
- **AI 建議 Related 記錄**：New Task 時，AI 根據 Title 自動建議關聯邊個 Company/Project
- **草稿自動保存**：用戶貼咗文字但中途關閉 Modal，下次打開提示「繼續上次草稿？」
