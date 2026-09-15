"""add_notes_i18n_keys.py — mobile Notes P0-5 / P1 需要嘅 i18n key。

只加 missing key（idempotent），並且只用「純文字插入」——唔會 reformat 成個 locale 檔。
支援多個 section（notes / editor / …）。執行：python3 scripts/add_notes_i18n_keys.py --apply
"""
import json
import re
import sys

ALL = {
    "en.json": {
        "notes": {
            "openNotebooks": "Open notebook list",
            "clearSearch": "Clear search",
            "unlink": "Unlink",
            "saving": "Saving…",
            "saved": "Saved",
            "offlineChanges": "Offline changes",
            "saveFailed": "Save failed",
            "noResultsTitle": "No matching notes",
            "emptyListTitle": "No notes yet",
            "more": "More",
            "moveTo": "Move to notebook",
        },
        "editor": {
            "contentLabel": "Note content",
            "insertBlock": "Insert block",
            "searchBlocks": "Search blocks…",
            "blockResults": "{{n}} blocks",
            "noBlocks": "No matching blocks",
            "blockGroupText": "Text",
            "blockGroupWork": "Work",
            "blockGroupMedia": "Media",
            "undo": "Undo",
            "redo": "Redo",
            "bold": "Bold",
            "italic": "Italic",
            "highlight": "Highlight",
            "link": "Link",
            "bulletList": "Bullet list",
            "taskList": "Checklist",
            "hideKeyboard": "Hide keyboard",
        },
    },
    "zh-TW.json": {
        "notes": {
            "openNotebooks": "開啟 Notebook 清單",
            "clearSearch": "清除搜尋",
            "unlink": "解除關聯",
            "saving": "儲存中…",
            "saved": "已儲存",
            "offlineChanges": "離線變更",
            "saveFailed": "儲存失敗",
            "noResultsTitle": "冇符合嘅筆記",
            "emptyListTitle": "未有筆記",
            "more": "更多",
            "moveTo": "移動到 Notebook",
        },
        "editor": {
            "contentLabel": "筆記內容",
            "insertBlock": "插入區塊",
            "searchBlocks": "搜尋區塊…",
            "blockResults": "{{n}} 個區塊",
            "noBlocks": "冇符合嘅區塊",
            "blockGroupText": "文字",
            "blockGroupWork": "工作",
            "blockGroupMedia": "媒體",
            "undo": "復原",
            "redo": "重做",
            "bold": "粗體",
            "italic": "斜體",
            "highlight": "螢光標示",
            "link": "連結",
            "bulletList": "項目列表",
            "taskList": "待辦清單",
            "hideKeyboard": "收起鍵盤",
        },
    },
}

LOCALES = "src/i18n/locales"


def object_span(s: str, key: str) -> tuple[int, int]:
    """搵**頂層**（depth 1）`key` 嘅 object span。

    ⚠️ 唔可以用 s.index('"notes"')：header section 入面都有一個 `"notes"`（導航標籤），
    會撞中錯嘅 object（2026-09-13 實際踩過，插錯 section）。editor 同理。
    """
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


def insert_keys(raw: str, section: str, pairs: dict[str, str]) -> str:
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
                print("REFUSE %s/%s：locale 冇呢個 section（唔敢自己開新 object）" % (name, section))
                rc = 1
                continue
            have = old[section]
            missing = {k: v for k, v in additions.items() if k not in have}
            if not missing:
                print("SKIP %s/%s：全部 key 已存在" % (name, section))
                continue
            candidate = insert_keys(raw, section, missing)
            reparsed = json.loads(candidate)  # 一定要 parse 得返先算數
            if reparsed.get(section) != {**have, **missing}:
                print("REFUSE %s/%s：插入之後內容唔一致" % (name, section))
                rc = 1
                continue
            others_ok = all(reparsed.get(k) == v for k, v in old.items() if k != section)
            if not others_ok:
                print("REFUSE %s/%s：其他 section 被改動" % (name, section))
                rc = 1
                continue
            print("OK %s/%s：+%d key（%s）" % (name, section, len(missing), ", ".join(missing)))
            raw = candidate
            old = reparsed
        if apply:
            open(path, "w", encoding="utf-8").write(raw)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
