#!/usr/bin/env python3
"""Red Faction VPP (packfile) v1 读写工具.

格式说明 (RF 2001, version 1):
  0x000  uint32  signature = 0x51890ACE
  0x004  uint32  version   = 1
  0x008  uint32  file_count
  0x00C  uint32  total_size
  ...    补零至 2048 字节
  0x800  目录区: 每项 64 字节 = char[60] 文件名(NUL 结尾) + uint32 文件大小
         整个目录区向上对齐到 2048 字节边界
  之后   各文件数据依次排列, 每个文件向上对齐到 2048 字节边界

用法:
  python vpp.py list   <in.vpp>
  python vpp.py unpack <in.vpp> <outdir> [.ext,.ext]
  python vpp.py pack   <out.vpp> <file|dir> [...]
"""
import os
import struct
import sys

SIG = 0x51890ACE
BLOCK = 2048
NAME_LEN = 60
ENTRY_LEN = 64


def _align(n, a=BLOCK):
    return (n + a - 1) // a * a


def read_index(path):
    """返回 [(名称, 大小, 数据偏移), ...]"""
    with open(path, 'rb') as f:
        sig, ver, count, _total = struct.unpack('<IIII', f.read(16))
        if sig != SIG:
            raise ValueError(f'{path}: 不是 VPP 文件 (签名 {sig:#x})')
        if ver != 1:
            raise ValueError(f'{path}: 不支持的 VPP 版本 {ver}')
        f.seek(BLOCK)
        raw = f.read(count * ENTRY_LEN)
    entries = []
    off = BLOCK + _align(count * ENTRY_LEN)
    for i in range(count):
        rec = raw[i * ENTRY_LEN:(i + 1) * ENTRY_LEN]
        name = rec[:NAME_LEN].split(b'\0')[0].decode('latin1')
        size = struct.unpack('<I', rec[NAME_LEN:])[0]
        entries.append((name, size, off))
        off += _align(size)
    return entries


def read_file(path, name):
    """从 vpp 中读出单个文件的内容 (名称大小写不敏感)"""
    low = name.lower()
    with open(path, 'rb') as f:
        for n, size, off in read_index(path):
            if n.lower() == low:
                f.seek(off)
                return f.read(size)
    raise KeyError(name)


def unpack(path, outdir, exts=None):
    os.makedirs(outdir, exist_ok=True)
    n = 0
    with open(path, 'rb') as f:
        for name, size, off in read_index(path):
            if exts and not name.lower().endswith(tuple(exts)):
                continue
            f.seek(off)
            with open(os.path.join(outdir, name), 'wb') as out:
                out.write(f.read(size))
            n += 1
    return n


def pack(out_path, files):
    """files: 文件路径列表. 打包顺序即给定顺序."""
    items = []
    for p in files:
        name = os.path.basename(p)
        if len(name.encode('latin1')) >= NAME_LEN:
            raise ValueError(f'文件名过长 (上限 {NAME_LEN - 1}): {name}')
        with open(p, 'rb') as f:
            items.append((name, f.read()))

    count = len(items)
    index = bytearray()
    for name, data in items:
        index += name.encode('latin1').ljust(NAME_LEN, b'\0')
        index += struct.pack('<I', len(data))
    index += b'\0' * (_align(len(index)) - len(index))

    body = bytearray()
    for _name, data in items:
        body += data
        body += b'\0' * (_align(len(data)) - len(data))

    header = struct.pack('<IIII', SIG, 1, count, len(body))
    header += b'\0' * (BLOCK - len(header))

    with open(out_path, 'wb') as f:
        f.write(header)
        f.write(index)
        f.write(body)
    return count


def _collect(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += [os.path.join(p, n) for n in sorted(os.listdir(p))
                    if os.path.isfile(os.path.join(p, n))]
        else:
            out.append(p)
    return out


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == 'list':
        for name, size, off in read_index(argv[2]):
            print(f'{size:10d}  {off:12d}  {name}')
    elif cmd == 'unpack':
        exts = argv[4].split(',') if len(argv) > 4 else None
        print(f'解出 {unpack(argv[2], argv[3], exts)} 个文件 -> {argv[3]}')
    elif cmd == 'pack':
        files = _collect(argv[3:])
        print(f'打包 {pack(argv[2], files)} 个文件 -> {argv[2]}')
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
