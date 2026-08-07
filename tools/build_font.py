#!/usr/bin/env python3
"""构建中文字体并打包成 client_mods 用的 vpp.

Alpine Faction 通过 packfile 系统加载字体 (`rf::File`), 加载顺序里
client_mods 排在 alpinefaction.vpp 之后, 所以同名文件会覆盖官方字体:

    hud_get_default_font_name(big) -> "regularfont.ttf:17"
    hud_get_bold_font_name(big)    -> "boldfont.ttf:26"

注意这两个只在 Big HUD 开启时才生效, 普通 HUD 走的是原版 .vf 位图字体。

用法:
  python build_font.py [--out 目录] [--charset 文件] [--full-cjk]

--charset 指向一个纯文本文件, 脚本会取其中所有字符作为子集范围。
不指定则默认收录 CJK 基本区全部汉字 (体积较大, 适合开发期)。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vpp  # noqa: E402

# 游戏实际会栅格化的拉丁字符 (对应 gr_font.cpp 里的 win_1252_char_ranges)
LATIN_RANGES = [
    (0x20, 0x7E), (0x8C, 0x8C), (0x95, 0x95), (0x99, 0x99), (0x9C, 0x9C),
    (0x9F, 0x9F), (0xA6, 0xA7), (0xA9, 0xAB), (0xAE, 0xAE), (0xB0, 0xB0),
    (0xC0, 0xC2), (0xC4, 0xCB), (0xCE, 0xCF), (0xD2, 0xD4), (0xD6, 0xD6),
    (0xD9, 0xDC), (0xDF, 0xE2), (0xE4, 0xEB), (0xEE, 0xEF), (0xF2, 0xF4),
    (0xF6, 0xF6), (0xF9, 0xFC),
]
# 中文标点 / 全角符号
CJK_PUNCT_RANGES = [(0x3000, 0x303F), (0xFF00, 0xFFEF), (0x2018, 0x201D),
                    (0x2026, 0x2026), (0x2014, 0x2014)]
CJK_BASIC = (0x4E00, 0x9FFF)

# 源字体: (ttc 路径, face 索引, 输出文件名)
SOURCES = [
    ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 2, 'regularfont.ttf'),
    # 早期这里故意用衬线体当"覆盖是否生效"的探针, 现在验证完了, 换回黑体粗体
    ('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc', 2, 'boldfont.ttf'),
]


def latin_codepoints():
    """把 Windows-1252 的字节值转成真正的 Unicode 码点.

    引擎里是用 MultiByteToWideChar(1252, ...) 做这个转换的, 我们必须一致 ——
    比如字节 0x95 对应的是 U+2022 (•) 而不是 U+0095, 直接拿字节值当码点
    会导致子集里缺字形。
    """
    cps = set()
    for lo, hi in LATIN_RANGES:
        for b in range(lo, hi + 1):
            cps.add(ord(bytes([b]).decode('cp1252')))
    return cps


def collect_codepoints(charset_file=None, full_cjk=False, all_punct=False):
    """收集要收录的码点.

    **默认不再无脑收录整个中日韩标点区。** 那是 300 多个码点, 实际译文里
    只用到十来个, 而字形数量直接决定纹理图集的边长 —— 图集尺寸按 2 的幂增长,
    多出几百个字形就可能把 4096x4096 (64MB) 顶成 8192x8192 (256MB)。
    在 32 位进程里这种浪费是致命的。
    """
    cps = set(latin_codepoints())
    if all_punct:
        for lo, hi in CJK_PUNCT_RANGES:
            cps.update(range(lo, hi + 1))
    if charset_file:
        with open(charset_file, encoding='utf-8') as f:
            cps.update(ord(c) for c in f.read() if not c.isspace())
    if full_cjk:
        # 全量 CJK 基本区: 约 12 MB/字体, 子集化耗时以分钟计, 仅开发期用
        cps.update(range(CJK_BASIC[0], CJK_BASIC[1] + 1))
    return cps


def otf_to_ttf(font, max_err=1.0):
    """把 CFF(OpenType) 轮廓转成 glyf(TrueType) 轮廓.

    这一步是必须的, 不是优化。Alpine Faction 内置的 FreeType 没有编译 CFF 驱动,
    喂给它 OTF 会直接 `FT_New_Memory_Face failed: 2`(unknown file format)。
    官方的 regularfont.ttf / boldfont.ttf 都是 glyf 格式, 我们必须对齐。
    """
    from fontTools.ttLib import newTable
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.pens.cu2quPen import Cu2QuPen

    if 'glyf' in font:
        return False
    if 'CFF ' not in font and 'CFF2' not in font:
        raise ValueError('字体既不是 CFF 也不是 glyf, 无法处理')

    glyph_order = font.getGlyphOrder()
    glyph_set = font.getGlyphSet()
    glyf = newTable('glyf')
    glyf.glyphOrder = glyph_order
    glyf.glyphs = {}
    for name in glyph_order:
        tt_pen = TTGlyphPen(glyph_set)
        # reverse_direction: CFF 用逆时针, TrueType 用顺时针
        glyph_set[name].draw(Cu2QuPen(tt_pen, max_err, reverse_direction=True))
        glyf.glyphs[name] = tt_pen.glyph()

    font['glyf'] = glyf
    font['loca'] = newTable('loca')
    # maxp 要从 CFF 的 0.5 版升到 TrueType 的 1.0 版, 补齐必需字段
    maxp = font['maxp']
    maxp.tableVersion = 0x00010000
    for field, value in [
        ('maxZones', 1), ('maxTwilightPoints', 0), ('maxStorage', 0),
        ('maxFunctionDefs', 0), ('maxInstructionDefs', 0),
        ('maxStackElements', 0), ('maxSizeOfInstructions', 0),
        ('maxComponentElements', 0),
    ]:
        setattr(maxp, field, value)
    font['head'].indexToLocFormat = 0
    for tag in ('CFF ', 'CFF2', 'VORG'):
        if tag in font:
            del font[tag]
    # 垂直书写用的表, 对我们没用, 留着只是增大体积
    for tag in ('vhea', 'vmtx', 'BASE'):
        if tag in font:
            del font[tag]
    # 关键: 文件头的 sfntVersion 必须从 'OTTO'(CFF) 改成 0x00010000(TrueType),
    # 否则 FreeType 仍然按 CFF 去解析, 找不到 CFF 表就报 "table missing"。
    # 这一步漏掉的话前面所有转换都白做。
    font.sfntVersion = '\x00\x01\x00\x00'
    return True


def apply_scale(font, scale):
    """让字形在同一像素字号下渲染得更大.

    游戏里的字号 (`regularfont.ttf:17`) 硬编码在 DLL 里, mod 改不了。
    但 FreeType 是按 `像素字号 / unitsPerEm` 来缩放轮廓的 —— 只要把 upem
    调小而不动轮廓坐标, 所有字形和度量就会等比放大 scale 倍。
    CFF 字体还要同步改 FontMatrix, 否则两处不一致。
    """
    if scale == 1.0:
        return
    upem = font['head'].unitsPerEm
    new_upem = round(upem / scale)
    font['head'].unitsPerEm = new_upem
    if 'CFF ' in font:
        top_dict = font['CFF '].cff.topDictIndex[0]
        top_dict.FontMatrix = [1.0 / new_upem, 0, 0, 1.0 / new_upem, 0, 0]


def build_one(src, face_index, out_path, codepoints, scale=1.0):
    from fontTools.ttLib import TTFont, TTCollection
    from fontTools.subset import Subsetter, Options

    if src.lower().endswith('.ttc'):
        font = TTCollection(src)[face_index]
    else:
        font = TTFont(src)

    opts = Options()
    opts.desubroutinize = True
    opts.name_IDs = ['*']
    opts.notdef_outline = True
    opts.recalc_bounds = True
    sub = Subsetter(options=opts)
    sub.populate(unicodes=codepoints)
    sub.subset(font)
    converted = otf_to_ttf(font)      # 必须在子集化之后, 只转留下来的字形
    apply_scale(font, scale)
    font.save(out_path)
    font.close()
    return os.path.getsize(out_path), converted


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(
        os.path.dirname(here), 'dist', 'client_mods'))
    ap.add_argument('--charset')
    ap.add_argument('--full-cjk', action='store_true')
    ap.add_argument('--name', default='rfcn_font')
    ap.add_argument('--scale', type=float, default=1.5,
                    help='字形放大倍数, 用于抵消中文字体在硬编码字号下偏小的问题')
    args = ap.parse_args()

    cps = collect_codepoints(args.charset, args.full_cjk)
    print(f'字符集: {len(cps)} 个码点')

    work = os.path.join(args.out, '_fonts')
    os.makedirs(work, exist_ok=True)
    built = []
    for src, idx, name in SOURCES:
        if not os.path.exists(src):
            print(f'  跳过 (源字体不存在): {src}')
            continue
        out = os.path.join(work, name)
        size, converted = build_one(src, idx, out, cps, args.scale)
        tag = 'CFF->glyf' if converted else 'glyf'
        print(f'  {name:18s} {size / 1024 / 1024:6.2f} MB  x{args.scale}  {tag:10s}'
              f'<- {os.path.basename(src)}[{idx}]')
        built.append(out)

    if not built:
        print('没有可用的源字体, 中止')
        return 1

    # 引擎补丁要靠这个文件才知道该栅格化哪些字, 必须和字体打进同一个包
    charset_path = os.path.join(work, 'alpine_extra_charset.txt')
    # 只列"基础 Windows-1252 之外"的字符 —— 拉丁部分引擎自己就会加载
    base = latin_codepoints()
    extra = sorted(c for c in cps if c >= 0x80 and c != 0xFEFF and c not in base)
    with open(charset_path, 'w', encoding='utf-8', newline='\n') as f:
        for i in range(0, len(extra), 64):
            f.write(''.join(chr(c) for c in extra[i:i + 64]) + '\n')
    built.append(charset_path)
    print(f'  {"alpine_extra_charset.txt":18s} {len(extra):5d} 个字符')

    os.makedirs(args.out, exist_ok=True)
    vpp_path = os.path.join(args.out, f'{args.name}.vpp')
    vpp.pack(vpp_path, built)
    print(f'\n打包完成: {vpp_path} ({os.path.getsize(vpp_path) / 1024 / 1024:.2f} MB)')
    print(f'把它复制到  <游戏目录>\\client_mods\\  然后开 bighud 进游戏')
    return 0


if __name__ == '__main__':
    sys.exit(main())
