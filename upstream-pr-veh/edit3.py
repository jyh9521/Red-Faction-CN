#!/usr/bin/env python3
"""把 VEH 那三处一行改动打到 PR 工作树上。

复用 apply_patch.VEH_EDITS 里的定义 —— 和本地汉化树用的是同一份, 也就是
build13 里编译验证过的那份, 不会出现"PR 里的和测过的不一样"。

新增文件那条 (create) 跳过, 因为文件已经手工复制过去了。

用法:
    python edit3.py <PR_WORKTREE>
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'patches'))

import apply_patch  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    root = sys.argv[1]
    if not os.path.isdir(os.path.join(root, 'game_patch')):
        print(f'{root} 不像是 alpinefaction 源码目录')
        return 1

    logger = os.path.join(root, 'game_patch', 'debug', 'exception_logger.cpp')
    if not os.path.exists(logger):
        print('缺少 game_patch/debug/exception_logger.cpp, 先复制过去')
        return 1

    # 复制过去的那份必须和 PR 包里的一致, 否则提交的就不是测过的代码
    src = apply_patch.read_source(os.path.join(HERE, 'exception_logger.cpp'))[0]
    dst = apply_patch.read_source(logger)[0]
    if src != dst:
        print('! exception_logger.cpp 与 PR 包里的不一致, 重新复制一遍')
        return 1
    print(f'exception_logger.cpp 一致 ({src.count(chr(10))} 行)')

    edits = [e for e in apply_patch.VEH_EDITS if 'create' not in e]
    print(f'\n打 {len(edits)} 处一行改动:')
    if not apply_patch.apply(root, edits):
        print('\n失败。上游可能改动了这几处的上下文, 需要人工核对锚点。')
        return 1
    print('\n完成。接下来跑 git status --short 确认只有 4 个文件。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
