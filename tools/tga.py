#!/usr/bin/env python3
"""RF 用的 TGA 读写.

**不要用 Pillow 直接存 TGA。** 它会改写描述符字节 (原版是 0x20/0x08/0x00,
Pillow 一律写 0x28) 并追加 26 字节 footer。原版引擎的加载器是否挑剔没人验证过,
与其赌不如逐字节保持原样 —— 我们只换像素, 头部原封不动写回去。

maps_en.vpp 里 229 张的实际格式:
    type=2 (未压缩 RGB), 32bpp desc=0x08  123 张   左下原点, 带 alpha
    type=2,              32bpp desc=0x20   88 张   左上原点
    type=2,              24bpp desc=0x00   18 张   左下原点, 无 alpha
"""
import struct

from PIL import Image


class Tga:
    """保存原始头部, 只替换像素数据。"""

    def __init__(self, header: bytes, image: Image.Image):
        self.header = header          # 完整的 18 字节头 (含 id_len 之后的 ID 区)
        self.image = image            # RGBA 或 RGB

    @property
    def bpp(self):
        return self.header[16]

    @property
    def top_origin(self):
        return bool(self.header[17] & 0x20)


def read(path) -> Tga:
    with open(path, 'rb') as f:
        data = f.read()
    id_len, cmap_type, img_type = data[0], data[1], data[2]
    w, h = struct.unpack_from('<HH', data, 12)
    bpp, desc = data[16], data[17]
    if img_type != 2 or cmap_type != 0:
        raise ValueError(f'{path}: 只支持未压缩 RGB (type=2), 实际 type={img_type}')
    if bpp not in (24, 32):
        raise ValueError(f'{path}: 只支持 24/32 位, 实际 {bpp}')

    off = 18 + id_len
    n = w * h * (bpp // 8)
    raw = data[off:off + n]
    if len(raw) != n:
        raise ValueError(f'{path}: 像素数据不足 ({len(raw)} < {n})')

    # TGA 存的是 BGR(A)
    mode = 'RGBA' if bpp == 32 else 'RGB'
    im = Image.frombytes(mode, (w, h), raw, 'raw',
                         'BGRA' if bpp == 32 else 'BGR')
    if not (desc & 0x20):          # 左下原点 -> 转成常规的左上
        im = im.transpose(Image.FLIP_TOP_BOTTOM)
    return Tga(data[:off], im)


def write(path, tga: Tga):
    im = tga.image
    if not tga.top_origin:
        im = im.transpose(Image.FLIP_TOP_BOTTOM)
    mode = 'RGBA' if tga.bpp == 32 else 'RGB'
    if im.mode != mode:
        im = im.convert(mode)
    raw = im.tobytes('raw', 'BGRA' if tga.bpp == 32 else 'BGR')
    with open(path, 'wb') as f:
        f.write(tga.header)
        f.write(raw)


def round_trip_ok(path) -> bool:
    """读进来再写出去, 应该和原文件逐字节相同。"""
    import io
    original = open(path, 'rb').read()
    t = read(path)
    buf = io.BytesIO()
    im = t.image
    if not t.top_origin:
        im = im.transpose(Image.FLIP_TOP_BOTTOM)
    buf.write(t.header)
    buf.write(im.tobytes('raw', 'BGRA' if t.bpp == 32 else 'BGR'))
    return buf.getvalue() == original[:len(buf.getvalue())]


if __name__ == '__main__':
    import glob
    import sys
    files = sorted(glob.glob(sys.argv[1] if len(sys.argv) > 1 else '*.tga'))
    bad = [f for f in files if not round_trip_ok(f)]
    print(f'{len(files)} 个文件, 往返不一致 {len(bad)} 个')
    for f in bad[:10]:
        print('  !', f)
