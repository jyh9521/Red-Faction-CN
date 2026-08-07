#!/usr/bin/env python3
"""一键构建完整汉化包.

把三样东西打进同一个 client_mods vpp:
  1. 回填了译文的 .tbl
  2. 子集化的中文字体 (regularfont.ttf / boldfont.ttf)
  3. alpine_extra_charset.txt —— 引擎补丁靠它决定栅格化哪些字形

**字符集是从译文里扫出来的**, 不是拍脑袋定的。译文里出现过的字一定在字体里,
没出现过的字一个都不多收 —— 这样体积最小, 图集显存也最省。

用法:
  python build_all.py [--scale 1.5] [--name rfcn] [--install]

--install 会直接复制到 <游戏目录>\\client_mods\\
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import build_font  # noqa: E402
import rftext  # noqa: E402
import vpp  # noqa: E402

GAME_DIR = os.path.dirname(ROOT)


def read_npc_lines(tr_dir):
    """读 npc_lines.tsv, 返回 [(wav, 要显示的文字)].

    译文为空时回落到英文原文 —— 这样机制做好就能先用英文验证链路,
    不用等 364 条全部翻完。标了「非语言」的行(纯尖叫)直接跳过。
    """
    path = os.path.join(tr_dir, 'npc_lines.tsv')
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding='utf-8', newline='') as f:
        next(f, None)
        for line in f:
            cols = line.rstrip('\n').rstrip('\r').split('\t')
            if len(cols) < 5 or not cols[0]:
                continue
            wav, en, zh = cols[0], cols[3], cols[4]
            note = cols[5] if len(cols) > 5 else ''
            if '非语言' in note:
                continue
            text = zh.strip() or en.strip()
            if text:
                out.append((wav, text))
    return out


def read_level_dialog(tr_dir):
    """从 subtitles.tsv 里取「关卡剧情语音」的 (wav, 译文)。

    这批文本游戏本来就有 (存在 L*_text.tbl 里), 我们也早就翻译了, 但引擎只在
    电台通讯时显示, 世界里 NPC 之间的对话一句字幕都没有 —— 比如第一关开场
    矿工和卫兵那段。挂到同一套语音字幕机制上就能白捡。

    context 列存的就是语音文件名。
    """
    path = os.path.join(tr_dir, 'subtitles.tsv')
    if not os.path.exists(path):
        return []
    import csv as _csv
    out = []
    with open(path, encoding='utf-8', newline='') as f:
        r = _csv.reader(f, delimiter='\t', quoting=_csv.QUOTE_NONE)
        next(r, None)
        for cols in r:
            if len(cols) < 6:
                continue
            wav, zh = cols[2].strip(), cols[5].strip()
            if wav.lower().endswith('.wav') and zh:
                out.append((wav, zh))

    # 另外 165 条关卡语音游戏里连英文文本都没有 (训练关 PS2 版指令、亨德里克斯的
    # 部分台词), 是我们自己转写 + 翻译的, 表结构不同, 单独读。
    extra = os.path.join(tr_dir, 'level_extra_zh.tsv')
    if os.path.exists(extra):
        with open(extra, encoding='utf-8', newline='') as f:
            r = _csv.reader(f, delimiter='\t', quoting=_csv.QUOTE_NONE)
            next(r, None)
            for cols in r:
                if len(cols) >= 3 and cols[0] and cols[2].strip():
                    out.append((cols[0], cols[2].strip()))
    return out


def read_cutscene_subs(tr_dir):
    """读 cutscene_zh.tsv, 返回 [(音轨名, 起始ms, 结束ms, 译文)].

    即时演算过场的音频是整场混成一个 RFCS_*_FinalMix.wav 走流式播放的, 没法像
    普通语音那样按文件名查表, 只能按播放起点算经过时间。这批台词游戏本身
    **一个字的文本都没有**, 全是我们转写 + 翻译的。
    """
    path = os.path.join(tr_dir, 'cutscene_zh.tsv')
    if not os.path.exists(path):
        return []
    import csv as _csv
    out = []
    with open(path, encoding='utf-8', newline='') as f:
        r = _csv.reader(f, delimiter='\t', quoting=_csv.QUOTE_NONE)
        next(r, None)
        for cols in r:
            if len(cols) < 5 or not cols[0]:
                continue
            zh = cols[4].strip()
            if zh:
                out.append((cols[0], int(cols[1]), int(cols[2]), zh))
    out.sort(key=lambda x: (x[0].lower(), x[1]))
    return out


def collect_translated_chars(tr_dir):
    """扫描所有译文里用到的非 ASCII 字符.

    **必须把 patches/alpine_ui.tsv 也算进来。** 那是 Alpine 自有 UI 的译文, 虽然
    通过改源码生效、不进 vpp, 但它用到的字同样要在字体和字符集清单里 ——
    否则引擎查不到字形会直接跳过该字符, 界面上就会凭空少字
    ("武器抖动" 显示成 "武器动")。
    """
    chars = set()
    total = 0
    for name in ('ui_strings.tsv', 'subtitles.tsv'):
        path = os.path.join(tr_dir, name)
        for (_f, _k), zh in rftext._load_csv(path).items():
            total += 1
            chars.update(c for c in zh if ord(c) >= 0x80)

    # apply_patch.py 里那些需要上下文才能安全替换的短词 (经典/原始/现代 等)
    # 也必须并进来 —— 它们同样是会显示在界面上的中文
    try:
        sys.path.insert(0, os.path.join(ROOT, 'patches'))
        import apply_patch
        for zh in apply_patch.VALUE_TEXTS:
            chars.update(c for c in zh if ord(c) >= 0x80)
        print(f'  另含源码内嵌短词 {len(apply_patch.VALUE_TEXTS)} 条')
    except Exception as exc:
        print(f'  ! 读取 apply_patch.VALUE_TEXTS 失败: {exc}')

    # NPC 语音字幕 —— 同样是会显示在屏幕上的中文, 必须并进字符集
    for wav, text in read_npc_lines(tr_dir):
        chars.update(c for c in text if ord(c) >= 0x80)

    # 过场字幕同样会显示在屏幕上, 漏了字体里就没有对应字形, 引擎静默跳过
    for _t, _s, _e, text in read_cutscene_subs(tr_dir):
        chars.update(c for c in text if ord(c) >= 0x80)

    ui_tsv = os.path.join(ROOT, 'patches', 'alpine_ui.tsv')
    n_ui = 0
    if os.path.exists(ui_tsv):
        with open(ui_tsv, encoding='utf-8') as f:
            next(f)
            for line in f:
                parts = line.rstrip('\n').rstrip('\r').split('\t')
                if len(parts) < 2:
                    continue
                zh = parts[-1]
                if zh:
                    chars.update(c for c in zh if ord(c) >= 0x80)
                    n_ui += 1
        print(f'  另含 Alpine 自有 UI 译文 {n_ui} 条')
    return chars, total


# 4K 下引擎实际会实例化的字号 (来自 AlpineFaction.log)
ATLAS_SIZES = [('bold', 65), ('regular', 41), ('regular', 34), ('regular', 17),
               ('regular', 13), ('regular', 11), ('bold', 26), ('bold', 20)]


def estimate_atlas(codepoints, scale=1.5):
    """粗估所有字体实例的纹理图集总占用.

    引擎在构造字体时把**全部**字形一次性栅格化进一张 ARGB8888 图集, 边长向上取
    2 的幂。RF_120na.exe 是 32 位程序 (地址空间 2GB), 图集吃太多会直接崩。
    """
    import math
    n = len(codepoints)
    total = 0.0
    for _, size in ATLAS_SIZES:
        # 汉字字形近似为方块, 高度约等于像素字号 × scale
        side_px = size * scale
        area = n * side_px * side_px * 9 / 8      # 引擎留了 1/8 余量
        side = 2 ** math.ceil(math.log2(math.sqrt(area)))
        total += side * side * 4 / 1024 / 1024
    return total


# 标牌贴图单独成包, 不并进 rfcn.vpp。两个原因:
#   1. 体积。文本包 1.7 MB, 高清标牌 130+ MB —— 混在一起等于强迫所有人下 130 MB,
#      而标牌是纯锦上添花, 不影响任何一句剧情。分开发布, 想要的人再下。
#   2. 载入顺序。引擎用 FindFirstFile 遍历 client_mods, NTFS 按大写折叠排序返回,
#      **后加载的覆盖先加载的**。高清材质包常叫 Z_xxx.vpp (比如 Goober 的
#      Z_GoobRFReTex_01.vpp), 里面就有这批标牌。我们必须排在它后面才不会被顶掉,
#      所以名字用 zz_ 开头。rfcn.vpp 里只有 tbl/字体, 和材质包不冲突, 不用改名。
SIGNAGE_VPP = 'zz_rfcn_signage.vpp'


def build_signage(build, stage):
    """把改成中文的标牌贴图打成独立 vpp。没有改过的图就不生成。"""
    import signage
    sign_dir = os.path.join(stage, 'signage')
    os.makedirs(sign_dir, exist_ok=True)
    for old in os.listdir(sign_dir):
        os.remove(os.path.join(sign_dir, old))

    edited = signage.load_edited_hd()
    src = '高清 4x'
    if not edited:
        edited = signage.load_edited()
        src = '原始分辨率'
    if not edited:
        print('  没有改动过的标牌, 跳过')
        return []

    paths = []
    for name, data in edited:
        p = os.path.join(sign_dir, name)
        with open(p, 'wb') as f:
            f.write(data)
        paths.append(p)

    out = os.path.join(build, SIGNAGE_VPP)
    vpp.pack(out, paths)
    mb = os.path.getsize(out) / 1024 / 1024
    print(f'  {len(paths)} 张 ({src}) -> {out} ({mb:.1f} MB)')
    return [out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scale', type=float, default=1.5)
    ap.add_argument('--name', default='rfcn')
    ap.add_argument('--install', action='store_true')
    ap.add_argument('--no-signage', action='store_true',
                    help='不打包标牌贴图 (只出文本包)')
    args = ap.parse_args()

    work = os.path.join(ROOT, 'work')
    tr = os.path.join(ROOT, 'translation')
    build = os.path.join(ROOT, 'build')
    tbl_dir = os.path.join(build, 'tbl')
    stage = os.path.join(build, 'stage')
    os.makedirs(stage, exist_ok=True)

    print('[1/4] 回填译文')
    n = rftext.cmd_apply(work, tr, tbl_dir, 'utf-8')

    print('\n[2/4] 从译文提取字符集')
    zh_chars, n_rows = collect_translated_chars(tr)
    print(f'  已翻译 {n_rows} 条, 用到 {len(zh_chars)} 个非 ASCII 字符')

    print('\n[3/4] 生成字体')
    # 只收录拉丁基础集 + 译文里真正用到的字。
    # 字形数量直接决定图集边长, 而图集按 2 的幂增长 —— 多几百个用不到的字形
    # 就可能把 4096²(64MB) 顶成 8192²(256MB)。32 位进程扛不住这种浪费。
    cps = build_font.latin_codepoints()
    cps.update(ord(c) for c in zh_chars)
    print(f'  字体收录 {len(cps)} 个码点')
    est = estimate_atlas(cps)
    print(f'  预估图集显存 {est:.0f} MB'
          + ('   ← 偏大, 32 位进程有风险' if est > 200 else ''))
    font_files = []
    for src, idx, fname in build_font.SOURCES:
        if not os.path.exists(src):
            print(f'  跳过 (源字体不存在): {src}')
            continue
        out = os.path.join(stage, fname)
        size, converted = build_font.build_one(src, idx, out, cps, args.scale)
        print(f'  {fname:18s} {size / 1024:7.0f} KB  x{args.scale}  '
              f'{"CFF->glyf" if converted else "glyf"}')
        font_files.append(out)

    # 字符集清单: 只列基础 Windows-1252 之外的字
    base = build_font.latin_codepoints()
    extra = sorted(c for c in cps if c >= 0x80 and c != 0xFEFF and c not in base)
    charset_path = os.path.join(stage, 'alpine_extra_charset.txt')
    with open(charset_path, 'w', encoding='utf-8', newline='\n') as f:
        for i in range(0, len(extra), 64):
            f.write(''.join(chr(c) for c in extra[i:i + 64]) + '\n')
    print(f'  alpine_extra_charset.txt  {len(extra)} 个字符')

    # NPC 语音字幕表: <wav 文件名>\t<字幕>, DLL 侧忽略大小写查表
    npc = read_npc_lines(tr)
    dialog = read_level_dialog(tr)
    # 同名以 npc_lines.tsv 为准 (那是我们自己转写校对过的)
    merged = {w.lower(): (w, t) for w, t in dialog}
    merged.update({w.lower(): (w, t) for w, t in npc})
    npc_path = os.path.join(stage, 'alpine_npc_subtitles.tbl')
    with open(npc_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('// Voice subtitles: <wav>\\t<text>\n')
        for wav, text in sorted(merged.values()):
            f.write(f'{wav}\t{text}\n')
    n_zh = sum(1 for _, t in merged.values() if any(ord(c) >= 0x80 for c in t))
    print(f'  alpine_npc_subtitles.tbl  {len(merged)} 条 '
          f'(NPC 短句 {len(npc)} + 剧情对话 {len(dialog)}, 已译 {n_zh})')

    # 过场字幕表: <音轨>\t<起始ms>\t<结束ms>\t<字幕>, 按音轨分组、起始时间升序
    cuts = read_cutscene_subs(tr)
    cut_path = os.path.join(stage, 'alpine_cutscene_subtitles.tbl')
    with open(cut_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('// Cutscene subtitles: <track>\\t<start_ms>\\t<end_ms>\\t<text>\n')
        for track, s, e, text in cuts:
            f.write(f'{track}\t{s}\t{e}\t{text}\n')
    n_tracks = len({c[0].lower() for c in cuts})
    print(f'  alpine_cutscene_subtitles.tbl  {len(cuts)} 条 / {n_tracks} 个音轨')

    print('\n[4/5] 打包文本与字体')
    files = font_files + [charset_path, npc_path, cut_path]
    files += [os.path.join(tbl_dir, x) for x in sorted(os.listdir(tbl_dir))]
    out_vpp = os.path.join(build, f'{args.name}.vpp')
    vpp.pack(out_vpp, files)
    size_mb = os.path.getsize(out_vpp) / 1024 / 1024
    print(f'  {len(files)} 个文件 -> {out_vpp} ({size_mb:.2f} MB)')

    produced = [out_vpp]

    if not args.no_signage:
        print('\n[5/5] 打包中文标牌贴图')
        produced += build_signage(build, stage)

    if args.install:
        dst_dir = os.path.join(GAME_DIR, 'client_mods')
        os.makedirs(dst_dir, exist_ok=True)
        print()
        for src in produced:
            dst = os.path.join(dst_dir, os.path.basename(src))
            with open(src, 'rb') as s, open(dst, 'wb') as d:
                d.write(s.read())
            print(f'已安装 {dst}')
        print('注意: client_mods 里只留一套汉化包, 多套会互相覆盖')
    else:
        print(f'\n复制到 <游戏目录>\\client_mods\\ 即可生效')
    return 0


if __name__ == '__main__':
    sys.exit(main())
