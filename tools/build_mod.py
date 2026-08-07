#!/usr/bin/env python3
"""一键构建汉化 mod.

流程: 读 work/en 原文 + translation/*.csv 译文 -> build/tbl -> dist/mods/<名字>/<名字>.vpp

用法:
  python build_mod.py [--root 项目目录] [--name rfcn] [--encoding utf-8|gbk]

生成后在游戏里用  RF.exe -mod rfcn  加载 (需先把 dist/mods/rfcn 复制到
游戏目录的 mods\\ 下)。
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rftext  # noqa: E402
import vpp  # noqa: E402


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.path.dirname(here))
    ap.add_argument('--name', default='rfcn')
    ap.add_argument('--encoding', default='utf-8',
                    help='译文落盘编码; 引擎未改造前用 gbk, 改造后用 utf-8')
    args = ap.parse_args()

    work = os.path.join(args.root, 'work')
    tr = os.path.join(args.root, 'translation')
    build = os.path.join(args.root, 'build', 'tbl')
    mod_dir = os.path.join(args.root, 'dist', 'mods', args.name)

    if os.path.isdir(build):
        shutil.rmtree(build)
    print('[1/2] 回填译文')
    rftext.cmd_apply(work, tr, build, args.encoding)

    print('[2/2] 打包 vpp')
    os.makedirs(mod_dir, exist_ok=True)
    files = [os.path.join(build, n) for n in sorted(os.listdir(build))]
    out = os.path.join(mod_dir, f'{args.name}.vpp')
    n = vpp.pack(out, files)
    print(f'完成: {n} 个文件 -> {out} ({os.path.getsize(out) / 1024:.0f} KB)')
    print(f'\n使用: 把 {mod_dir} 复制到 游戏目录\\mods\\, 然后 RF.exe -mod {args.name}')


if __name__ == '__main__':
    main()
