#!/usr/bin/env python3
"""汉化质检: 记号、字形覆盖、排版宽度、漏译.

用法: python qa.py [--font build/stage/regularfont.ttf]
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import rftext  # noqa: E402

# 版面吃紧的位置: 这些字号下如果中文比英文宽出太多就有溢出风险
CHECK_SIZES = [('HUD', 17), ('菜单', 41)]
WIDTH_TOLERANCE = 1.15   # 中文宽度超过英文这个倍数就提示


def load_translations():
    tr = {}
    for n in ('ui_strings.tsv', 'subtitles.tsv'):
        tr.update(rftext._load_csv(os.path.join(ROOT, 'translation', n)))
    return tr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--font', default=os.path.join(
        ROOT, 'build', 'stage', 'regularfont.ttf'))
    args = ap.parse_args()

    tr = load_translations()
    en_dir = os.path.join(ROOT, 'work', 'en')
    entries = []
    for name in sorted(os.listdir(en_dir)):
        if rftext.kind_of(name) is None:
            continue
        for e in rftext.parse(os.path.join(en_dir, name)):
            entries.append((name, e))

    total = sum(1 for n, e in entries if e['en'].strip())
    done = sum(1 for n, e in entries if tr.get((n, e['key'])))
    print(f'进度: {done} / {total} 条有内容的文本已翻译\n')

    # --- 1. 记号 ---
    bad = []
    for n, e in entries:
        zh = tr.get((n, e['key']))
        if not zh:
            continue
        miss = [t for t in rftext.TOKEN_RE.findall(e['en']) if t not in zh]
        if miss:
            bad.append((n, e['key'], miss))
    print(f'[记号] 缺失 {len(bad)} 条')
    for n, k, m in bad[:10]:
        print(f'    {n} #{k} 缺 {m}')

    # --- 2. 漏译: 原文有字母, 译文却一个汉字都没有 ---
    suspects = []
    for n, e in entries:
        zh = tr.get((n, e['key']))
        if not zh or not any(c.isalpha() and ord(c) < 128 for c in e['en']):
            continue
        if not any('一' <= c <= '鿿' for c in zh):
            suspects.append((n, e['key'], e['en'][:40], zh[:40]))
    print(f'\n[漏译] 译文无汉字但原文有字母: {len(suspects)} 条')
    for s in suspects[:12]:
        print(f'    {s[0]} #{s[1]}  {s[2]!r} -> {s[3]!r}')

    # --- 3. 字形覆盖 ---
    if os.path.exists(args.font):
        from fontTools.ttLib import TTFont
        cmap = TTFont(args.font).getBestCmap()
        missing = {}
        for n, e in entries:
            zh = tr.get((n, e['key'])) or ''
            for c in zh:
                if ord(c) >= 0x80 and ord(c) not in cmap:
                    missing.setdefault(c, []).append(f'{n}#{e["key"]}')
        print(f'\n[字形] 字体缺失字符: {len(missing)} 个')
        for c, where in list(missing.items())[:15]:
            print(f'    {c!r} U+{ord(c):04X}  出现在 {where[0]} 等 {len(where)} 处')
    else:
        print(f'\n[字形] 跳过 (字体不存在: {args.font})')

    # --- 4. 排版宽度 ---
    try:
        from PIL import ImageFont
    except ImportError:
        print('\n[宽度] 跳过 (缺 PIL)')
        return 0
    if not os.path.exists(args.font):
        return 0
    off_font = '/tmp/af/regularfont.ttf'      # 官方英文字体, 用于对比
    print()
    for label, size in CHECK_SIZES:
        zh_f = ImageFont.truetype(args.font, size)
        en_f = ImageFont.truetype(off_font, size) if os.path.exists(off_font) else zh_f
        wide = []
        for n, e in entries:
            zh = tr.get((n, e['key']))
            if not zh or n != 'strings.tbl':
                continue
            if '\\n' in e['en'] or len(e['en']) > 40:
                continue          # 长文本本来就会换行, 不看
            try:
                w_en = en_f.getlength(e['en'])
                w_zh = zh_f.getlength(zh)
            except Exception:
                continue
            if w_en > 0 and w_zh / w_en > WIDTH_TOLERANCE:
                wide.append((w_zh / w_en, e['key'], e['en'], zh, w_en, w_zh))
        wide.sort(reverse=True)
        print(f'[宽度@{label} {size}px] 中文比英文宽 {WIDTH_TOLERANCE:.0%} 以上: {len(wide)} 条')
        for ratio, k, en, zh, we, wz in wide[:8]:
            print(f'    {ratio:4.2f}x  #{k:<4s} {en[:32]!r} ({we:.0f}px)'
                  f' -> {zh[:20]!r} ({wz:.0f}px)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
