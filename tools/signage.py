#!/usr/bin/env python3
"""场景标牌贴图: 从 maps_en.vpp 导出, 以及把改好的图回封。

用法:
    python tools\\signage.py extract      导出到 rf_cn\\signage\\ 并生成预览
    python tools\\signage.py check        检查改动过哪些、格式有没有问题

为什么不直接用 Pillow 存 TGA:
    原版这 229 张有三种头部 (32bpp desc=0x08 / desc=0x20 / 24bpp desc=0x00),
    Pillow 一律写成 desc=0x28 并追加 26 字节 footer。Photoshop 存盘也会按自己
    的规则写头。**回封时一律用原始头部重新编码**, 只取编辑后的像素 —— 这样无论
    你用什么软件改, 出来的文件对引擎都和原版同构。

透明通道:
    229 张里 211 张真的用到 alpha (血迹、贴花、箭头整张都是靠 alpha 抠形状的)。
    PS 里改完务必保留 alpha 通道, 否则贴花会变成一个不透明的方块。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GAME = os.path.dirname(ROOT)
sys.path.insert(0, HERE)

import tga   # noqa: E402
import vpp   # noqa: E402

SRC_VPP = os.path.join(GAME, 'maps_en.vpp')
OUT_DIR = os.path.join(ROOT, 'signage')
ORIG_DIR = os.path.join(ROOT, 'work', 'signage_orig')

# 高清基底: Captain_Dagon 的 ESRGAN 4x AI Upscale Pack (Goober 重打包)
# 统一放大 4 倍, 格式和原版同构 (未压缩 TGA), 193 张标牌 100% 覆盖。
HD_VPPS = ['0_AIUpscale1a.vpp', '0_AIUpscale1b.vpp', '0_AIUpscale1c.vpp']
HD_DIR = os.path.join(ROOT, 'signage_hd')
HD_ORIG_DIR = os.path.join(ROOT, 'work', 'signage_hd_orig')


def _hd_index():
    """名称(小写) -> vpp 路径。后面的分卷覆盖前面的。"""
    loc = {}
    for v in HD_VPPS:
        path = os.path.join(GAME, 'client_mods', v)
        if not os.path.exists(path):
            continue
        for name, _s, _o in vpp.read_index(path):
            loc[name.lower()] = path
    return loc


def cmd_extract_hd():
    """按 signage/ 里保留的清单, 从高清包导出对应的 4 倍图。"""
    if not os.path.isdir(OUT_DIR):
        print('先跑 extract 并挑出要做的标牌')
        return 1
    loc = _hd_index()
    if not loc:
        print(f'没找到高清包, 请把 {HD_VPPS} 放进 client_mods\\')
        return 1
    os.makedirs(HD_DIR, exist_ok=True)
    os.makedirs(HD_ORIG_DIR, exist_ok=True)
    wanted = sorted(f for f in os.listdir(OUT_DIR) if f.lower().endswith('.tga'))
    got = missing = 0
    for name in wanted:
        src = loc.get(name.lower())
        if not src:
            print(f'  ! 高清包里没有 {name}')
            missing += 1
            continue
        data = vpp.read_file(src, name)
        for d in (HD_DIR, HD_ORIG_DIR):
            with open(os.path.join(d, name), 'wb') as f:
                f.write(data)
        got += 1
    print(f'导出高清版 {got} 张 -> {HD_DIR}' + (f'  (缺 {missing} 张)' if missing else ''))
    print(f'原始副本 -> {HD_ORIG_DIR}  (提供头部与对照基准, 别动)')
    return 0


def cmd_extract():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(ORIG_DIR, exist_ok=True)
    idx = vpp.read_index(SRC_VPP)
    for name, _size, _off in idx:
        data = vpp.read_file(SRC_VPP, name)
        # 两份: signage/ 给你改, work/signage_orig/ 留作对照基准
        for d in (OUT_DIR, ORIG_DIR):
            with open(os.path.join(d, name), 'wb') as f:
                f.write(data)
    print(f'导出 {len(idx)} 张 -> {OUT_DIR}')
    print(f'原始副本 -> {ORIG_DIR}  (用于比对, 别动)')


def cmd_check():
    if not os.path.isdir(ORIG_DIR):
        print('还没导出过, 先跑 extract')
        return 1
    changed, broken = [], []
    for name in sorted(os.listdir(ORIG_DIR)):
        edited = os.path.join(OUT_DIR, name)
        if not os.path.exists(edited):
            print(f'  ! 缺失: {name}')
            continue
        if open(edited, 'rb').read() == open(os.path.join(ORIG_DIR, name), 'rb').read():
            continue
        changed.append(name)
        try:
            orig = tga.read(os.path.join(ORIG_DIR, name))
            new = tga.read(edited)
            if new.image.size != orig.image.size:
                broken.append((name, f'尺寸变了 {orig.image.size} -> {new.image.size}'))
        except Exception as exc:
            broken.append((name, str(exc)))
    print(f'改动过 {len(changed)} 张')
    for n in changed:
        print(f'  · {n}')
    if broken:
        print(f'\n有问题 {len(broken)} 张:')
        for n, why in broken:
            print(f'  ! {n}: {why}')
    return 0


def _load_edited(orig_dir, out_dir):
    """返回 [(名称, 用原始头部重编后的字节)]。只含改动过的。

    为什么不直接把编辑后的文件原样塞进 vpp:
        改图软件 (PS / 各家 AI 工具) 写 TGA 时会按自己的规则定描述符字节、
        是否追加 footer、原点在上还是在下。原版引擎的加载器有多挑剔没人验证过。
        这里一律拆成像素再用**原始头部**重新编码 —— 出来的文件对引擎和原版同构,
        无论你用什么软件改都一样。
    """
    if not os.path.isdir(orig_dir) or not os.path.isdir(out_dir):
        return []
    out = []
    for name in sorted(os.listdir(orig_dir)):
        if not name.lower().endswith('.tga'):
            continue
        edited = os.path.join(out_dir, name)
        orig_path = os.path.join(orig_dir, name)
        if not os.path.exists(edited):
            continue          # 用户删掉了 = 不打算汉化这张
        if open(edited, 'rb').read() == open(orig_path, 'rb').read():
            continue          # 没改过, 不必占体积
        orig = tga.read(orig_path)
        new = tga.read(edited)
        if new.image.size != orig.image.size:
            print(f'  ! 跳过 {name}: 尺寸和原版不一致 '
                  f'{orig.image.size} != {new.image.size}')
            continue
        # 关键: 沿用原始头部, 只换像素
        orig.image = new.image
        tmp = os.path.join(out_dir, '.repack.tmp')
        tga.write(tmp, orig)
        with open(tmp, 'rb') as f:
            out.append((name, f.read()))
        os.remove(tmp)
    return out


def load_edited():
    """原始分辨率那套 (maps_en.vpp 的 229 张)。"""
    return _load_edited(ORIG_DIR, OUT_DIR)


def load_edited_hd():
    """高清那套 (AI Upscale 4x 的 193 张)。有就优先用这套。"""
    return _load_edited(HD_ORIG_DIR, HD_DIR)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'extract'
    sys.exit({'extract': cmd_extract, 'extract-hd': cmd_extract_hd,
              'check': cmd_check}[cmd]() or 0)
