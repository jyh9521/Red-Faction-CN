#!/usr/bin/env python3
"""给 Alpine Faction 源码打中文支持补丁.

用法:
    python apply_patch.py <alpinefaction 源码目录> [--revert] [--big-hud-only-off]

改动全部基于字符串精确匹配, 不依赖行号, 所以上游更新后大概率还能用。
每一处都会检查"原文恰好出现一次", 匹配不到会明确报错而不是静默跳过。
脚本可重复执行: 已经打过的补丁会被识别并跳过。

改了什么, 为什么:

  A. gr_font.cpp  char_map_[256] -> unordered_map<uint32_t,int>
     原实现用单字节索引字形, 装不下汉字。

  B. gr_font.cpp  新增 UTF-8 解码器和扩展字符集加载
     从 packfile 读 alpine_extra_charset.txt (UTF-8), 里面出现过的字符
     都会被 FreeType 栅格化进图集。文件不存在时行为与原版完全一致。

  C. gr_font.cpp  构造函数同时注册两种键
     Windows-1252 单字节 (原版 tbl) 和 Unicode 码点 (UTF-8 tbl) 都能查到字形,
     所以德文/法文版不会被破坏。

  D. gr_font.cpp  draw() / get_size() 逐字节遍历 -> 逐码点遍历

  E. gr_font.cpp  gr_fit_string() 按码点回退, 不再把多字节字符切成两半

  F. hud.cpp      hud_fit_string() 同上

  G. gr_font.cpp  把三个文本类 .vf 位图字体重定向到 TTF
     Alpine 只把 rf::ui 那四个全局字体换成了 TTF, 但部分 UI 控件
     (武器优先级列表、按键绑定列表) 用的是别的字体句柄, 仍然是 .vf。
     位图字体按单字节索引字形, 非拉丁文本会渲染成逐字节的乱码。

  H. hud.cpp      (可选, --big-hud-only-off) 普通 HUD 也用 TTF
     原版只有 Big HUD 才走 TTF, 关掉 Big HUD 就回到位图字体, 中文会消失。
"""
import argparse
import os
import sys

UI_TSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'alpine_ui.tsv')
HEX = set('0123456789abcdefABCDEF')


def c_escape(text):
    """把中文写成纯 ASCII 的 C++ 字符串字面量内容.

    源码必须保持纯 ASCII —— 直接写中文的话, MSVC 在中文/日文 Windows 上会按系统
    代码页解释无 BOM 的源文件, GBK 的某些第二字节正好是 0x5C(反斜杠), 出现在
    字符串里会变成转义符, 后果不可预测。

    另一个坑是 C++ 的十六进制转义是**贪婪**的: "\\xe5F" 会被当成一个超大转义值,
    而不是 "\\xe5" 后面跟字母 F。所以只要转义后面紧跟十六进制数字字符,
    就得断开成相邻字符串字面量: "\\xe5" "F" —— 编译期会自动拼接。
    """
    out = []
    prev_escape = False
    for byte in text.encode('utf-8'):
        ch = chr(byte)
        if byte < 0x80 and ch not in '"\\':
            if prev_escape and ch in HEX:
                out.append('" "')          # 断开, 防止被并进上一个转义
            out.append(ch)
            prev_escape = False
        else:
            out.append(f'\\x{byte:02x}')
            prev_escape = True
    return ''.join(out)


# ---------------------------------------------------------------- 补丁内容

UTF8_HELPERS = r'''
// ============================================================================
// Support for non-Latin scripts (CJK and others)
// ----------------------------------------------------------------------------
// Glyphs used to be indexed by a single byte (char_map_[256]), which can only
// hold the ~220 Windows-1252 characters. These two helpers extend that to
// arbitrary Unicode code points:
//   utf8_decode       - pull one code point out of a byte stream
//   get_extra_charset - read the list of extra glyphs to rasterize, from a
//                       packfile entry supplied by a translation mod
// ============================================================================

// Decode one UTF-8 code point at pos and advance pos.
// On an invalid byte it falls back to returning that single byte. That both
// guarantees forward progress and keeps legacy Windows-1252 text working:
// bytes 0x80-0xFF are invalid UTF-8 lead bytes, so they come back unchanged
// and can still be looked up by their byte value.
static uint32_t utf8_decode(std::string_view text, size_t& pos)
{
    auto byte_at = [&](size_t i) { return static_cast<unsigned char>(text[i]); };
    unsigned char lead = byte_at(pos);
    if (lead < 0x80) {
        ++pos;
        return lead;
    }
    uint32_t cp;
    int extra;
    if ((lead & 0xE0) == 0xC0) { cp = lead & 0x1Fu; extra = 1; }
    else if ((lead & 0xF0) == 0xE0) { cp = lead & 0x0Fu; extra = 2; }
    else if ((lead & 0xF8) == 0xF0) { cp = lead & 0x07u; extra = 3; }
    else { ++pos; return lead; }
    if (pos + extra >= text.size()) {
        ++pos;
        return lead;
    }
    for (int i = 1; i <= extra; ++i) {
        unsigned char cont = byte_at(pos + i);
        if ((cont & 0xC0) != 0x80) {
            ++pos;
            return lead;
        }
        cp = (cp << 6) | (cont & 0x3Fu);
    }
    pos += extra + 1;
    return cp;
}

// List of extra characters to rasterize. Lives in a packfile (e.g. a
// translation mod's vpp) as plain UTF-8 text; only the set of characters that
// appear in it matters, formatting is irrelevant. If the file is absent this
// does nothing and behaviour is identical to stock.
constexpr const char* extra_charset_filename = "alpine_extra_charset.txt";

static const std::vector<uint32_t>& get_extra_charset()
{
    static std::vector<uint32_t> charset;
    static bool loaded = false;
    if (loaded) {
        return charset;
    }
    loaded = true;
    if (!rf::File{}.find(extra_charset_filename)) {
        return charset;
    }
    std::vector<unsigned char> buffer;
    if (!load_file_into_buffer(extra_charset_filename, buffer)) {
        return charset;
    }
    std::string_view sv{reinterpret_cast<const char*>(buffer.data()), buffer.size()};
    std::unordered_map<uint32_t, bool> seen;
    size_t pos = 0;
    while (pos < sv.size()) {
        uint32_t cp = utf8_decode(sv, pos);
        if (cp < 0x80 || cp == 0xFEFF) {
            continue;  // ASCII is already in the base set; FEFF is a BOM
        }
        if (seen.emplace(cp, true).second) {
            charset.push_back(cp);
        }
    }
    xlog::info("Loaded {} extra glyphs from {}", charset.size(), extra_charset_filename);
    return charset;
}
'''

EDITS = [
    # ---- A. 头文件 ----
    dict(
        file='game_patch/graphics/gr_font.cpp',
        # 注意: old 必须不是 new 的子串, 否则打完补丁后仍然能匹配到, 会被重复应用
        old='#include <cstddef>\n#include <exception>\n',
        new='#include <cstddef>\n#include <cstdint>\n#include <string_view>\n#include <exception>\n',
        why='补上 uint32_t / string_view 的头文件',
    ),
    # ---- B. 成员类型 ----
    dict(
        file='game_patch/graphics/gr_font.cpp',
        old='    std::vector<GlyphInfo> glyphs_;\n    int char_map_[256];\n',
        new='    std::vector<GlyphInfo> glyphs_;\n'
            '    // Keyed by Unicode code point. High bytes of legacy Windows-1252 text are\n'
            '    // additionally registered under their raw byte value so both encodings\n'
            '    // resolve to the same glyph (see the constructor).\n'
            '    std::unordered_map<uint32_t, int> char_map_;\n',
        why='单字节字形索引改成码点映射',
    ),
    # ---- C. 插入工具函数 ----
    dict(
        file='game_patch/graphics/gr_font.cpp',
        # 尾部带上下一个函数的开头, 保证 old 不是 new 的子串 (否则会被重复插入)
        old='    return true;\n'
            '}\n'
            '\n'
            'template<typename T>\n'
            'inline void TextureAtlasPacker<T>::add(int w, int h, T userdata)\n',
        new='    return true;\n'
            '}\n'
            + UTF8_HELPERS +
            '\n'
            'template<typename T>\n'
            'inline void TextureAtlasPacker<T>::add(int w, int h, T userdata)\n',
        why='插入 UTF-8 解码器与扩展字符集加载',
    ),
    # ---- D. 构造函数字符集 ----
    dict(
        file='game_patch/graphics/gr_font.cpp',
        old='    // Prepare character mapping and array of unicode code points\n'
            '    std::fill(char_map_, char_map_ + std::size(char_map_), -1);\n'
            '    std::vector<int> unicode_code_points;\n'
            '    for (auto& range : win_1252_char_ranges) {\n'
            '        for (auto c = range.first; c < range.second + 1; ++c) {\n'
            '            if (digits_only && !std::isdigit(c)) {\n'
            '                continue;\n'
            '            }\n'
            '            char windows_1252_char = static_cast<char>(c);\n'
            '            wchar_t unicode_char = 0;\n'
            '            MultiByteToWideChar(1252, 0, &windows_1252_char, 1, &unicode_char, 1);\n'
            '            unicode_code_points.push_back(unicode_char);\n'
            '            auto char_idx = static_cast<unsigned char>(windows_1252_char);\n'
            '            char_map_[char_idx] = unicode_code_points.size() - 1;\n'
            '        }\n'
            '    }\n',
        new='    // Base character set: Windows-1252, same as stock\n'
            '    char_map_.clear();\n'
            '    std::vector<int> unicode_code_points;\n'
            '    for (auto& range : win_1252_char_ranges) {\n'
            '        for (auto c = range.first; c < range.second + 1; ++c) {\n'
            '            if (digits_only && !std::isdigit(c)) {\n'
            '                continue;\n'
            '            }\n'
            '            char windows_1252_char = static_cast<char>(c);\n'
            '            wchar_t unicode_char = 0;\n'
            '            MultiByteToWideChar(1252, 0, &windows_1252_char, 1, &unicode_char, 1);\n'
            '            unicode_code_points.push_back(unicode_char);\n'
            '            int glyph_idx = static_cast<int>(unicode_code_points.size()) - 1;\n'
            '            // Register both keys: stock tables are Windows-1252 (single byte),\n'
            '            // translated tables are UTF-8. Bytes 0x80-0xFF are invalid UTF-8 lead\n'
            '            // bytes, so the decoder returns them unchanged and the two encodings\n'
            '            // never collide. This keeps the German and French editions working.\n'
            '            char_map_[static_cast<uint32_t>(static_cast<unsigned char>(windows_1252_char))] = glyph_idx;\n'
            '            char_map_[static_cast<uint32_t>(unicode_char)] = glyph_idx;\n'
            '        }\n'
            '    }\n'
            '    // Extra character set (CJK etc.), registered by code point\n'
            '    if (!digits_only) {\n'
            '        for (uint32_t cp : get_extra_charset()) {\n'
            '            if (char_map_.find(cp) != char_map_.end()) {\n'
            '                continue;\n'
            '            }\n'
            '            unicode_code_points.push_back(static_cast<int>(cp));\n'
            '            char_map_[cp] = static_cast<int>(unicode_code_points.size()) - 1;\n'
            '        }\n'
            '    }\n',
        why='字符集加入扩展汉字, 并同时按字节值和码点注册',
    ),
    # ---- E. draw() ----
    dict(
        file='game_patch/graphics/gr_font.cpp',
        old='    for (auto ch : text) {\n'
            '        if (ch == \'\\n\') {\n'
            '            pen_x = x;\n'
            '            pen_y += line_spacing_;\n'
            '        }\n'
            '        else {\n'
            '            auto glyph_idx = char_map_[static_cast<unsigned char>(ch)];\n'
            '            if (glyph_idx != -1) {\n'
            '                const auto& glyph_info = glyphs_[glyph_idx];\n'
            '                if (glyph_info.bm_w) {\n'
            '                    // rf::gr::rect(pen_x + glyph_info.x, pen_y + glyph_info.y, glyph_info.bm_w, glyph_info.bm_h);\n'
            '                    rf::gr::bitmap_ex(bitmap_, pen_x + glyph_info.x, pen_y + glyph_info.y, glyph_info.bm_w, glyph_info.bm_h, glyph_info.bm_x, glyph_info.bm_y, state);\n'
            '                }\n'
            '                pen_x += glyph_info.advance_x;\n'
            '            }\n'
            '        }\n'
            '    }\n',
        new='    size_t char_pos = 0;\n'
            '    while (char_pos < text.size()) {\n'
            '        uint32_t cp = utf8_decode(text, char_pos);\n'
            '        if (cp == static_cast<uint32_t>(\'\\n\')) {\n'
            '            pen_x = x;\n'
            '            pen_y += line_spacing_;\n'
            '            continue;\n'
            '        }\n'
            '        auto it = char_map_.find(cp);\n'
            '        if (it == char_map_.end()) {\n'
            '            continue;\n'
            '        }\n'
            '        const auto& glyph_info = glyphs_[it->second];\n'
            '        if (glyph_info.bm_w) {\n'
            '            rf::gr::bitmap_ex(bitmap_, pen_x + glyph_info.x, pen_y + glyph_info.y, glyph_info.bm_w, glyph_info.bm_h, glyph_info.bm_x, glyph_info.bm_y, state);\n'
            '        }\n'
            '        pen_x += glyph_info.advance_x;\n'
            '    }\n',
        why='draw() 改为逐码点绘制',
    ),
    # ---- F. get_size() ----
    dict(
        file='game_patch/graphics/gr_font.cpp',
        old='    for (auto ch : text) {\n'
            '        if (ch == \'\\n\') {\n'
            '            *w = std::max(*w, cur_line_w);\n'
            '            cur_line_w = 0;\n'
            '            *h += line_spacing_;\n'
            '        }\n'
            '        else {\n'
            '            auto glyph_idx = char_map_[static_cast<unsigned char>(ch)];\n'
            '            if (glyph_idx != -1) {\n'
            '                const auto& glyph_info = glyphs_[glyph_idx];\n'
            '                cur_line_w += glyph_info.advance_x;\n'
            '            }\n'
            '        }\n'
            '    }\n',
        new='    size_t char_pos = 0;\n'
            '    while (char_pos < text.size()) {\n'
            '        uint32_t cp = utf8_decode(text, char_pos);\n'
            '        if (cp == static_cast<uint32_t>(\'\\n\')) {\n'
            '            *w = std::max(*w, cur_line_w);\n'
            '            cur_line_w = 0;\n'
            '            *h += line_spacing_;\n'
            '            continue;\n'
            '        }\n'
            '        auto it = char_map_.find(cp);\n'
            '        if (it != char_map_.end()) {\n'
            '            cur_line_w += glyphs_[it->second].advance_x;\n'
            '        }\n'
            '    }\n',
        why='get_size() 改为逐码点测量',
    ),
    # ---- G. gr_fit_string ----
    dict(
        file='game_patch/graphics/gr_font.cpp',
        old='    while (text_w + suffix_w > max_width && !text.empty()) {\n'
            '        const auto [last_w, last_h] = rf::gr::get_char_size(text.back(), font_id);\n'
            '        text_w -= last_w;\n'
            '        text.pop_back();\n'
            '    }\n',
        new='    while (text_w + suffix_w > max_width && !text.empty()) {\n'
            '        // Trim whole code points, otherwise a multi-byte character gets cut in half\n'
            '        size_t cut = text.size() - 1;\n'
            '        while (cut > 0 && (static_cast<unsigned char>(text[cut]) & 0xC0) == 0x80) {\n'
            '            --cut;\n'
            '        }\n'
            '        text.erase(cut);\n'
            '        const auto [new_w, new_h] = rf::gr::get_string_size(text, font_id);\n'
            '        text_w = new_w;\n'
            '    }\n',
        why='字符串截断改为码点对齐',
    ),
]

# .vf → TTF 重定向。单独拆出来是因为它风险最高:
# 它把带 ttf_font_flag(0x1000) 的字体 id 交给了**原版引擎代码**, 而引擎里
# 有些地方可能直接拿这个 id 去索引只有 12 个槽位的 rf::gr::fonts[] 数组。
# 用 --no-vf-redirect 可以单独关掉它做对照测试。
VF_REDIRECT_EDITS = [
    # ---- G2. .vf 字体重定向: 头文件 + 辅助函数 ----
    dict(
        file='game_patch/graphics/gr_font.cpp',
        # 尾部带上下一行, 保证 old 不是 new 的子串
        old='#include <common/utils/string-utils.h>\n'
            '#include "../rf/gr/gr_font.h"\n'
            '#include "../rf/bmpman.h"\n',
        new='#include <format>\n'
            '#include <algorithm>\n'
            '#include <cmath>\n'
            '#include <common/utils/string-utils.h>\n'
            '#include "../rf/gr/gr_font.h"\n'
            '#include "../rf/ui.h"\n'
            '#include "../rf/bmpman.h"\n',
        why='.vf 重定向所需的头文件',
    ),
    dict(
        file='game_patch/graphics/gr_font.cpp',
        old='constexpr int ttf_font_flag = 0x1000;\n'
            '\n'
            'FT_Library g_freetype_lib = nullptr;\n',
        new='constexpr int ttf_font_flag = 0x1000;\n'
            '\n'
            '// Stock .vf bitmap fonts index glyphs by a single byte, so any non-Latin text\n'
            '// drawn with one comes out as per-byte mojibake. Alpine already swaps the four\n'
            '// rf::ui globals for TrueType, but some widgets (the weapon priority list and\n'
            '// the control binding list among them) hold a separate font handle and still\n'
            '// ask for a .vf. Redirect the three general-purpose text fonts to their\n'
            '// TrueType equivalents, using the same scale factors menu_init_hook uses, so\n'
            '// those widgets get a font that can actually render the text.\n'
            '//\n'
            '// bigfont.vf / smallfont.vf / biggerfont.vf are deliberately left alone: they\n'
            '// hold 32-69 glyphs with a non-standard first_ascii and are special-purpose\n'
            '// glyph sets (HUD counters), not general text.\n'
            'static std::string redirect_vf_font(const char* name)\n'
            '{\n'
            '    const float scale = rf::ui::scale_y;\n'
            '    if (!(scale > 1.0f)) {\n'
            '        return {};   // UI scale not known yet - keep the bitmap font\n'
            '    }\n'
            '    auto px = [scale](float factor) {\n'
            '        return std::min(128, static_cast<int>(std::round(scale * factor)));\n'
            '    };\n'
            '    if (string_iequals(name, "rfpc-large.vf")) {\n'
            '        return std::format("boldfont.ttf:{}", px(14.5f));\n'
            '    }\n'
            '    if (string_iequals(name, "rfpc-medium.vf")) {\n'
            '        return std::format("regularfont.ttf:{}", px(9.0f));\n'
            '    }\n'
            '    if (string_iequals(name, "rfpc-small.vf")) {\n'
            '        return std::format("regularfont.ttf:{}", px(7.5f));\n'
            '    }\n'
            '    return {};\n'
            '}\n'
            '\n'
            'FT_Library g_freetype_lib = nullptr;\n',
        why='新增 .vf → TTF 重定向函数',
    ),
    dict(
        file='game_patch/graphics/gr_font.cpp',
        old='        if (string_ends_with(name, ".vf")) {\n'
            '            return gr_init_font_hook.call_target(name, reserved);\n'
            '        }\n'
            '        for (unsigned i = 0; i < g_fonts.size(); ++i) {\n',
        new='        std::string redirected;\n'
            '        if (string_ends_with(name, ".vf")) {\n'
            '            redirected = redirect_vf_font(name);\n'
            '            if (redirected.empty()) {\n'
            '                return gr_init_font_hook.call_target(name, reserved);\n'
            '            }\n'
            '            xlog::info("Redirecting bitmap font {} to {}", name, redirected);\n'
            '            name = redirected.c_str();   // outlives every use below\n'
            '        }\n'
            '        for (unsigned i = 0; i < g_fonts.size(); ++i) {\n',
        why='.vf 加载入口改为先尝试重定向',
    ),
]

# 诊断 + 加固: 给三个 TTF 钩子加边界检查。
#
# 上游写的是 `g_fonts[font_num & ~ttf_font_flag]` —— std::vector::operator[]
# 越界是未定义行为, 不会抛异常也不会报错, 只会读到垃圾内存, 然后在后续访问
# glyphs_ 时才炸。一旦引擎把陈旧/非法的字体 id 传进来 (关卡切换、控件复用等),
# 就会以完全不相干的形式崩溃。
#
# 这几处改动本身也是**该有的健壮性**, 不只是排查手段: 越界时打日志并安全退出,
# 比未定义行为强得多。
FONT_GUARD_EDITS = [
    dict(
        file='game_patch/graphics/gr_font.cpp',
        old='        if (font_num & ttf_font_flag) {\n'
            '            auto& font = g_fonts[font_num & ~ttf_font_flag];\n'
            '            return font.get_height();\n'
            '        }\n',
        new='        if (font_num & ttf_font_flag) {\n'
            '            unsigned idx = static_cast<unsigned>(font_num & ~ttf_font_flag);\n'
            '            if (idx >= g_fonts.size()) {\n'
            '                xlog::error("gr_get_font_height: bad TTF font id {:#x} (have {})",\n'
            '                    font_num, g_fonts.size());\n'
            '                return 0;\n'
            '            }\n'
            '            return g_fonts[idx].get_height();\n'
            '        }\n',
        why='加固: get_font_height 的字体 id 边界检查',
    ),
    dict(
        file='game_patch/graphics/gr_font.cpp',
        old='        if (font_num & ttf_font_flag) {\n'
            '            auto& font = g_fonts[font_num & ~ttf_font_flag];\n'
            '            font.draw(x, y, text, mode);\n'
            '        }\n',
        new='        if (font_num & ttf_font_flag) {\n'
            '            unsigned idx = static_cast<unsigned>(font_num & ~ttf_font_flag);\n'
            '            if (idx >= g_fonts.size()) {\n'
            '                xlog::error("gr_string: bad TTF font id {:#x} (have {}) text={}",\n'
            '                    font_num, g_fonts.size(), text ? text : "(null)");\n'
            '                return;\n'
            '            }\n'
            '            try {\n'
            '                g_fonts[idx].draw(x, y, text, mode);\n'
            '            }\n'
            '            catch (const std::exception& e) {\n'
            '                xlog::error("gr_string threw: {} | font={:#x} text={}",\n'
            '                    e.what(), font_num, text ? text : "(null)");\n'
            '            }\n'
            '        }\n',
        why='加固: gr_string 边界检查 + 异常兜底',
    ),
    dict(
        file='game_patch/graphics/gr_font.cpp',
        old='        if (font_num & ttf_font_flag) {\n'
            '            auto& font = g_fonts[font_num & ~ttf_font_flag];\n'
            '            std::string_view text_sv;\n'
            '            if (text_len < 0) {\n'
            '                text_sv = std::string_view{text};\n'
            '            }\n'
            '            else {\n'
            '                text_sv = std::string_view{text, static_cast<size_t>(text_len)};\n'
            '            }\n'
            '            font.get_size(out_width, out_height, text_sv);\n'
            '        }\n',
        new='        if (font_num & ttf_font_flag) {\n'
            '            unsigned idx = static_cast<unsigned>(font_num & ~ttf_font_flag);\n'
            '            if (idx >= g_fonts.size()) {\n'
            '                xlog::error("gr_get_string_size: bad TTF font id {:#x} (have {})",\n'
            '                    font_num, g_fonts.size());\n'
            '                *out_width = 0;\n'
            '                *out_height = 0;\n'
            '                return;\n'
            '            }\n'
            '            std::string_view text_sv;\n'
            '            if (text_len < 0) {\n'
            '                text_sv = std::string_view{text};\n'
            '            }\n'
            '            else {\n'
            '                text_sv = std::string_view{text, static_cast<size_t>(text_len)};\n'
            '            }\n'
            '            try {\n'
            '                g_fonts[idx].get_size(out_width, out_height, text_sv);\n'
            '            }\n'
            '            catch (const std::exception& e) {\n'
            '                xlog::error("gr_get_string_size threw: {} | font={:#x} len={}",\n'
            '                    e.what(), font_num, text_len);\n'
            '                *out_width = 0;\n'
            '                *out_height = 0;\n'
            '            }\n'
            '        }\n',
        why='加固: gr_get_string_size 边界检查 + 异常兜底',
    ),
]

# 已合并进 FONT_GUARD_EDITS —— 两组改动串联会破坏幂等性
FONT_CATCH_EDITS = []


# ---------------------------------------------------------------------------
# NPC 语音字幕
#
# 游戏里路人 NPC 的语音 (foley.tbl 的 persona 语音组: 发现玩家、求饶、闲聊……)
# 原版完全没有字幕, 也没有任何表把它们关联到文字。
#
# 做法: 钩住底层播放函数 snd_play_3d / snd_play, 用 rf::sounds[handle].filename
# 反查文件名 —— 这个字段引擎本来就有, 不需要我们自己建 id 映射。查到就调
# rf::hud_msg 走原版的屏幕消息通道。
#
# 两个要点:
#   * foley.tbl 里写的是 "Grd_Alert_01.wav", 而 vpp 索引里是 "GRD_ALERT_01.WAV",
#     所以查表必须忽略大小写。
#   * hud_msg (0x004383C0) 不会写进 M 键消息记录 —— 那个是 persona 系统单独喂的
#     (0x00437FB0, 只被 0x00439429 调用)。所以字幕不会淹没剧情消息。
#
# 字幕表放在 vpp 里, 缺文件就等于功能关闭, 行为和原版一致。
# ---------------------------------------------------------------------------
NPCSUB_HELPERS = r'''
// ---- NPC voice subtitles ----------------------------------------------------
// Ambient NPC barks have no subtitles in the original game. The table lives in a
// packfile as UTF-8 text, one entry per line:
//     <wav filename><TAB><subtitle>
// Blank lines and lines starting with // are ignored. If the file is absent the
// feature is simply off and behaviour is identical to stock.
constexpr const char* npc_subtitle_filename = "alpine_npc_subtitles.tbl";

static std::string npc_sub_lower(const char* s)
{
    std::string out;
    for (; s && *s; ++s) {
        out += static_cast<char>(std::tolower(static_cast<unsigned char>(*s)));
    }
    return out;
}

static const std::unordered_map<std::string, std::string>& npc_subtitle_table()
{
    static std::unordered_map<std::string, std::string> table;
    static bool loaded = false;
    if (loaded) {
        return table;
    }
    loaded = true;

    rf::File file;
    if (file.open(npc_subtitle_filename) != 0) {
        // Log it: a silent empty table is indistinguishable from a hook that never ran.
        xlog::info("{} not found, NPC subtitles are off", npc_subtitle_filename);
        return table;
    }
    const int len = file.size();
    std::string buf(static_cast<size_t>(len), '\0');
    int total = 0;
    while (total < len) {
        const int n = file.read(buf.data() + total, len - total);
        if (n <= 0) {
            break;
        }
        total += n;
    }
    file.close();
    buf.resize(static_cast<size_t>(total));

    size_t pos = 0;
    while (pos < buf.size()) {
        size_t eol = buf.find('\n', pos);
        if (eol == std::string::npos) {
            eol = buf.size();
        }
        std::string_view line{buf.data() + pos, eol - pos};
        pos = eol + 1;
        while (!line.empty() && (line.back() == '\r' || line.back() == ' ')) {
            line.remove_suffix(1);
        }
        if (line.empty() || line.substr(0, 2) == "//") {
            continue;
        }
        const size_t tab = line.find('\t');
        if (tab == std::string_view::npos) {
            continue;
        }
        // foley.tbl spells these "Grd_Alert_01.wav" but the packfile index has them
        // upper case, so the key is always lowered on both sides.
        std::string key{line.substr(0, tab)};
        for (char& c : key) {
            c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        }
        std::string text{line.substr(tab + 1)};
        if (!key.empty() && !text.empty()) {
            table.emplace(std::move(key), std::move(text));
        }
    }
    xlog::info("Loaded {} NPC subtitles from {}", table.size(), npc_subtitle_filename);
    return table;
}

static int g_npc_subtitle_debug = 30;   // log the first N lookups, then go quiet

// ---- Independent subtitle channel -------------------------------------------
// rf::hud_msg is shared with pickup notices ("Picked up ...") and holds at most 8
// entries, so voice subtitles and item pickups keep pushing each other out. This is
// a separate queue with its own render pass: it cannot be stepped on, and position,
// lifetime and styling are ours to set.
constexpr int npc_subtitle_max_lines = 3;

struct NpcSubtitleLine
{
    std::string text;
    int expire_ms = 0;
};

static NpcSubtitleLine g_npc_subtitle_queue[npc_subtitle_max_lines];

static void npc_subtitle_push(const std::string& text, int duration_ms)
{
    for (int i = 0; i + 1 < npc_subtitle_max_lines; ++i) {
        g_npc_subtitle_queue[i] = std::move(g_npc_subtitle_queue[i + 1]);
    }
    auto& slot = g_npc_subtitle_queue[npc_subtitle_max_lines - 1];
    slot.text = text;
    slot.expire_ms = rf::frametime_total_milliseconds + duration_ms;
}

// Same font the message log body uses (0x006C66F0 is set when the log UI is created).
// Cached rather than loaded per call: the .vf redirect logs a line every time.
static auto& npc_subtitle_msglog_font = addr_as_ref<int>(0x006C66F0);

static int npc_subtitle_font()
{
    if (npc_subtitle_msglog_font) {
        return npc_subtitle_msglog_font;
    }
    static int fallback = rf::gr::load_font("rfpc-medium.vf");
    return fallback;
}

// ---- Cutscene subtitles ------------------------------------------------------
// In-engine cutscenes do not play their dialogue through snd_play/snd_play_3d at
// all: the whole scene is one pre-mixed track (RFCS_*_FinalMix.wav) streamed via
// snd_music_play, so there is no per-line filename to look up. The engine also
// ships no text for these lines -- they were transcribed and translated by hand.
// So this is a plain timed track: remember when playback started, then show
// whichever phrase covers the elapsed time.
constexpr const char* cutscene_subtitle_filename = "alpine_cutscene_subtitles.tbl";

struct CutscenePhrase
{
    int start_ms;
    int end_ms;
    std::string text;
};

// Local decimal parser: avoids pulling <cstdlib> in just for atoi.
static int cutscene_parse_int(std::string_view s)
{
    int v = 0;
    for (char c : s) {
        if (c < '0' || c > '9') {
            break;
        }
        v = v * 10 + (c - '0');
    }
    return v;
}

static const std::unordered_map<std::string, std::vector<CutscenePhrase>>& cutscene_subtitle_table()
{
    static std::unordered_map<std::string, std::vector<CutscenePhrase>> table;
    static bool loaded = false;
    if (loaded) {
        return table;
    }
    loaded = true;

    rf::File file;
    if (file.open(cutscene_subtitle_filename) != 0) {
        xlog::info("{} not found, cutscene subtitles are off", cutscene_subtitle_filename);
        return table;
    }
    const int len = file.size();
    std::string buf(static_cast<size_t>(len), '\0');
    int total = 0;
    while (total < len) {
        const int n = file.read(buf.data() + total, len - total);
        if (n <= 0) {
            break;
        }
        total += n;
    }
    file.close();
    buf.resize(static_cast<size_t>(total));

    size_t pos = 0;
    while (pos < buf.size()) {
        size_t eol = buf.find('\n', pos);
        if (eol == std::string::npos) {
            eol = buf.size();
        }
        std::string_view line{buf.data() + pos, eol - pos};
        pos = eol + 1;
        while (!line.empty() && (line.back() == '\r' || line.back() == ' ')) {
            line.remove_suffix(1);
        }
        if (line.empty() || line.substr(0, 2) == "//") {
            continue;
        }
        const size_t t1 = line.find('\t');
        if (t1 == std::string_view::npos) continue;
        const size_t t2 = line.find('\t', t1 + 1);
        if (t2 == std::string_view::npos) continue;
        const size_t t3 = line.find('\t', t2 + 1);
        if (t3 == std::string_view::npos) continue;
        CutscenePhrase p;
        p.start_ms = cutscene_parse_int(line.substr(t1 + 1, t2 - t1 - 1));
        p.end_ms = cutscene_parse_int(line.substr(t2 + 1, t3 - t2 - 1));
        p.text = std::string{line.substr(t3 + 1)};
        if (p.end_ms > p.start_ms && !p.text.empty()) {
            table[npc_sub_lower(std::string{line.substr(0, t1)}.c_str())].push_back(std::move(p));
        }
    }
    size_t n_lines = 0;
    for (auto& kv : table) {
        std::sort(kv.second.begin(), kv.second.end(),
                  [](const CutscenePhrase& a, const CutscenePhrase& b) {
                      return a.start_ms < b.start_ms;
                  });
        n_lines += kv.second.size();
    }
    xlog::info("Loaded {} cutscene subtitles across {} tracks from {}",
        n_lines, table.size(), cutscene_subtitle_filename);
    return table;
}

static const std::vector<CutscenePhrase>* g_cutscene_phrases = nullptr;
static int g_cutscene_started_ms = 0;

static void cutscene_subtitle_begin(const char* track)
{
    g_cutscene_phrases = nullptr;
    if (!track) {
        return;
    }
    const auto& table = cutscene_subtitle_table();
    const auto it = table.find(npc_sub_lower(track));
    if (it == table.end()) {
        return;
    }
    g_cutscene_phrases = &it->second;
    g_cutscene_started_ms = rf::frametime_total_milliseconds;
    xlog::info("Cutscene subtitles armed for '{}' ({} lines)", track, it->second.size());
}

// Returns the phrase covering the current playback position, or nullptr.
static const std::string* cutscene_subtitle_current(int now)
{
    if (!g_cutscene_phrases || g_cutscene_bg_sound_sig == -1) {
        // sig is cleared when the player skips the cutscene
        return nullptr;
    }
    const int elapsed = now - g_cutscene_started_ms;
    for (const auto& p : *g_cutscene_phrases) {
        if (elapsed < p.start_ms) {
            break;      // sorted, so nothing later can match either
        }
        if (elapsed < p.end_ms) {
            return &p.text;
        }
    }
    return nullptr;
}

void npc_subtitle_render()
{
    const int now = rf::frametime_total_milliseconds;

    // Two paths drive this: the HUD message render hook during normal gameplay, and
    // the cutscene per-frame hook (the HUD is not drawn at all during cutscenes).
    // Both can run in the same frame, and drawing twice would double the drop shadow,
    // so the second call in a frame is a no-op.
    static int last_drawn_ms = -1;
    if (now == last_drawn_ms) {
        return;
    }
    last_drawn_ms = now;

    const int font = npc_subtitle_font();
    const int line_h = rf::gr::get_font_height(font);
    const int clip_w = rf::gr::clip_width();
    const int clip_h = rf::gr::clip_height();
    const int max_w = clip_w * 4 / 5;

    // Cutscene line first, then the ordinary queue. During a cutscene the queue is
    // normally empty anyway, but a sound started just before the cutscene began can
    // still be expiring, and stacking them is better than one hiding the other.
    std::vector<std::string> sources;
    if (const std::string* cut = cutscene_subtitle_current(now)) {
        sources.push_back(*cut);
    }
    for (const auto& slot : g_npc_subtitle_queue) {
        if (!slot.text.empty() && now < slot.expire_ms) {
            sources.push_back(slot.text);
        }
    }

    std::vector<std::string> lines;
    for (const auto& src : sources) {
        // gr_split_str is our CJK aware replacement, so this wraps Chinese correctly
        std::string buf = src;
        int len_array[8] = {};
        int off_array[8] = {};
        const int n = rf::gr::split_str(len_array, off_array, buf.data(), max_w, 8, 0, font);
        if (n <= 0) {
            lines.push_back(buf);
        }
        else {
            for (int i = 0; i < n; ++i) {
                lines.emplace_back(buf, static_cast<size_t>(off_array[i]),
                                   static_cast<size_t>(len_array[i]));
            }
        }
    }
    if (lines.empty()) {
        return;
    }

    // Sit above the engine's own message line so the two never overlap.
    const int center_x = clip_w / 2;
    int y = clip_h * 84 / 100 - static_cast<int>(lines.size()) * line_h;
    for (const auto& line : lines) {
        rf::gr::set_color(0, 0, 0, 170);
        rf::gr::string_aligned(rf::gr::ALIGN_CENTER, center_x + 2, y + 2, line.c_str(), font);
        rf::gr::set_color(255, 255, 255, 255);
        rf::gr::string_aligned(rf::gr::ALIGN_CENTER, center_x, y, line.c_str(), font);
        y += line_h;
    }
}


static void npc_subtitle_on_play(int handle, const rf::Vector3* pos)
{
    const auto& table = npc_subtitle_table();
    if (table.empty() || handle < 0 || handle >= 2600) {
        return;
    }
    const rf::Sound& snd = rf::sounds[handle];
    const auto it = table.find(npc_sub_lower(snd.filename));

    // Diagnostics first, before any of the early returns below. Logging after them
    // means a line skipped by the persona check leaves no trace at all, which makes
    // "no subtitle" and "hook never saw it" look identical in the log.
    // Only level dialogue names (L<n>S<n>_...) are logged, so gunfire and footsteps
    // do not burn the budget.
    if (g_npc_subtitle_debug > 0) {
        const char* fn = snd.filename;
        // Level dialogue is named L<level>S<scene>_..., e.g. L6S3_GRYN_01.wav.
        // Checking the first two chars avoids needing <cstring> for strchr.
        const bool is_dialogue = fn && (fn[0] == 'L' || fn[0] == 'l')
            && fn[1] >= '0' && fn[1] <= '9';
        if (is_dialogue || it != table.end()) {
            --g_npc_subtitle_debug;
            const int pidx = rf::hud_persona_current_idx;
            const bool persona_owns = pidx >= 0 && pidx < 10
                && rf::hud_personas_info[pidx].sound_handle == handle;
            xlog::info("[npc-sub] '{}' {} in_table={} persona_owns={} alpha={:.2f}",
                fn ? fn : "(null)", pos ? "3D" : "2D", it != table.end(), persona_owns,
                rf::hud_persona_alpha);
        }
    }

    // Skip only the one line the engine is itself subtitling in the persona box.
    // HudPersonaInfo::sound_handle and hud_persona_current_idx are both set before the
    // sound is started (0x0043957C sets the index, the play call reads +0x20 after it),
    // so this comparison is reliable at the moment we run.
    //
    // Do NOT gate on hud_persona_alpha alone: the box is up for several seconds, and
    // world conversations often happen underneath it -- the level 1 opening has Orion
    // on the radio while a guard and a miner argue in front of you.
    const int persona_idx = rf::hud_persona_current_idx;
    if (persona_idx >= 0 && persona_idx < 10
        && rf::hud_personas_info[persona_idx].sound_handle == handle) {
        return;
    }

    float dist = -1.0f;
    if (pos) {
        const float dx = pos->x - rf::sound_listener_pos.x;
        const float dy = pos->y - rf::sound_listener_pos.y;
        const float dz = pos->z - rf::sound_listener_pos.z;
        dist = std::sqrt(dx * dx + dy * dy + dz * dz);
    }

    if (it == table.end()) {
        return;
    }
    // Out of earshot: the engine plays it inaudibly, no reason to subtitle it.
    // Only trust max_range when it is actually set -- snd_get_handle takes min_range
    // but no max_range, so for dynamically loaded sounds it can be left at zero, and
    // a naive "dist > max_range" then rejects everything.
    if (dist >= 0.0f && snd.max_range > 0.0f && dist > snd.max_range) {
        return;
    }
    // Duration follows the clip: long lines stay up long enough to read.
    const float secs = rf::snd_pc_get_duration(handle);
    int ms = static_cast<int>(secs * 1000.0f) + 900;
    ms = std::clamp(ms, 2500, 9000);
    npc_subtitle_push(it->second, ms);
}

'''

NPCSUB_EDITS = [
    dict(
        file='game_patch/sound/sound.cpp',
        old='#include "../misc/vpackfile.h"\n'
            '\n'
            'static int g_cutscene_bg_sound_sig = -1;\n',
        new='#include "../misc/vpackfile.h"\n'
            '#include "../rf/file/file.h"\n'
            '#include "../rf/hud.h"\n'
            '#include <unordered_map>\n'
            '#include <string>\n'
            '#include <string_view>\n'
            '#include <cctype>\n'
            '#include <cmath>\n'
            '#include <vector>\n'
            '// gr_font.h, not gr.h: split_str / string_aligned / get_font_height /\n'
            '// load_font live there, and rf/hud.h only pulls in gr/gr.h.\n'
            '#include "../rf/gr/gr_font.h"\n'
            '\n'
            '// Defined further down, next to the subtitle table. Alpine already hooks both\n'
            '// snd_play and snd_play_3d, so we call into it from those hooks rather than\n'
            '// installing a second FunHook on the same address -- two hooks on one function\n'
            '// means whichever installs last silently wins.\n'
            'static void npc_subtitle_on_play(int handle, const rf::Vector3* pos);\n'
            'static void cutscene_subtitle_begin(const char* track);\n'
            '\n'
            'static int g_cutscene_bg_sound_sig = -1;\n',
        why='NPC 字幕: 补齐头文件与前向声明',
    ),
    dict(
        file='game_patch/sound/sound.cpp',
        old='        if (rf::snd_load_hint(handle) != 0) {\n'
            '            xlog::warn("Failed to load sound {}", handle);\n'
            '            return -1;\n'
            '        }\n'
            '\n'
            '        float vol_scale = volume * rf::snd_group_volume[group];\n',
        new='        if (rf::snd_load_hint(handle) != 0) {\n'
            '            xlog::warn("Failed to load sound {}", handle);\n'
            '            return -1;\n'
            '        }\n'
            '\n'
            '        npc_subtitle_on_play(handle, nullptr);\n'
            '\n'
            '        float vol_scale = volume * rf::snd_group_volume[group];\n',
        why='NPC 字幕: 接入 snd_play (2D)',
    ),
    dict(
        file='game_patch/sound/sound.cpp',
        old='        if (rf::snd_load_hint(handle) != 0) {\n'
            '            xlog::warn("Failed to load sound {}", handle);\n'
            '            return -1;\n'
            '        }\n'
            '\n'
            '\n'
            '        bool looping = rf::sounds[handle].is_looping;\n',
        new='        if (rf::snd_load_hint(handle) != 0) {\n'
            '            xlog::warn("Failed to load sound {}", handle);\n'
            '            return -1;\n'
            '        }\n'
            '\n'
            '        npc_subtitle_on_play(handle, &pos);\n'
            '\n'
            '        bool looping = rf::sounds[handle].is_looping;\n',
        why='NPC 字幕: 接入 snd_play_3d',
    ),
    dict(
        file='game_patch/hud/multi_hud.cpp',
        old='FunHook<void()> hud_msg_render_hook{\n'
            '    0x004382D0,\n'
            '    [] {\n'
            '        if (!g_remote_server_cfg_popup.is_active()) {\n'
            '            hud_msg_render_hook.call_target();\n'
            '        }\n'
            '    },\n'
            '};\n',
        new='// Defined in sound.cpp. Alpine already hooks 0x004382D0, so the voice subtitle\n'
            '// channel draws from inside that hook rather than installing a second one --\n'
            '// two FunHooks on one address means whichever installs last silently wins.\n'
            'extern void npc_subtitle_render();\n'
            '\n'
            'FunHook<void()> hud_msg_render_hook{\n'
            '    0x004382D0,\n'
            '    [] {\n'
            '        if (!g_remote_server_cfg_popup.is_active()) {\n'
            '            hud_msg_render_hook.call_target();\n'
            '        }\n'
            '        npc_subtitle_render();\n'
            '    },\n'
            '};\n',
        why='NPC 字幕: 独立渲染通道接入每帧 HUD 绘制',
    ),
    # 即时演算过场里 HUD 整个不画, 上面那条挂在 hud_msg_render 上的通道自然没机会
    # 跑 —— 格里芬办公室那场就一句字幕都没有。过场有自己的每帧函数, 得另外接一次。
    # 同样搭 Alpine 现成的钩子, 不新开。
    dict(
        file='game_patch/object/cutscene.cpp',
        old='        if (!skip_cutscene) {\n'
            '            cutscene_do_frame_hook.call_target(dlg_open);\n'
            '            render_skip_cutscene_hint_text(skip_cutscene_ctrl);\n'
            '        }\n',
        new='        if (!skip_cutscene) {\n'
            '            cutscene_do_frame_hook.call_target(dlg_open);\n'
            '            render_skip_cutscene_hint_text(skip_cutscene_ctrl);\n'
            '            // HUD is not drawn during cutscenes, so the voice subtitle channel\n'
            '            // has to be driven from here as well. npc_subtitle_render() skips\n'
            '            // repeat calls within the same frame, so this is safe even if the\n'
            '            // HUD path happens to run too.\n'
            '            npc_subtitle_render();\n'
            '        }\n',
        why='NPC 字幕: 即时演算过场里也要画 (过场时 HUD 不绘制)',
    ),
    # 诊断: 过场对白不走 snd_play/snd_play_3d —— 日志证明钩子完全看不到它们。
    # Alpine 自己在 0x00505D70 挂了 snd_music_play_cutscene_hook, 说明过场音频是当
    # "音乐"流式播放的。搭这个现成钩子记一下文件名, 看是整段混音还是逐句播放:
    #   逐句 -> 直接按文件名查表出字幕
    #   整段 -> 只能自己排时间轴
    dict(
        file='game_patch/sound/sound.cpp',
        old='    [](const char *filename, float volume) {\n'
            '        g_cutscene_bg_sound_sig = snd_music_play_cutscene_hook.call_target(filename, volume);\n',
        new='    [](const char *filename, float volume) {\n'
            '        cutscene_subtitle_begin(filename);\n'
            '        g_cutscene_bg_sound_sig = snd_music_play_cutscene_hook.call_target(filename, volume);\n',
        why='过场字幕: 记下音轨名与开播时刻',
    ),
    dict(
        file='game_patch/object/cutscene.cpp',
        old='#include "../sound/sound.h"\n\nstatic constexpr rf::ControlConfigAction',
        new='#include "../sound/sound.h"\n\n'
            '// Defined in sound.cpp\n'
            'extern void npc_subtitle_render();\n\n'
            'static constexpr rf::ControlConfigAction',
        why='NPC 字幕: cutscene.cpp 前向声明',
    ),
    dict(
        file='game_patch/sound/sound.cpp',
        old='extern void sound_foley_apply_patches();\n'
            '\n'
            'void apply_sound_patches()\n',
        new='extern void sound_foley_apply_patches();\n'
            '\n'
            + NPCSUB_HELPERS
            + 'void apply_sound_patches()\n',
        why='NPC 字幕: 字幕表加载与显示',
    ),
]


# ---------------------------------------------------------------------------
# 断行修复: 引擎的 gr_split_str 对 UTF-8 和 TTF 字体都是失效的
#
# gr_split_str (0x00520810) 是原版引擎的断行器, 它按字节遍历字符串, 从引擎自己的
# fonts[] 表里查字宽, 并且只在空格处断行。两点都对我们不成立:
#
#   * TTF 字体号是 0x1000|n, 在引擎的 fonts[] 里根本不存在 -> 查出来是垃圾宽度
#   * 中文没有空格 -> 永远找不到断点
#
# 消息记录 (M 键) 入库时用它算行数, 再把 (行数+1)x字高 存进消息结构 +0x106,
# 绘制时靠这个值递增 y。所以一个错误同时造成两个现象: 行太长撑出框外, 条目
# 高度算错互相重叠。persona 消息和弹窗也走同一个函数。
#
# 这里换成按码点遍历、用 rf::gr::get_string_size 量宽度 (那个是我们钩过的,
# 认得 TTF), 并允许在汉字之间断行, 同时保留西文按空格断词。
# ---------------------------------------------------------------------------
LINEBREAK_HELPERS = r'''
// ---- CJK aware line breaking ----
// See gr_split_str_hook below. Break opportunities follow the usual CJK rules: a line
// may break between two ideographs, but never before closing punctuation nor after
// opening punctuation.
static bool cjk_breakable(uint32_t cp)
{
    return (cp >= 0x2E80 && cp <= 0x9FFF)      // radicals, kana, CJK ideographs
        || (cp >= 0xF900 && cp <= 0xFAFF)      // compatibility ideographs
        || (cp >= 0x3000 && cp <= 0x303F)      // CJK punctuation
        || (cp >= 0xFF00 && cp <= 0xFF60);     // fullwidth forms
}

static bool cjk_no_break_before(uint32_t cp)
{
    switch (cp) {
    case 0x3001: case 0x3002: case 0xFF0C: case 0xFF0E:
    case 0xFF1A: case 0xFF1B: case 0xFF01: case 0xFF1F:
    case 0x300D: case 0x300F: case 0x3011: case 0x300B:
    case 0xFF09: case 0x2019: case 0x201D:
        return true;
    default:
        return false;
    }
}

static bool cjk_no_break_after(uint32_t cp)
{
    switch (cp) {
    case 0x300C: case 0x300E: case 0x3010: case 0x300A:
    case 0xFF08: case 0x2018: case 0x201C:
        return true;
    default:
        return false;
    }
}

// Replacement for the engine's gr_split_str. Fills offset_array/len_array with byte
// offsets and lengths of each line and returns the line count, same contract as the
// original. unk_char is ignored: its meaning in the original is unclear and every
// caller we can see passes 0. A newline always breaks, as it did before.
FunHook<int(int*, int*, char*, int, int, char, int)> gr_split_str_hook{
    0x00520810,
    [](int* len_array, int* offset_array, char* text, int max_w, int max_lines, char unk_char,
       int font_num) -> int {
        static_cast<void>(unk_char);
        if (!text || !len_array || !offset_array || max_lines <= 0 || max_w <= 0) {
            return 0;
        }
        const std::string_view sv{text};
        int n_lines = 0;
        size_t line_start = 0;
        size_t pos = 0;
        int line_w = 0;
        size_t break_end = 0;   // where the line would end if we break here
        size_t break_next = 0;  // where the following line would start
        uint32_t prev_cp = 0;
        size_t prev_pos = 0;

        auto emit = [&](size_t end, size_t next) {
            offset_array[n_lines] = static_cast<int>(line_start);
            len_array[n_lines] = static_cast<int>(end - line_start);
            ++n_lines;
            line_start = next;
            pos = next;
            line_w = 0;
            break_end = 0;
            break_next = 0;
            prev_cp = 0;
            prev_pos = 0;
        };

        while (pos < sv.size() && n_lines < max_lines) {
            size_t next = pos;
            const uint32_t cp = utf8_decode(sv, next);

            if (cp == static_cast<uint32_t>('\n')) {
                emit(pos, next);
                continue;
            }

            // Record a break opportunity for the pair (prev_cp, cp) before placing cp,
            // so that when cp turns out not to fit we already know where to cut.
            if (prev_cp == static_cast<uint32_t>(' ')) {
                break_end = prev_pos;   // the space itself is dropped
                break_next = pos;
            }
            else if (prev_cp && !cjk_no_break_after(prev_cp) && !cjk_no_break_before(cp)
                     && (cjk_breakable(prev_cp) || cjk_breakable(cp))) {
                break_end = pos;
                break_next = pos;
            }

            const int cw = rf::gr::get_string_size(sv.substr(pos, next - pos), font_num).first;
            if (line_w + cw > max_w && pos > line_start) {
                if (break_end > line_start) {
                    emit(break_end, break_next);
                }
                else {
                    emit(pos, pos);   // one word wider than the whole line: hard cut
                }
                continue;
            }

            line_w += cw;
            prev_cp = cp;
            prev_pos = pos;
            pos = next;
        }

        if (line_start < sv.size() && n_lines < max_lines) {
            offset_array[n_lines] = static_cast<int>(line_start);
            len_array[n_lines] = static_cast<int>(sv.size() - line_start);
            ++n_lines;
        }
        return n_lines;
    },
};

'''

MSGLOG_HELPERS = r'''
// ---------------------------------------------------------------------------
// Message log text layout
//
// Alpine scales the message log background and clip rectangle to the current
// resolution, but the text inside is still laid out with the original 640x480
// constants: the speaker name goes at x=5, the message body at x=70, and the body
// is split to a width of about 240. At 4K that is a 70 pixel name column inside an
// 1878 pixel box, so the speaker name runs straight into the message text.
//
// Separately, the per entry height stored at +0x106 when a message is added is
// (line count + 1) x gr_get_font_height(-1), i.e. measured with the *default* font,
// while the body is drawn with rfpc-medium.vf. Once a localization redirects the
// bitmap fonts to a TTF those differ, so entries overlap and the scroll arithmetic
// (0x00454F53 / 0x004550BC sum the same field) stops working. Fixing the stored
// value covers drawing and scrolling at once.
// ---------------------------------------------------------------------------

static auto& message_log_font = addr_as_ref<int>(0x006C66F0);

static float message_log_ui_scale()
{
    return rf::gr::screen_width() / 640.0f;
}

// The font the log body is drawn with. 0x006C66F0 is set when the log UI is created;
// before that (a message can arrive earlier) fall back to loading it by name. Do not
// call load_font on every entry: the .vf redirect logs a line on each call.
static int message_log_body_font()
{
    if (message_log_font) {
        return message_log_font;
    }
    static int fallback = rf::gr::load_font("rfpc-medium.vf");
    return fallback;
}

// Height of one entry as actually rendered. The extra font height reproduces the
// blank line the original left between entries.
static int message_log_entry_height(const char* text)
{
    if (!text) {
        return 0;
    }
    const int font = message_log_body_font();
    return rf::gr::get_string_size(text, font).second + rf::gr::get_font_height(font);
}

// All four readers of the stored height, recomputed from the text that will actually
// be drawn. Patching the readers rather than the stored value makes this independent
// of where the value came from -- savegames carry it across sessions, so a value
// written by a different build would otherwise survive.
// Each site is a 7 byte `movsx <reg>, word ptr [<ptr> + 0x106]`; we set the
// destination register and resume after the instruction.

// Draw: is this entry within the visible area? (entry in esi -> eax)
CodeInjection message_log_height_visible_injection{
    0x00455315,
    [](auto& regs) {
        const char* text = regs.esi;
        regs.eax = message_log_entry_height(text);
        regs.eip = 0x0045531C;
    },
};

// Draw: advance y to the next entry. (entry in esi -> eax)
CodeInjection message_log_height_advance_injection{
    0x00455421,
    [](auto& regs) {
        const char* text = regs.esi;
        regs.eax = message_log_entry_height(text);
        regs.eip = 0x00455428;
    },
};

// Scroll: total height of the entries below the current position. (entry in eax -> eax)
CodeInjection message_log_height_scroll_sum_injection{
    0x00454F53,
    [](auto& regs) {
        const char* text = regs.eax;
        regs.eax = message_log_entry_height(text);
        regs.eip = 0x00454F5A;
    },
};

// Scroll: height of the last entry, to decide whether it fits. (entry in eax -> edx)
CodeInjection message_log_height_scroll_last_injection{
    0x004550BC,
    [](auto& regs) {
        const char* text = regs.eax;
        regs.edx = message_log_entry_height(text);
        regs.eip = 0x004550C3;
    },
};

// The engine splits the body to the unscaled 640x480 width and measures with the
// *default* font, while the body is drawn at 70 * scale with rfpc-medium.vf. Both
// have to match the real layout or lines come out too long and get clipped.
CallHook<int(int*, int*, char*, int, int, char, int)> message_log_add_split_str_hook{
    0x0043803F,
    [](int* len_array, int* offset_array, char* text, int max_w, int max_lines,
       char unk_char, int font_num) {
        static_cast<void>(max_w);
        static_cast<void>(font_num);
        // clip width 313 minus the 70 indent, minus a small right margin
        const int scaled_w = static_cast<int>(239.0f * message_log_ui_scale());
        return message_log_add_split_str_hook.call_target(
            len_array, offset_array, text, scaled_w, max_lines, unk_char,
            message_log_body_font());
    },
};

// Speaker name (x=5) and message body (x=70), both still in 640x480 coordinates.
CallHook<void(int, int, const char*, int, rf::gr::Mode)> message_log_name_string_hook{
    0x004553BA,
    [](int x, int y, const char* s, int font, rf::gr::Mode mode) {
        message_log_name_string_hook.call_target(
            static_cast<int>(x * message_log_ui_scale()), y, s, font, mode);
    },
};

CallHook<void(int, int, const char*, int, rf::gr::Mode)> message_log_body_string_hook{
    0x004553DD,
    [](int x, int y, const char* s, int font, rf::gr::Mode mode) {
        message_log_body_string_hook.call_target(
            static_cast<int>(x * message_log_ui_scale()), y, s, font, mode);
    },
};

'''

LINEBREAK_EDITS = [
    dict(
        file='game_patch/graphics/gr_font.cpp',
        old='    return text_w + suffix_w;\n'
            '};\n'
            '\n'
            'void gr_font_apply_patch()\n',
        new='    return text_w + suffix_w;\n'
            '};\n'
            '\n'
            + LINEBREAK_HELPERS
            + 'void gr_font_apply_patch()\n',
        why='断行: 加入 UTF-8/CJK 版 gr_split_str',
        # 这条的 new 尾部锚在 `void gr_font_apply_patch()` 上, 而 VEH_EDITS 会在
        # 同一处前面插入诊断代码, 把尾巴撑断 —— new 就不再逐字存在了。重跑脚本时
        # 只能靠这个独有符号判断本条是否已经生效, 否则会误报"上游代码已改动"。
        marker='static bool cjk_breakable(',
    ),
    dict(
        file='game_patch/graphics/gr_font.cpp',
        old='    gr_get_string_size_hook.install();\n'
            '    init_freetype_lib();\n',
        new='    gr_get_string_size_hook.install();\n'
            '    gr_split_str_hook.install();\n'
            '    init_freetype_lib();\n',
        why='断行: 安装 gr_split_str 钩子',
    ),
    dict(
        file='game_patch/hud/message_log.cpp',
        old='#include "../rf/gr/gr.h"\n'
            '\n'
            'static auto& message_log_bm_w',
        new='#include "../rf/gr/gr.h"\n'
            '#include "../rf/gr/gr_font.h"\n'
            '\n'
            'static auto& message_log_bm_w',
        why='消息记录: 引入 gr_font.h (量文字尺寸)',
    ),
    dict(
        file='game_patch/hud/message_log.cpp',
        old='void message_log_apply_patch()\n'
            '{\n'
            '    // Fix message log rendering in resolutions with ratio different than 4:3\n',
        new=MSGLOG_HELPERS
            + 'void message_log_apply_patch()\n'
              '{\n'
              '    message_log_height_visible_injection.install();\n'
              '    message_log_height_advance_injection.install();\n'
              '    message_log_height_scroll_sum_injection.install();\n'
              '    message_log_height_scroll_last_injection.install();\n'
              '    message_log_add_split_str_hook.install();\n'
              '    message_log_name_string_hook.install();\n'
              '    message_log_body_string_hook.install();\n'
              '\n'
              '    // Fix message log rendering in resolutions with ratio different than 4:3\n',
        why='消息记录: 条目高度实测 + 文字坐标/断行宽度按分辨率缩放',
    ),
]


# ---------------------------------------------------------------------------
# 上游 bug 修复: 格式串里的单字节 Windows-1252 字符
#
# Alpine 源码里有几处把 Windows-1252 的字节直接写进 std::format 的格式串:
#   "{} \x95 {}/{} PLAYING"        \x95 = 项目符号 •
#   "\xA6 Shot canceled: {}"       \xA6 = 断竖线 ¦ (聊天消息前缀)
#
# 在原版单字节世界里这没问题, 引擎的 .vf 位图字体就是按 Windows-1252 索引的。
# 但 MSVC 较新版本的 std::format **会把格式串按 UTF-8 校验**, 而 0x95/0xA6
# 都是非法的 UTF-8 前导字节 -> 抛 std::format_error。RF 自己的 __try/__except
# 把异常吞掉, 表现就是"进多人游戏后游戏直接消失"。
#
# 这跟汉化没有关系 —— 任何人用当前的 VS 2022 编译 1.3.0 都会中招, 官方发布的
# 二进制是用较老的 STL 编的所以没暴露。这几处是可以往上游提的纯 bug 修复。
#
# 修法分两种, 区别在于那个字节会不会上网络:
#   * 计分板 (纯显示)   -> 直接换成 UTF-8 的 \xe2\x80\xa2, 我们的渲染器认得
#   * 聊天前缀 (走协议) -> 保留原字节, 只把它移出格式串, 用字符串拼接
#     绝不能改成 UTF-8: 其它客户端/服务器用 string_istarts_with 比对这个前缀,
#     改了就是协议不兼容。
# ---------------------------------------------------------------------------
UPSTREAM_FIX_EDITS = [
    dict(
        file='game_patch/hud/multi_scoreboard.cpp',
        old='            "{} \\x95 {}/{} PLAYING",\n',
        new='            "{} \\xe2\\x80\\xa2 {}/{} PLAYING",\n',
        why='上游修复: 计分板模式行的项目符号改 UTF-8 (崩溃点)',
    ),
    dict(
        file='game_patch/hud/multi_scoreboard.cpp',
        old='            "{1} \\x95 {0:%Y} ({2}) by {3}",\n',
        new='            "{1} \\xe2\\x80\\xa2 {0:%Y} ({2}) by {3}",\n',
        why='上游修复: 计分板地图信息行的项目符号改 UTF-8',
    ),
    dict(
        file='game_patch/multi/alpine_packets.cpp',
        old='            send_chat_line_packet(std::format("\\xA6 {}", msg), &player);\n',
        new='            send_chat_line_packet(std::string("\\xA6 ") + std::string(msg), &player);\n',
        why='上游修复: 聊天前缀移出格式串 (保留原字节, 不破坏协议)',
    ),
    dict(
        file='game_patch/multi/multi.cpp',
        old='    auto message = std::format("\\xA6 Shot canceled: {}", reason);\n',
        new='    auto message = std::string("\\xA6 Shot canceled: ") + reason;\n',
        why='上游修复: 同上, 射击取消提示',
    ),
]




# 诊断: 记录被 RF 自己的 SEH 吞掉的异常。
#
# RF 把大段帧循环包在自己的 __try/__except 里, 里面抛出的异常会让日志直接断在半截 ——
# 没有错误行, 没有栈。crash_handler_stub 用的 SetUnhandledExceptionFilter 按定义只对
# "没人处理的异常"生效, 也看不到。VEH 跑在所有 SEH 帧之前, 才能抢在 RF 吞掉之前记录。
#
# 这份代码已整理成独立文件提交给上游 (见 rf_cn/upstream-pr-veh/)。本地这份和 PR 里
# 那份**内容完全一致** —— 直接读同一个文件, 不做第二份拷贝, 免得两边改出分歧。
# 上游合并后把这组编辑删掉即可。
#
# 出正式版时用 --no-veh 关掉。
def _veh_source():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(os.path.dirname(here), 'upstream-pr-veh', 'exception_logger.cpp')
    with open(path, encoding='utf-8', newline='') as f:
        return f.read().replace('\r\n', '\n')


VEH_EDITS = [
    dict(
        file='game_patch/debug/exception_logger.cpp',
        create=_veh_source(),
        why='诊断: 新增 exception_logger.cpp (VEH 异常记录器)',
    ),
    # 下面两条的锚点都**必须往下多含一行**。只写到插入点为止的话 old 会变成 new 的
    # 前缀, 重跑时 old 仍然匹配得上, 于是又插一遍。
    dict(
        file='game_patch/debug/debug.h',
        old='void debug_init();\nvoid debug_cleanup();\n',
        new='void debug_init();\nvoid exception_logger_init();\nvoid debug_cleanup();\n',
        why='诊断: debug.h 声明 exception_logger_init',
    ),
    dict(
        file='game_patch/CMakeLists.txt',
        old='    debug/debug.cpp\n    debug/obj_debug.cpp\n',
        new='    debug/debug.cpp\n    debug/exception_logger.cpp\n    debug/obj_debug.cpp\n',
        why='诊断: exception_logger.cpp 加入构建',
    ),
    dict(
        file='game_patch/main/main.cpp',
        old='    // Init modules\n    console_apply_patches();\n',
        new='    // Init modules\n    exception_logger_init();\n    console_apply_patches();\n',
        why='诊断: 最先安装 VEH, 覆盖后续全部初始化过程',
    ),
]


EDITS += [
    # ---- H. hud_fit_string ----
    dict(
        file='game_patch/hud/hud.cpp',
        old='    while (str_w > max_w) {\n'
            '        result = result.substr(0, result.size() - (has_ellipsis ? 4 : 1)) + "...";\n'
            '        has_ellipsis = true;\n'
            '        std::tie(str_w, str_h) = rf::gr::get_string_size(result, font_id);\n'
            '    }\n',
        new='    while (str_w > max_w) {\n'
            '        if (has_ellipsis) {\n'
            '            result.erase(result.size() - 3);  // drop the "..." added last round\n'
            '        }\n'
            '        if (result.empty()) {\n'
            '            break;\n'
            '        }\n'
            '        // Step back one whole code point, never split a multi-byte character\n'
            '        size_t cut = result.size() - 1;\n'
            '        while (cut > 0 && (static_cast<unsigned char>(result[cut]) & 0xC0) == 0x80) {\n'
            '            --cut;\n'
            '        }\n'
            '        result.erase(cut);\n'
            '        result += "...";\n'
            '        has_ellipsis = true;\n'
            '        std::tie(str_w, str_h) = rf::gr::get_string_size(result, font_id);\n'
            '    }\n',
        why='HUD 字符串截断改为码点对齐',
    ),
]

# 需要上下文才能安全替换的字符串 (短词直接全局替换会误伤别处代码)
#
# 这里的中文必须经 _v() 登记 —— build_all.py 会读 VALUE_TEXTS 把这些字并入字符集。
# 漏登记的后果不是报错, 而是字体里没有对应字形, 引擎静默跳过, 界面上凭空少字。
VALUE_TEXTS = []


def _v(zh):
    """登记一段中文并返回它的 C++ 转义形式"""
    VALUE_TEXTS.append(zh)
    return c_escape(zh)


def _arr(decl, *zh_words):
    """生成 `decl = {"译文1", "译文2", ...};` 形式的替换文本"""
    body = ', '.join(f'"{_v(w)}"' for w in zh_words)
    return f'{decl} = {{{body}}};'


# weapons.tbl 里少数武器没有 $Display Name: 字段, 引擎就回落到 $Name: 的英文原文。
# 那条路**不经过 strings.tbl 的 XSTR 通道**, 所以 strings.tbl 翻得再全也没用;
# 而 weapons.tbl 不在 client_mods 的 tbl 覆盖白名单里 (只放行 strings/hud/
# hud_personas/personas/credits/endgame/ponr 和 *_text.tbl), 也没法用 vpp 顶掉。
# 只能在 DLL 侧, 等表解析完之后把 display_name 直接改掉。
#
# 时机很关键: 必须在 weapons.tbl 全部读完之后。这里搭 Alpine 现成的
# weapon_init_track_reticle_bitmap_injection (0x004C6756) 的车 —— 它本来就是
# 遍历全部 64 条武器定义的, 说明那时表已经齐了。**不要另开一个 CodeInjection
# 挂同一地址**, 两个钩子挂同一处时后装的会把先装的悄悄顶掉。
#
# 实际受影响的只有起爆器一个: 原版全部 player_wep 武器里只有它缺 $Display Name。
# Vauss、坦克机枪那些同样缺, 但都是 NPC/载具武器, 玩家武器轮盘里不会出现。
_DETONATOR_FIX = '''static void weapon_cn_fix_display_names()
{
    static const struct { const char* en; const char* zh; } cn_names[] = {
        {"Remote Charge Detonator", "%s"},
    };
    for (int i = 0; i < rf::num_weapon_types && i < 64; ++i) {
        rf::WeaponInfo& wi = rf::weapon_types[i];
        for (const auto& e : cn_names) {
            // With no $Display Name: the engine may leave display_name empty or copy
            // $Name: into it, so accept either. rf::String::operator== does the strcmp
            // and handles a null buffer, which saves pulling in <cstring>.
            if (wi.display_name == e.en || (wi.display_name.empty() && wi.name == e.en)) {
                wi.display_name = e.zh;
                break;
            }
        }
    }
}

''' % _v('起爆器')


VALUE_EDITS = [
    dict(
        file='game_patch/object/weapon.cpp',
        old=('CodeInjection weapon_init_track_reticle_bitmap_injection{\n'
             '    0x004C6756,\n'
             '    [](auto& regs) {\n'
             '        weapon_reticle_custom_mask.fill(0);\n'),
        new=(_DETONATOR_FIX +
             'CodeInjection weapon_init_track_reticle_bitmap_injection{\n'
             '    0x004C6756,\n'
             '    [](auto& regs) {\n'
             '        weapon_cn_fix_display_names();\n'
             '        weapon_reticle_custom_mask.fill(0);\n'),
        why='起爆器武器名: weapons.tbl 无 $Display Name, 只能在 DLL 侧改',
    ),
    dict(
        file='game_patch/input/mouse.cpp',
        old='static constexpr const char* mode_names[] = {"Classic", "Raw", "Modern"};',
        new=_arr('static constexpr const char* mode_names[]', '经典', '原始', '现代'),
        why='鼠标缩放模式: 经典/原始/现代',
    ),
    dict(
        file='game_patch/misc/ui.cpp',
        old='static constexpr const char* camscale_mode_names[] = {"Classic", "Raw", "Modern"};',
        new=_arr('static constexpr const char* camscale_mode_names[]', '经典', '原始', '现代'),
        why='镜头缩放模式: 经典/原始/现代',
    ),
    dict(
        file='game_patch/misc/ui.cpp',
        old='static constexpr const char* meshlight_mode_names[] = {"Ambient", "Vertex", "Pixel"};',
        new=_arr('static constexpr const char* meshlight_mode_names[]',
                 '环境光', '顶点', '逐像素'),
        why='网格光照模式: 环境光/顶点/逐像素',
    ),
    # ao_aa_btn_label_text 是 static char[8], 只装得下 2 个汉字 (6 字节 + 结束符)。
    # 想改成 3 个字就会溢出, 改这两行时务必先数字节。
    dict(
        file='game_patch/misc/ui.cpp',
        old='        strcpy(ao_aa_btn_label_text, "Error");',
        new=f'        strcpy(ao_aa_btn_label_text, "{_v("错误")}");',
        why='抗锯齿状态: Error -> 错误 (buf[8] 上限 2 汉字)',
        optional=True,
    ),
    dict(
        file='game_patch/misc/ui.cpp',
        old='            strcpy(ao_aa_btn_label_text, "None");',
        new=f'            strcpy(ao_aa_btn_label_text, "{_v("关闭")}");',
        why='抗锯齿状态: None -> 关闭 (buf[8] 上限 2 汉字)',
        optional=True,
    ),
]

# 高级选项面板的标签页文字偏移。原值是按英文宽度逐个手调的
# (Visual 27 / Interface 18 / Input 29 / Misc 30), 换成等宽的两字中文后
# 就参差不齐了 —— "界面" 明显偏左。统一成 28。
TAB_OFFSET_EDITS = [
    dict(file='game_patch/misc/ui.cpp',
         old=f'== {i}, {x}, 0, {old_off},',
         new=f'== {i}, {x}, 0, 28,',
         why=f'标签页 {i} 文字偏移 {old_off} -> 28')
    for i, x, old_off in [(0, 107, 27), (1, 199, 18), (2, 291, 29), (3, 383, 30)]
    if old_off != 28
]

# 可选改动: 让普通 HUD 也走 TTF
BIG_HUD_EDITS = [
    dict(
        file='game_patch/hud/hud.cpp',
        old='    return "rfpc-small.vf";',
        new='    return "regularfont.ttf:11";  // was rfpc-small.vf; bitmap fonts cannot show CJK',
        why='普通 HUD 小字体改用 TTF',
    ),
    dict(
        file='game_patch/hud/hud.cpp',
        old='    return "rfpc-medium.vf";',
        new='    return "regularfont.ttf:13";  // was rfpc-medium.vf',
        why='普通 HUD 默认字体改用 TTF',
    ),
    dict(
        file='game_patch/hud/hud.cpp',
        old='    return "rfpc-large.vf";',
        new='    return "boldfont.ttf:20";  // was rfpc-large.vf',
        why='普通 HUD 粗体改用 TTF',
    ),
]

# ---------------------------------------------------------------- Alpine 自有 UI 文本

def load_ui_edits():
    """从 alpine_ui.tsv 生成源码字符串替换.

    三列: 源文件 / 英文 / 中文。译文为空或与英文相同的条目跳过。
    """
    if not os.path.exists(UI_TSV):
        return []
    edits = []
    with open(UI_TSV, encoding='utf-8') as f:
        next(f)
        for line in f:
            line = line.rstrip('\n').rstrip('\r')
            if not line:
                continue
            parts = line.split('\t')
            if len(parts) != 3:
                continue
            path, en, zh = parts
            if not zh or zh == en:
                continue
            edits.append(dict(
                file=path,
                old=f'"{en}"',
                new=f'"{c_escape(zh)}"',
                why=f'UI 文本: {en} -> {zh}',
                allow_multi=True,
                optional=True,   # 见下方 optional 的说明
            ))
    return edits


# ---------------------------------------------------------------- 执行


def read_source(path):
    """读文件并归一化成 LF, 同时返回原本的换行风格.

    在 Windows 上 git checkout 出来的是 CRLF, 而补丁里的字符串是 LF,
    不归一化的话所有匹配都会失败。写回时按原样还原, 不制造无谓的全文件 diff。
    """
    with open(path, encoding='utf-8', newline='') as f:
        raw = f.read()
    crlf = raw.count('\r\n')
    lf_only = raw.count('\n') - crlf
    newline = '\r\n' if crlf > lf_only else '\n'
    return raw.replace('\r\n', '\n'), newline


def write_source(path, text, newline):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text.replace('\n', newline) if newline == '\r\n' else text)


def check_idempotent(root, edits):
    """对着**已打好补丁**的源码检查: 再跑一遍脚本时每条编辑还认得出来吗。

    为什么需要这个检查:
        两条编辑挑同一处当锚点时会互相干扰。A 先插入代码, B 又在 A 的 new 尾部
        动刀 —— A 的 new 就不再逐字存在了。第一次打补丁没事 (顺序对就都能生效),
        但重跑时 A 既匹配不到 old 也匹配不到 new, 会报"上游代码已改动", 吓人
        且不实; 撤销时同样卡住。给 A 加个 marker 就能解决 (见 apply())。

        静态比对两条编辑的字符串抓不到这种情况 —— B 的 old 并不是 A 的 new 的
        子串, 它们只是**首尾重叠**。所以只能对着真实文件验。

    用法: python apply_patch.py <源码目录> --check
    """
    cache = {}
    lost = []
    for e in edits:
        path = os.path.join(root, e['file'].replace('/', os.sep))
        if 'create' in e:
            # 整个文件都是我们的, 存在且内容一致就是已应用
            if os.path.exists(path) and read_source(path)[0] != e['create']:
                lost.append(e)
            continue
        if not os.path.exists(path):
            continue
        if path not in cache:
            cache[path] = read_source(path)[0]
        text = cache[path]
        marker = e.get('marker')
        if e['new'] in text or e['old'] in text or (marker and marker in text):
            continue
        if e.get('optional'):
            continue
        lost.append(e)
    return lost


def apply_create(path, content, revert):
    """处理 create 型编辑 (我们自己新增的源文件)。返回 'ok' / 'skip'。

    这类编辑没有 old/new 可匹配 —— 整个文件都是我们加的, 撤销就是删掉它。
    """
    exists = os.path.exists(path)
    if revert:
        if not exists:
            return 'skip'
        try:
            os.remove(path)
        except OSError as exc:
            # 删不掉不该让整个撤销中断 —— 引用它的那条构建配置照样会被撤掉,
            # 留下的只是个没人引用的孤儿文件。
            print(f'    ! 删除失败, 请手动删掉 {path}: {exc}')
            return 'ok'
        return 'ok'
    if exists and read_source(path)[0] == content:
        return 'skip'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 换行风格跟同目录既有文件保持一致, 免得 git 里显示成整文件改动
    newline = '\n'
    sibs = [f for f in os.listdir(os.path.dirname(path))
            if f.endswith(('.cpp', '.h')) and f != os.path.basename(path)]
    if sibs:
        newline = read_source(os.path.join(os.path.dirname(path), sibs[0]))[1]
    write_source(path, content, newline)
    return 'ok'


def apply(root, edits, revert=False):
    # 前置硬性检查: old 绝不能是 new 的连续子串。
    # 否则打完补丁 old 仍然匹配得上, 重跑就再插一遍 —— 而且不会报错, 只是文件里
    # 悄悄多出重复的行。这个坑很容易踩 (锚点只写到插入点为止就中招), 所以在这里拦死。
    broken = [e for e in edits if 'create' not in e and e['old'] in e['new']]
    if broken:
        print('  ✗ 编辑定义有误, old 是 new 的子串 (重跑会重复插入):')
        for e in broken:
            print(f'     {e["why"]}  ({e["file"]})')
        print('     修法: 锚点往下多含一行, 让插入的内容夹在中间。')
        return False

    # 前置硬性检查二: 注入的 C++ 必须是纯 ASCII (中文一律走 _v() 转成 \xNN 转义)。
    #
    # 源码是 UTF-8 无 BOM, 而 MSVC 在中文/日文 Windows 上按系统代码页读它。注释里
    # 的汉字在 Shift-JIS 下会被当成双字节序列, 行尾那个字的末字节是前导字节, 就要
    # 吃掉下一个字节当后续字节:
    #     CRLF 时吃掉 \r, \n 还在 -> 侥幸能编译
    #     LF   时吃掉 \n         -> 注释吞掉下一行, 语法崩掉
    # 也就是说带中文注释的代码能不能编译, 取决于工作树是什么换行符 —— 这种雷不能留。
    # (这和我们报给上游的 #399 是同一个成因: DBCS 前导字节。)
    non_ascii = []
    for e in edits:
        text = e.get('create', e.get('new', ''))
        bad = sorted({c for c in text if ord(c) > 127})
        if bad:
            non_ascii.append((e, bad))
    if non_ascii:
        print('  ✗ 注入的代码含非 ASCII 字符 (换行符一变就可能编译失败):')
        for e, bad in non_ascii:
            print(f'     {e["why"]}  ({e["file"]})')
            print(f'       {"".join(bad)[:60]}')
        print('     修法: 注释改英文; 要显示的中文用 _v() 转义成 \\xNN。')
        return False

    ok = skipped = missing = 0
    # 撤销必须倒序 —— 后加的编辑可能压在先加的编辑之上, 先撤外层才能露出内层。
    for e in (list(reversed(edits)) if revert else edits):
        path = os.path.join(root, e['file'].replace('/', os.sep))
        if 'create' in e:
            res = apply_create(path, e['create'], revert)
            if res == 'skip':
                print(f'  - 已是目标状态, 跳过: {e["why"]}')
                skipped += 1
            else:
                print(f'  ✓ {e["why"]}')
                ok += 1
            continue
        if not os.path.exists(path):
            print(f'  ✗ 找不到文件: {e["file"]}')
            return False
        text, newline = read_source(path)
        src, dst = (e['new'], e['old']) if revert else (e['old'], e['new'])
        if text.count(src) == 0:
            # marker: 这条编辑引入的独有标识。当它的 new 尾部被后续编辑改写时,
            # new 已不再逐字存在, 只能靠 marker 判断这条到底应用过没有。
            marker = e.get('marker')
            if text.count(dst) > 0 or (marker and not revert and marker in text):
                print(f'  - 已是目标状态, 跳过: {e["why"]}')
                skipped += 1
                continue
            # optional 的条目允许找不到 —— 它们对应的功能可能在这个版本还不存在。
            # 比如喷漆选择器、观战镜头是 1.3.0 之后才加的, 按 v1.3.0 tag 编译时
            # 自然匹配不到。这类缺失只影响个别界面文字, 不该让整个补丁失败。
            # 引擎改造那些是硬性的, 缺一个就不能显示中文, 所以仍然硬失败。
            if e.get('optional'):
                print(f'  · 跳过 (此版本无此项): {e["why"]}')
                missing += 1
                continue
            print(f'  ✗ 匹配失败: {e["why"]}\n     在 {e["file"]} 里找不到预期的原文。'
                  f'上游代码可能已改动, 需要人工核对。')
            return False
        n_found = text.count(src)
        if n_found > 1 and not e.get('allow_multi'):
            print(f'  ✗ 匹配到 {n_found} 处 (预期 1 处): {e["why"]}')
            return False
        write_source(path, text.replace(src, dst), newline)
        suffix = f' ({n_found} 处)' if n_found > 1 else ''
        print(f'  ✓ {e["why"]}{suffix}')
        ok += 1
    tail = f', {missing} 处此版本不适用' if missing else ''
    print(f'  共 {ok} 处改动, {skipped} 处已存在{tail}')
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('root', help='alpinefaction 源码根目录')
    ap.add_argument('--revert', action='store_true', help='撤销补丁')
    ap.add_argument('--big-hud-only-off', action='store_true',
                    help='额外让普通 HUD 也用 TTF (否则关掉 Big HUD 时中文会消失)')
    ap.add_argument('--no-ui-strings', action='store_true',
                    help='不翻译 Alpine 自有的 UI 文本 (alpine_ui.tsv)')
    ap.add_argument('--no-vf-redirect', action='store_true',
                    help='不做 .vf -> TTF 重定向 (排查用: 那两个列表框会重新变乱码)')
    ap.add_argument('--no-veh', action='store_true',
                    help='不装异常记录器 (定位完崩溃后出正式版时用)')
    ap.add_argument('--check', action='store_true',
                    help='只检查已打补丁的源码能否再次识别 (不改动任何文件)')
    args = ap.parse_args()

    if not os.path.isdir(os.path.join(args.root, 'game_patch')):
        print(f'{args.root} 看起来不是 alpinefaction 源码目录 (没有 game_patch/)')
        return 1

    edits = (list(EDITS) + FONT_GUARD_EDITS + FONT_CATCH_EDITS + UPSTREAM_FIX_EDITS
             + LINEBREAK_EDITS + NPCSUB_EDITS)
    if not args.no_veh:
        edits += VEH_EDITS
        print('（含异常记录器, 出正式版时用 --no-veh 关掉）')
    if not args.no_vf_redirect:
        edits += VF_REDIRECT_EDITS
    else:
        print('（已关闭 .vf -> TTF 重定向）')
    if args.big_hud_only_off:
        edits += BIG_HUD_EDITS
    if not args.no_ui_strings:
        ui_edits = load_ui_edits() + VALUE_EDITS + TAB_OFFSET_EDITS
        edits += ui_edits
        print(f'（含 Alpine 自有 UI 文本 {len(ui_edits)} 条）')

    if args.check:
        lost = check_idempotent(args.root, edits)
        if lost:
            print(f'{len(edits)} 条编辑, 重跑时认不出来的 {len(lost)} 条 '
                  f'—— 给它们各加一个 marker:')
            for e in lost:
                print(f'  ! {e["why"]}  ({e["file"]})')
            return 1
        print(f'{len(edits)} 条编辑全部可重复识别, 重跑与撤销都安全。')
        return 0

    print('撤销补丁...' if args.revert else '打补丁...')
    if not apply(args.root, edits, args.revert):
        print('\n失败。已改动的部分不会自动回滚, 建议用 git checkout 还原后重试。')
        return 1
    print('\n完成。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
