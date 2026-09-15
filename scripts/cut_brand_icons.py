"""PenguinCRM brand kit — 將 simple icon set 網格（1408x768, 4x4）裁切做獨立 icon PNG。

每格 352x192，內容係深藍 line icon 居中。流程：
1. 4x4 均分裁格
2. 白色背景 → 透明（threshold）
3. 自動 trim 邊界（non-white bbox）
4. 輸出正方形（padding 8px）透明背景 PNG → public/assets/icons/cut/
"""
from PIL import Image
import os, sys

SRC_DIR = 'public/assets/icons/simple'
OUT_DIR = 'public/assets/icons/cut'
GRID = 4  # 4x4
CELL_W, CELL_H = 352, 192
PAD = 8

os.makedirs(OUT_DIR, exist_ok=True)

def trim_to_icon(img: Image.Image) -> Image.Image | None:
    """白色背景 → alpha，trim 到 icon bbox，回傳正方形 icon（透明背景）。"""
    rgba = img.convert('RGBA')
    px = rgba.load()
    w, h = rgba.size
    # 白底 threshold：RGB 全部 > 235 當背景
    bbox = None
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if r < 232 or g < 232 or b < 232:
                if bbox is None:
                    bbox = [x, y, x, y]
                else:
                    bbox[0] = min(bbox[0], x); bbox[1] = min(bbox[1], y)
                    bbox[2] = max(bbox[2], x); bbox[3] = max(bbox[3], y)
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    # 白 → 透明
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    opx = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if r >= 232 and g >= 232 and b >= 232:
                continue  # 透明
            # 邊緣淡化（anti-aliasing 像素）
            alpha = 255
            if r >= 200 and g >= 200 and b >= 200:
                alpha = max(0, 255 - int((r + g + b) / 3 - 200) * 6)
            opx[x, y] = (r, g, b, alpha)
    crop = out.crop((x0, y0, x1 + 1, y1 + 1))
    # 正方形化：長邊 + 兩邊 padding
    side = max(crop.size) + PAD * 2
    sq = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    sq.paste(crop, ((side - crop.size[0]) // 2, (side - crop.size[1]) // 2), crop)
    return sq

count = 0
for set_i in range(1, 6):
    src = f'{SRC_DIR}/simple_icon_set_{set_i}.png'
    img = Image.open(src)
    for row in range(GRID):
        for col in range(GRID):
            cell = img.crop((col * CELL_W, row * CELL_H, (col + 1) * CELL_W, (row + 1) * CELL_H))
            icon = trim_to_icon(cell)
            if icon is None:
                print(f'set{set_i} r{row}c{col}: EMPTY')
                continue
            idx = row * GRID + col + 1
            out = f'{OUT_DIR}/set{set_i}_icon{idx:02d}.png'
            icon.save(out)
            count += 1

print(f'DONE: {count} icons → {OUT_DIR}')
