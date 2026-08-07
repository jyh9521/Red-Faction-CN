#!/usr/bin/env python3
"""游戏目录快照 / 差异比对.

用于记录安装 Dash Faction 前后的目录变化, 以便发布整合版时准确知道
需要打包哪些文件、哪些原版文件被替换。

大文件 (默认 >64MB) 只对首尾各 4MB + 文件大小做哈希, 避免全量读取拖慢,
对检测 exe 替换、tbl 修改这类场景足够。

子命令:
  take <目录> <输出.json> [--label 说明]
  diff <旧.json> <新.json> [--md 输出.md]
  show <快照.json>
"""
import argparse
import datetime
import hashlib
import json
import os
import sys

FULL_HASH_LIMIT = 64 * 1024 * 1024
EDGE = 4 * 1024 * 1024
# 这些目录不参与快照: 汉化工程自身 + 运行时产生的存档
EXCLUDE_DIRS = {'rf_cn'}
# 这些文件每次运行游戏都会变, 记录但比对时忽略
VOLATILE = {'players.cfg', 'console_history', 'svrlist.adr', 'favlist.adr',
            'banlist.txt', 'red.cfg', 'rfd3d.id', 'steam_autocloud.vdf',
            'dashfaction.log', 'df_config.txt'}


def file_digest(path, size):
    h = hashlib.sha256()
    if size <= FULL_HASH_LIMIT:
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        return 'sha256:' + h.hexdigest()
    with open(path, 'rb') as f:
        h.update(f.read(EDGE))
        f.seek(-EDGE, os.SEEK_END)
        h.update(f.read(EDGE))
    h.update(str(size).encode())
    return 'partial:' + h.hexdigest()


def take(root, label=''):
    root = os.path.abspath(root)
    files = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace('\\', '/')
            # 符号链接必须单独记录: 安装器可能把 exe 换成指向别处的链接,
            # 直接跳过会在 diff 里表现为"文件被删除", 产生误导
            if os.path.islink(full):
                try:
                    target = os.readlink(full)
                except OSError:
                    target = '<无法读取, 可能是 Windows 重解析点>'
                files[rel] = {'size': 0, 'mtime': 0,
                              'hash': 'symlink:' + target, 'symlink': target}
                continue
            if not os.path.isfile(full):
                continue
            try:
                st = os.stat(full)
                files[rel] = {
                    'size': st.st_size,
                    'mtime': int(st.st_mtime),
                    'hash': file_digest(full, st.st_size),
                }
            except OSError as exc:
                files[rel] = {'error': str(exc)}
    return {
        'label': label,
        'root': root,
        'taken_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'file_count': len(files),
        'total_size': sum(f.get('size', 0) for f in files.values()),
        'files': files,
    }


def _fmt(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if abs(n) < 1024 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024


def diff(old, new):
    a, b = old['files'], new['files']
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed = sorted(
        k for k in set(a) & set(b)
        if a[k].get('hash') != b[k].get('hash')
        and os.path.basename(k) not in VOLATILE
    )
    volatile = sorted(
        k for k in set(a) & set(b)
        if a[k].get('hash') != b[k].get('hash')
        and os.path.basename(k) in VOLATILE
    )
    return added, removed, changed, volatile


def report(old, new, md_path=None):
    added, removed, changed, volatile = diff(old, new)
    lines = []
    w = lines.append
    w(f"# 目录差异: {old.get('label') or '旧'} → {new.get('label') or '新'}")
    w('')
    w(f"- 旧快照 {old['taken_at']}  {old['file_count']} 个文件  {_fmt(old['total_size'])}")
    w(f"- 新快照 {new['taken_at']}  {new['file_count']} 个文件  {_fmt(new['total_size'])}")
    w(f"- 新增 {len(added)} / 删除 {len(removed)} / 修改 {len(changed)}"
      f" / 运行时变动 {len(volatile)}")
    w('')

    def table(title, keys, src):
        if not keys:
            return
        w(f'## {title} ({len(keys)})')
        w('')
        w('| 文件 | 大小 |')
        w('|---|---|')
        for k in keys:
            w(f"| `{k}` | {_fmt(src[k].get('size', 0))} |")
        w('')

    table('新增', added, new['files'])
    table('删除', removed, old['files'])

    if changed:
        w(f'## 修改 ({len(changed)})')
        w('')
        w('| 文件 | 原大小 | 新大小 | 说明 |')
        w('|---|---|---|---|')
        for k in changed:
            oe, ne = old['files'][k], new['files'][k]
            o, n = oe.get('size', 0), ne.get('size', 0)
            if str(ne.get('hash', '')).startswith('symlink:'):
                note = f"变成符号链接 → `{ne.get('symlink')}`"
            elif str(oe.get('hash', '')).startswith('symlink:'):
                note = '由符号链接变回普通文件'
            else:
                note = f'{n - o:+d} B'
            w(f'| `{k}` | {_fmt(o)} | {_fmt(n)} | {note} |')
        w('')
    if volatile:
        w('## 运行时变动 (配置/存档, 可忽略)')
        w('')
        for k in volatile:
            w(f'- `{k}`')
        w('')

    text = '\n'.join(lines)
    if md_path:
        os.makedirs(os.path.dirname(md_path) or '.', exist_ok=True)
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(text + '\n')
    return text


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('take')
    p.add_argument('root')
    p.add_argument('out')
    p.add_argument('--label', default='')
    p = sub.add_parser('diff')
    p.add_argument('old')
    p.add_argument('new')
    p.add_argument('--md')
    p = sub.add_parser('show')
    p.add_argument('snapshot')
    args = ap.parse_args()

    if args.cmd == 'take':
        snap = take(args.root, args.label)
        os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(snap, f, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"快照完成: {snap['file_count']} 个文件, "
              f"{_fmt(snap['total_size'])} -> {args.out}")
    elif args.cmd == 'diff':
        old = json.load(open(args.old, encoding='utf-8'))
        new = json.load(open(args.new, encoding='utf-8'))
        print(report(old, new, args.md))
        if args.md:
            print(f'\n已写入 {args.md}')
    else:
        s = json.load(open(args.snapshot, encoding='utf-8'))
        print(f"{s.get('label')}  {s['taken_at']}  "
              f"{s['file_count']} 个文件  {_fmt(s['total_size'])}")
        for k, v in sorted(s['files'].items()):
            print(f"  {v.get('size', 0):12d}  {k}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
