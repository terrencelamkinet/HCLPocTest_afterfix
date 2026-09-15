"""add_editor_i18n_keys.py — t12：NexusEditor 硬編中文 → i18n 需要嘅 key（39 個）。

跟 add_notes_i18n_keys.py 同一套做法：
  • 只加 missing key（idempotent）
  • **純文字插入**，唔 reformat 成個 locale 檔（避免 80KB 全檔 diff）
  • 插完一定 json.loads 返嚟核對 section 內容 + 其他 section 冇被動
執行：python3 scripts/add_editor_i18n_keys.py --apply
"""
import json
import re
import sys

ALL = {
    "en.json": {
        "editor": {
            # AI actions
            "aiImprove": "Improve writing",
            "aiShorten": "Shorten",
            "aiExpand": "Expand",
            "aiTranslate": "Translate to English",
            "aiFix": "Fix grammar",
            "aiSummarize": "Summarize",
            # highlight 色名
            "hlYellow": "Yellow",
            "hlOrange": "Orange",
            "hlGreen": "Green",
            "hlBlue": "Blue",
            "hlPink": "Pink",
            "hlPurple": "Purple",
            "hlCyan": "Cyan",
            "highlightNamed": "Highlight {{name}}",
            "customColorNamed": "Custom {{hex}}",
            # block 操作 toast
            "blockMovedUp": "Block moved up",
            "blockMovedDown": "Block moved down",
            "blockCopied": "Block copied",
            "blockLinkCopied": "Block link copied",
            # 上載 / AI
            "uploadFailed": "Upload failed",
            "uploadDone": "Uploaded",
            "attachment": "Attachment",
            "audioMemo": "Voice memo",
            "aiEditDone": "AI edit applied",
            "aiRequestFailed": "AI request failed — please try again",
            "selectTextFirst": "Select some text first",
            # 儲存狀態 + 字數
            "saveSaving": "Saving…",
            "saveSaved": "Saved",
            "saveError": "Save failed, retrying…",
            "saveReady": "Ready",
            "wordCount": "{{words}} words · {{min}} min read",
            # slash menu / block sheet 標籤
            "slashH1": "Heading 1",
            "slashH2": "Heading 2",
            "slashOrdered": "Numbered list",
            "slashQuote": "Quote",
            "slashTable": "Table",
            "slashImage": "Image",
            "slashVideo": "Video",
            "slashAudio": "Audio",
            # slash menu 其餘項目（第二部分：SlashCommand.ts 嘅 live 選單）
            "slashH3": "Heading 3",
            "slashDivider": "Divider",
            "slashImageUpload": "Upload image",
            "slashImageUrl": "Image from URL",
            "slashCode": "Code block",
            "slashAiContinue": "Continue with AI",
            "slashAiSummarize": "AI summary",
            "slashSubAiContinue": "Continue with AI",
            "slashSubAiSummarize": "Summarise the content above",
            "slashGroupBasic": "Basic",
            "slashGroupAdvanced": "Advanced",
            "slashGroupAi": "AI",
            "imageUrlPrompt": "Image URL:",
        },
    },
    "zh-TW.json": {
        "editor": {
            "aiImprove": "改善寫作",
            "aiShorten": "精簡內容",
            "aiExpand": "擴充內容",
            "aiTranslate": "翻譯做英文",
            "aiFix": "修正文法",
            "aiSummarize": "生成摘要",
            "hlYellow": "黃",
            "hlOrange": "橙",
            "hlGreen": "綠",
            "hlBlue": "藍",
            "hlPink": "粉紅",
            "hlPurple": "紫",
            "hlCyan": "青",
            "highlightNamed": "Highlight {{name}}",
            "customColorNamed": "自訂 {{hex}}",
            "blockMovedUp": "區塊已上移",
            "blockMovedDown": "區塊已下移",
            "blockCopied": "已複製區塊",
            "blockLinkCopied": "已複製區塊連結",
            "uploadFailed": "上載失敗",
            "uploadDone": "已上載",
            "attachment": "附件",
            "audioMemo": "語音備忘",
            "aiEditDone": "AI 已完成編輯",
            "aiRequestFailed": "AI 請求失敗，請重試",
            "selectTextFirst": "請先選取文字",
            "saveSaving": "正在儲存…",
            "saveSaved": "已儲存",
            "saveError": "儲存失敗，重試中…",
            "saveReady": "準備就緒",
            "wordCount": "{{words}} 字 · {{min}} 分鐘閱讀",
            "slashH1": "大標題",
            "slashH2": "中標題",
            "slashOrdered": "編號列表",
            "slashQuote": "引言",
            "slashTable": "表格",
            "slashImage": "圖片",
            "slashVideo": "影片",
            "slashAudio": "語音",
            "slashH3": "小標題",
            "slashDivider": "分隔線",
            "slashImageUpload": "圖片上載",
            "slashImageUrl": "圖片連結",
            "slashCode": "程式碼區塊",
            "slashAiContinue": "AI 續寫",
            "slashAiSummarize": "AI 摘要",
            "slashSubAiContinue": "由 AI 接續內容",
            "slashSubAiSummarize": "為以上內容生成摘要",
            "slashGroupBasic": "基本",
            "slashGroupAdvanced": "進階",
            "slashGroupAi": "AI",
            "imageUrlPrompt": "圖片網址 (URL)：",
        },
    },
}

LOCALES = "src/i18n/locales"


def object_span(s: str, key: str) -> tuple:
    """搵頂層（depth 1）`key` 嘅 object span（唔可以用 s.index，會撞中同名 sub-key）。"""
    depth = 0
    i = 0
    while i < len(s):
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == '"' and depth == 1:
            j = s.index('"', i + 1)
            if s[i + 1:j] == key:
                b = s.index("{", j)
                d = 0
                for k in range(b, len(s)):
                    if s[k] == "{":
                        d += 1
                    elif s[k] == "}":
                        d -= 1
                        if d == 0:
                            return b, k
            i = j
        i += 1
    raise KeyError(key)


def insert_keys(raw: str, section: str, pairs: dict) -> str:
    b, j = object_span(raw, section)
    inner = raw[b + 1:j]
    m = re.search(r'\n([ \t]+)"', inner)
    if not m:
        raise ValueError("搵唔到 %s object 嘅縮排" % section)
    indent = m.group(1)
    close_indent = indent[:-2] if len(indent) >= 2 else ""
    body = inner.rstrip()
    head = body + ("" if body.endswith(",") else ",")
    items = ",\n".join('%s"%s": %s' % (indent, k, json.dumps(v, ensure_ascii=False)) for k, v in pairs.items())
    return raw[:b + 1] + head + "\n" + items + "\n" + close_indent + raw[j:]


def main() -> int:
    apply = "--apply" in sys.argv
    rc = 0
    for name, sections in ALL.items():
        path = "%s/%s" % (LOCALES, name)
        raw = open(path, encoding="utf-8").read()
        old = json.loads(raw)
        for section, additions in sections.items():
            if section not in old:
                print("REFUSE %s/%s：locale 冇呢個 section" % (name, section))
                rc = 1
                continue
            have = old[section]
            missing = {k: v for k, v in additions.items() if k not in have}
            if not missing:
                print("SKIP %s/%s：全部 key 已存在" % (name, section))
                continue
            candidate = insert_keys(raw, section, missing)
            reparsed = json.loads(candidate)
            if reparsed.get(section) != {**have, **missing}:
                print("REFUSE %s/%s：插入之後內容唔一致" % (name, section))
                rc = 1
                continue
            others_ok = all(reparsed.get(k) == v for k, v in old.items() if k != section)
            if not others_ok:
                print("REFUSE %s/%s：其他 section 被改動" % (name, section))
                rc = 1
                continue
            print("OK %s/%s：+%d key" % (name, section, len(missing)))
            raw = candidate
            old = reparsed
        if apply:
            open(path, "w", encoding="utf-8").write(raw)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
