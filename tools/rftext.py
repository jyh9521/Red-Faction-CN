#!/usr/bin/env python3
"""Red Faction 文本表 (.tbl) 提取 / 导出 / 回填工具.

处理三种文件:
  strings.tbl     UI/HUD/菜单文本   条目形如  #12 + En:/Gr:/Fr: "..."
  *_text.tbl      关卡语音字幕      条目形如  12  "xxx.wav" + En:/Gr:/Fr: "..."
  endgame.tbl     结局文本          条目形如  $Name: "eos" + En: ... #end

回填采用"逐行外科手术"策略: 只替换 En 行引号内的内容, 其余字节 (CRLF、
缩进、行尾空白、Gr/Fr 行) 原样保留, 保证空译文回填后与原文件完全一致.

子命令:
  extract <游戏目录> <工作目录>      从 vpp 中解出全部文本表
  export  <工作目录> <翻译目录>      生成待翻译 CSV
  apply   <工作目录> <翻译目录> <输出目录> [--encoding utf-8|gbk]
                                     把译文写回 tbl
  verify  <工作目录> <输出目录>      比对两个目录下的 tbl 是否字节一致
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vpp  # noqa: E402

RAW_ENC = 'latin1'  # 原文按单字节读写, 不做任何转换

# 需要提取的 vpp 及其中的文本表
SOURCES = [
    ('tables.vpp', ('strings.tbl', 'endgame.tbl', 'hud_personas.tbl')),
    ('levels1.vpp', ('_text.tbl',)),
    ('levels2.vpp', ('_text.tbl',)),
    ('levels3.vpp', ('_text.tbl',)),
]

LANG_RE = re.compile(r'^(En|Gr|Fr):(\s*)"(.*)"(\s*)$')
STRINGS_ID_RE = re.compile(r'^#(\d+)\s*$')
TEXT_ID_RE = re.compile(r'^(\d+)\s+"(.*)"\s*$')
NAME_RE = re.compile(r'^\$Name:\s*"(.*)"\s*$')
PERSONA_NAME_RE = re.compile(r'^(\s*\$Name:\s*")(.*)("\s*)$')
PERSONA_DISP_RE = re.compile(r'^(\s*\$Display Name:\s*")(.*)("\s*)$')

# 译文中必须原样保留的记号: 按键占位符 $USE$ / 格式符 %s %d / 转义 \n \t \v183
#
# 注意 \n 后面不能吞数字。原文里有 "at least\n620 KB" 这种写法 ——
# 那是换行符后面紧跟字面量 620, 不是 "\n620" 这一个记号。
# 只有 \v 才带数字参数 (\v183)。写成 \\[nvt][0-9]* 会把 \n620 误判成一个整体,
# 于是译文里明明 \n 和 620 都在, 却被报成"缺少记号"。
TOKEN_RE = re.compile(r'\$[A-Z_]+\$|%[-0-9.]*[sdif]|\\v[0-9]+|\\[nt]')


# ---------------------------------------------------------------- 读取

def read_lines(path):
    with open(path, 'r', encoding=RAW_ENC, newline='') as f:
        return f.read().split('\n')


def write_lines(path, lines, encoding=RAW_ENC):
    """逐行编码写出.

    未翻译的行含德/法文的 latin1 字节, 无法用 GBK 编码; 译文行则含中文.
    因此按行尝试目标编码, 失败再退回 latin1, 保证两类内容都能原样落盘.
    """
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    buf = bytearray()
    for i, line in enumerate(lines):
        if i:
            buf += b'\n'
        try:
            buf += line.encode(encoding)
        except UnicodeEncodeError:
            try:
                buf += line.encode(RAW_ENC)
            except UnicodeEncodeError as exc:
                raise ValueError(
                    f'{path}: 第 {i + 1} 行无法用 {encoding} 编码: {line!r}') from exc
    with open(path, 'wb') as f:
        f.write(buf)


def kind_of(filename):
    n = filename.lower()
    if n == 'strings.tbl':
        return 'strings'
    if n == 'endgame.tbl':
        return 'endgame'
    if n == 'hud_personas.tbl':
        return 'personas'
    if n.endswith('_text.tbl'):
        return 'text'
    return None


def parse_personas(lines):
    """解析 hud_personas.tbl.

    每个角色有 $Name (关卡引用的内部标识, **绝不能改**) 和可选的
    $Display Name (屏幕上实际显示的名字)。引擎的逻辑是:
    display_name 非空就用它, 否则回退到 name —— 所以汉化只动 $Display Name,
    没有的就新插一行, $Name 原样不碰。
    """
    out = []
    for i, raw in enumerate(lines):
        m = PERSONA_NAME_RE.match(raw.rstrip('\r'))
        if not m:
            continue
        name = m.group(2)
        disp_line = None
        disp = name
        # 往后找几行内的 $Display Name
        for j in range(i + 1, min(i + 4, len(lines))):
            nxt = lines[j].rstrip('\r')
            if PERSONA_NAME_RE.match(nxt):
                break
            dm = PERSONA_DISP_RE.match(nxt)
            if dm:
                disp_line, disp = j, dm.group(2)
                break
        out.append({'key': name, 'context': '角色名', 'en': disp,
                    'line': i, 'disp_line': disp_line, 'block': False,
                    'persona': True})
    return out


def parse(path):
    """返回 [{key, context, en, line}] , line 为 En 行在文件中的行号 (0 基)."""
    kind = kind_of(os.path.basename(path))
    lines = read_lines(path)
    if kind == 'personas':
        return parse_personas(lines)
    out = []
    key = context = None
    i = 0
    while i < len(lines):
        line = lines[i].rstrip('\r')

        if kind == 'strings':
            m = STRINGS_ID_RE.match(line)
            if m:
                key, context = m.group(1), ''
        elif kind == 'text':
            m = TEXT_ID_RE.match(line)
            if m:
                key, context = m.group(1), m.group(2)
        elif kind == 'endgame':
            m = NAME_RE.match(line)
            if m:
                key, context = m.group(1), '结局文本'
                # 收集 En: 到 #end 之间的整块
                if i + 1 < len(lines) and lines[i + 1].rstrip('\r') == 'En:':
                    j = i + 2
                    block = []
                    while j < len(lines) and lines[j].rstrip('\r') != '#end':
                        block.append(lines[j].rstrip('\r'))
                        j += 1
                    out.append({'key': key, 'context': context,
                                'en': '\\n'.join(block), 'line': i + 2,
                                'end': j, 'block': True})
                    i = j
                    key = None
            i += 1
            continue

        m = LANG_RE.match(line)
        if m and m.group(1) == 'En' and key is not None:
            out.append({'key': key, 'context': context or '',
                        'en': m.group(3), 'line': i, 'block': False})
            key = None
        i += 1
    return out


# ---------------------------------------------------------------- 命令

def cmd_extract(game_dir, work_dir):
    en_dir = os.path.join(work_dir, 'en')
    os.makedirs(en_dir, exist_ok=True)
    total = 0
    for pack_name, wanted in SOURCES:
        path = os.path.join(game_dir, pack_name)
        if not os.path.exists(path):
            print(f'  跳过 (不存在): {pack_name}')
            continue
        with open(path, 'rb') as f:
            for name, size, off in vpp.read_index(path):
                low = name.lower()
                if not any(low == w or low.endswith(w) for w in wanted):
                    continue
                f.seek(off)
                with open(os.path.join(en_dir, name), 'wb') as out:
                    out.write(f.read(size))
                total += 1
        print(f'  {pack_name} -> 提取完成')
    print(f'共提取 {total} 个文本表到 {en_dir}')
    return total


TSV_FIELDS = ['file', 'key', 'context', 'tokens', 'en', 'zh']


def edge_space(s):
    """标出首尾空格 —— 这些空格是有意义的, 不能吃掉.

    比如 "Viewing from " 末尾那个空格后面要拼接玩家名字, 丢了就会粘在一起。
    """
    tags = []
    if s[:1] == ' ':
        tags.append('首部空格')
    if s[-1:] == ' ':
        tags.append('末尾空格')
    return tags


def read_tsv(path):
    """读 TSV. 数据里不含制表符和换行, 所以不需要任何引号转义。"""
    rows = []
    with open(path, encoding='utf-8', newline='') as f:
        header = f.readline().rstrip('\n').rstrip('\r').split('\t')
        for lineno, line in enumerate(f, start=2):
            line = line.rstrip('\n').rstrip('\r')
            if not line:
                continue
            parts = line.split('\t')
            if len(parts) != len(header):
                raise ValueError(
                    f'{os.path.basename(path)} 第 {lineno} 行有 {len(parts)} 列, '
                    f'应为 {len(header)} 列。是不是译文里混进了制表符?')
            rows.append(dict(zip(header, parts)))
    return rows


def write_tsv(path, rows, fields=None):
    fields = fields or TSV_FIELDS
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('\t'.join(fields) + '\n')
        for r in rows:
            vals = []
            for k in fields:
                v = r.get(k) or ''
                if '\t' in v or '\n' in v or '\r' in v:
                    raise ValueError(f'字段 {k} 含制表符或换行, 无法写入 TSV: {v!r}')
                vals.append(v)
            f.write('\t'.join(vals) + '\n')


def _rows(en_dir, kinds):
    for name in sorted(os.listdir(en_dir)):
        if kind_of(name) not in kinds:
            continue
        for e in parse(os.path.join(en_dir, name)):
            yield name, e


def _mk_row(name, e):
    """一条待翻译记录. tokens 列同时标出首尾空格, 提醒译者别吃掉。"""
    marks = edge_space(e['en'])
    tokens = ' '.join(TOKEN_RE.findall(e['en']))
    if marks:
        tokens = (tokens + '  ' + ' '.join(marks)).strip()
    return {'file': name, 'key': e['key'], 'context': e['context'],
            'tokens': tokens, 'en': e['en'], 'zh': ''}


def cmd_export(work_dir, tr_dir):
    en_dir = os.path.join(work_dir, 'en')
    ui = [_mk_row(n, e) for n, e in _rows(en_dir, {'strings', 'endgame'})]
    sub = [_mk_row(n, e) for n, e in _rows(en_dir, {'text'})]
    write_tsv(os.path.join(tr_dir, 'ui_strings.tsv'), ui)
    write_tsv(os.path.join(tr_dir, 'subtitles.tsv'), sub)
    print(f'UI 文本   {len(ui):5d} 条 -> ui_strings.tsv')
    print(f'关卡字幕  {len(sub):5d} 条 -> subtitles.tsv')
    return len(ui) + len(sub)


def _load_csv(path):
    """读译文. 不对 zh 做 strip —— 首尾空格可能是有意义的。"""
    if not os.path.exists(path):
        return {}
    out = {}
    for r in read_tsv(path):
        zh = r.get('zh') or ''
        if zh:
            out[(r['file'], r['key'])] = zh
    return out


def cmd_apply(work_dir, tr_dir, out_dir, encoding=RAW_ENC):
    en_dir = os.path.join(work_dir, 'en')
    tr = {}
    for n in ('ui_strings.tsv', 'subtitles.tsv'):
        tr.update(_load_csv(os.path.join(tr_dir, n)))

    changed = warned = 0
    for name in sorted(os.listdir(en_dir)):
        if kind_of(name) is None:
            continue
        src = os.path.join(en_dir, name)
        lines = read_lines(src)
        pending_inserts = []
        for e in parse(src):
            zh = tr.get((name, e['key']))
            if not zh:
                continue
            miss = [t for t in TOKEN_RE.findall(e['en']) if t not in zh]
            if miss:
                print(f'  ! {name} #{e["key"]} 译文缺少记号 {miss}')
                warned += 1
            if edge_space(e['en']) != edge_space(zh):
                print(f'  ! {name} #{e["key"]} 首尾空格与原文不一致: '
                      f'原文{edge_space(e["en"]) or "无"} 译文{edge_space(zh) or "无"}')
                warned += 1
            if e.get('persona'):
                cr = '\r' if lines[e['line']].endswith('\r') else ''
                new_line = f'$Display Name: "{zh}"{cr}'
                if e['disp_line'] is not None:
                    lines[e['disp_line']] = new_line
                else:
                    # 原本没有这一行, 插到 $Name 后面 (行号从后往前处理才不会错位,
                    # 所以这里先记下来, 循环结束后统一插入)
                    pending_inserts.append((e['line'] + 1, new_line))
            elif e['block']:
                body = [l for l in zh.split('\\n')]
                lines[e['line']:e['end']] = [l + '\r' for l in body]
            else:
                old = lines[e['line']]
                m = LANG_RE.match(old.rstrip('\r'))
                cr = '\r' if old.endswith('\r') else ''
                lines[e['line']] = f'En:{m.group(2)}"{zh}"{m.group(4)}{cr}'
            changed += 1
        # 从后往前插, 避免前面的插入把后面的行号顶偏
        for pos, text in sorted(pending_inserts, reverse=True):
            lines.insert(pos, text)
        write_lines(os.path.join(out_dir, name), lines, encoding)
    print(f'回填 {changed} 条译文, {warned} 条告警 -> {out_dir}')
    return changed


def cmd_verify(dir_a, dir_b):
    bad = 0
    names = sorted(n for n in os.listdir(dir_a) if kind_of(n))
    for n in names:
        pa, pb = os.path.join(dir_a, n), os.path.join(dir_b, n)
        if not os.path.exists(pb):
            print(f'  缺失: {n}')
            bad += 1
            continue
        if open(pa, 'rb').read() != open(pb, 'rb').read():
            print(f'  不一致: {n}')
            bad += 1
    print(f'比对 {len(names)} 个文件, {bad} 处差异')
    return bad


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    try:
        if cmd == 'extract':
            cmd_extract(argv[2], argv[3])
        elif cmd == 'export':
            cmd_export(argv[2], argv[3])
        elif cmd == 'apply':
            enc = RAW_ENC
            if '--encoding' in argv:
                enc = argv[argv.index('--encoding') + 1]
            cmd_apply(argv[2], argv[3], argv[4], enc)
        elif cmd == 'verify':
            return 1 if cmd_verify(argv[2], argv[3]) else 0
        else:
            print(__doc__)
            return 1
    except IndexError:
        print(__doc__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
