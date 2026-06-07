#!/usr/bin/env python3
"""
pysix2png — 将 DEC SIXEL 图像转换为 PNG 格式

基于 libsixel 1.8.7 的 fromsixel.c 状态机实现的纯 Python Sixel 解码器。
用法与 C 版 sixel2png 保持一致。

用法:
    pysix2png.py -i input.sixel -o output.png
    pysix2png.py < input.sixel > output.png

选项:
    -i, --input     指定输入文件
    -o, --output    指定输出文件
    -V, --version   显示版本和许可信息
    -H, --help      显示帮助信息
"""

import argparse
import sys
from io import BytesIO

from PIL import Image

VERSION = "1.0.0"

SIXEL_PALETTE_MAX = 256
SIXEL_WIDTH_LIMIT = 1000000
SIXEL_HEIGHT_LIMIT = 1000000
DECSIXEL_PARAMS_MAX = 16


def _palval(n, a, m):
    return (n * a + m // 2) // m


def _xrgb(r, g, b):
    return (_palval(r, 255, 100) << 16) + (_palval(g, 255, 100) << 8) + _palval(b, 255, 100)


# 16 色默认调色板（与 libsixel 一致）
_SIXEL_DEFAULT_COLOR_TABLE = [
    _xrgb(0, 0, 0),       #  0 Black
    _xrgb(20, 20, 80),    #  1 Blue
    _xrgb(80, 13, 13),    #  2 Red
    _xrgb(20, 80, 20),    #  3 Green
    _xrgb(80, 20, 80),    #  4 Magenta
    _xrgb(20, 80, 80),    #  5 Cyan
    _xrgb(80, 80, 20),    #  6 Yellow
    _xrgb(53, 53, 53),    #  7 Gray 50%
    _xrgb(26, 26, 26),    #  8 Gray 25%
    _xrgb(33, 33, 60),    #  9 Blue*
    _xrgb(60, 26, 26),    # 10 Red*
    _xrgb(33, 60, 33),    # 11 Green*
    _xrgb(60, 33, 60),    # 12 Magenta*
    _xrgb(33, 60, 60),    # 13 Cyan*
    _xrgb(60, 60, 33),    # 14 Yellow*
    _xrgb(80, 80, 80),    # 15 Gray 75%
]


def _hls_to_rgb(hue, lum, sat):
    """HLS 色彩空间转 RGB（复刻 libsixel 的 hls_to_rgb）"""
    if sat == 0:
        r = g = b = lum
        return (_palval(r, 255, 100) << 16) + (_palval(g, 255, 100) << 8) + _palval(b, 255, 100)

    if lum > 50:
        max_val = lum + sat * (1.0 - (2 * (lum / 100.0) - 1.0)) / 2.0
        min_val = lum - sat * (1.0 - (2 * (lum / 100.0) - 1.0)) / 2.0
    else:
        max_val = lum + sat * (1.0 - (-(2 * (lum / 100.0) - 1.0))) / 2.0
        min_val = lum - sat * (1.0 - (-(2 * (lum / 100.0) - 1.0))) / 2.0

    # sixel hue 色环比通用色环旋转 -120 度
    hue = (hue + 240) % 360

    sector = hue // 60
    if sector == 0:
        r = max_val
        g = min_val + (max_val - min_val) * (hue / 60.0)
        b = min_val
    elif sector == 1:
        r = min_val + (max_val - min_val) * ((120 - hue) / 60.0)
        g = max_val
        b = min_val
    elif sector == 2:
        r = min_val
        g = max_val
        b = min_val + (max_val - min_val) * ((hue - 120) / 60.0)
    elif sector == 3:
        r = min_val
        g = min_val + (max_val - min_val) * ((240 - hue) / 60.0)
        b = max_val
    elif sector == 4:
        r = min_val + (max_val - min_val) * ((hue - 240) / 60.0)
        g = min_val
        b = max_val
    else:  # sector == 5
        r = max_val
        g = min_val
        b = min_val + (max_val - min_val) * ((360 - hue) / 60.0)

    return (_palval(int(r), 255, 100) << 16) + (_palval(int(g), 255, 100) << 8) + _palval(int(b), 255, 100)


# 状态常量
PS_GROUND   = 0
PS_ESC      = 1
PS_DCS      = 2
PS_DECSIXEL = 3
PS_DECGRA   = 4
PS_DECGRI   = 5
PS_DECGCI   = 6


class _ImageBuffer:
    __slots__ = ('data', 'width', 'height', 'palette', 'ncolors')

    def __init__(self, width, height, bgindex):
        self.width = width
        self.height = height
        self.data = bytearray(width * height)
        if bgindex >= 0:
            for i in range(len(self.data)):
                self.data[i] = bgindex
        self.ncolors = 2

        self.palette = list(_SIXEL_DEFAULT_COLOR_TABLE) + [0] * (SIXEL_PALETTE_MAX - 16)
        n = 16
        # 16-231: 6x6x6 色立方体
        for ri in range(6):
            for gi in range(6):
                for bi in range(6):
                    if n < SIXEL_PALETTE_MAX:
                        self.palette[n] = (ri * 51 << 16) + (gi * 51 << 8) + bi * 51
                    n += 1
        # 232-255: 灰度渐变
        for i in range(24):
            if n < SIXEL_PALETTE_MAX:
                self.palette[n] = (i * 11 << 16) + (i * 11 << 8) + i * 11
            n += 1
        # 剩余填白色
        while n < SIXEL_PALETTE_MAX:
            self.palette[n] = 0xFFFFFF
            n += 1

    def resize(self, width, height, bgindex):
        alt = bytearray(width * height)
        min_h = min(height, self.height)
        if width > self.width:
            for row in range(min_h):
                src_off = self.width * row
                dst_off = width * row
                alt[dst_off:dst_off + self.width] = self.data[src_off:src_off + self.width]
                # 扩展部分填背景色
                bg = bgindex if bgindex >= 0 else 0
                for c in range(self.width, width):
                    alt[dst_off + c] = bg
        else:
            for row in range(min_h):
                src_off = self.width * row
                dst_off = width * row
                alt[dst_off:dst_off + width] = self.data[src_off:src_off + width]
        if height > self.height:
            bg = bgindex if bgindex >= 0 else 0
            fill_start = width * self.height
            for i in range(fill_start, width * height):
                alt[i] = bg
        self.data = alt
        self.width = width
        self.height = height


class _ParserContext:
    __slots__ = ('state', 'pos_x', 'pos_y', 'max_x', 'max_y',
                 'attributed_pan', 'attributed_pad',
                 'attributed_ph', 'attributed_pv',
                 'repeat_count', 'color_index', 'bgindex',
                 'param', 'nparams', 'params')

    def __init__(self):
        self.state = PS_GROUND
        self.pos_x = 0
        self.pos_y = 0
        self.max_x = 0
        self.max_y = 0
        self.attributed_pan = 2
        self.attributed_pad = 1
        self.attributed_ph = 0
        self.attributed_pv = 0
        self.repeat_count = 1
        self.color_index = 15
        self.bgindex = -1
        self.param = 0
        self.nparams = 0
        self.params = [0] * DECSIXEL_PARAMS_MAX


def _sixel_decode_raw(data):
    """解码 Sixel 字节数据，返回 (indexed_pixels, width, height, palette, ncolors)"""
    ctx = _ParserContext()
    img = _ImageBuffer(1, 1, ctx.bgindex)
    p = 0
    data_len = len(data)

    while p < data_len:
        byte = data[p]

        if ctx.state == PS_GROUND:
            if byte == 0x1B:  # ESC
                ctx.state = PS_ESC
            elif byte == 0x90:  # DCS (8-bit)
                ctx.state = PS_DCS
            elif byte == 0x9C:  # ST (8-bit)
                break
            p += 1

        elif ctx.state == PS_ESC:
            if byte == ord('\\') or byte == 0x9C:
                break
            elif byte == ord('P'):
                ctx.param = -1
                ctx.state = PS_DCS
            p += 1

        elif ctx.state == PS_DCS:
            if byte == 0x1B:
                ctx.state = PS_ESC
            elif ord('0') <= byte <= ord('9'):
                if ctx.param < 0:
                    ctx.param = 0
                ctx.param = ctx.param * 10 + (byte - ord('0'))
            elif byte == ord(';'):
                if ctx.param < 0:
                    ctx.param = 0
                if ctx.nparams < DECSIXEL_PARAMS_MAX:
                    ctx.params[ctx.nparams] = ctx.param
                    ctx.nparams += 1
                ctx.param = 0
            elif byte == ord('q'):
                if ctx.param >= 0 and ctx.nparams < DECSIXEL_PARAMS_MAX:
                    ctx.params[ctx.nparams] = ctx.param
                    ctx.nparams += 1
                # Pn1: aspect ratio
                if ctx.nparams > 0:
                    pn1 = ctx.params[0]
                    if pn1 in (0, 1):
                        ctx.attributed_pad = 2
                    elif pn1 == 2:
                        ctx.attributed_pad = 5
                    elif pn1 in (3, 4):
                        ctx.attributed_pad = 4
                    elif pn1 in (5, 6):
                        ctx.attributed_pad = 3
                    elif pn1 in (7, 8):
                        ctx.attributed_pad = 2
                    elif pn1 == 9:
                        ctx.attributed_pad = 1
                    else:
                        ctx.attributed_pad = 2
                # Pn3: grid aspect ratio
                if ctx.nparams > 2:
                    pn3 = ctx.params[2]
                    if pn3 == 0:
                        pn3 = 10
                    scaled_pan = ctx.attributed_pan * pn3 // 10
                    scaled_pad = ctx.attributed_pad * pn3 // 10
                    ctx.attributed_pan = max(1, scaled_pan)
                    ctx.attributed_pad = max(1, scaled_pad)
                ctx.nparams = 0
                ctx.state = PS_DECSIXEL
            p += 1

        elif ctx.state == PS_DECSIXEL:
            if byte == 0x1B:
                ctx.state = PS_ESC
            elif byte == ord('"'):
                ctx.param = 0
                ctx.nparams = 0
                ctx.state = PS_DECGRA
            elif byte == ord('!'):
                ctx.param = 0
                ctx.nparams = 0
                ctx.state = PS_DECGRI
            elif byte == ord('#'):
                ctx.param = 0
                ctx.nparams = 0
                ctx.state = PS_DECGCI
            elif byte == ord('$'):
                # DECGCR Graphics Carriage Return
                ctx.pos_x = 0
            elif byte == ord('-'):
                # DECGNL Graphics Next Line
                ctx.pos_x = 0
                ctx.pos_y += 6
            elif 0x3F <= byte <= 0x7E:  # sixel 字符 '?'-'~'
                # 扩展缓冲区
                sx = img.width
                while sx < ctx.pos_x + ctx.repeat_count:
                    sx *= 2
                sy = img.height
                while sy < ctx.pos_y + 6:
                    sy *= 2
                if sx > img.width or sy > img.height:
                    img.resize(sx, sy, ctx.bgindex)
                if ctx.color_index > img.ncolors:
                    img.ncolors = ctx.color_index
                bits = byte - 0x3F
                if bits != 0:
                    if ctx.repeat_count <= 1:
                        vmask = 0x01
                        for i in range(6):
                            if bits & vmask:
                                pos = img.width * (ctx.pos_y + i) + ctx.pos_x
                                img.data[pos] = ctx.color_index
                                if ctx.max_x < ctx.pos_x:
                                    ctx.max_x = ctx.pos_x
                                if ctx.max_y < ctx.pos_y + i:
                                    ctx.max_y = ctx.pos_y + i
                            vmask <<= 1
                    else:
                        vmask = 0x01
                        i = 0
                        while i < 6:
                            if bits & vmask:
                                c = vmask << 1
                                n = 1
                                while i + n < 6:
                                    if not (bits & c):
                                        break
                                    c <<= 1
                                    n += 1
                                for y in range(ctx.pos_y + i, ctx.pos_y + i + n):
                                    off = img.width * y + ctx.pos_x
                                    for k in range(ctx.repeat_count):
                                        img.data[off + k] = ctx.color_index
                                end_x = ctx.pos_x + ctx.repeat_count - 1
                                end_y = ctx.pos_y + i + n - 1
                                if ctx.max_x < end_x:
                                    ctx.max_x = end_x
                                if ctx.max_y < end_y:
                                    ctx.max_y = end_y
                                i += (n - 1)
                                vmask <<= (n - 1)
                            vmask <<= 1
                            i += 1
                    ctx.pos_x += ctx.repeat_count
                else:
                    ctx.pos_x += ctx.repeat_count
                ctx.repeat_count = 1
            p += 1

        elif ctx.state == PS_DECGRA:
            # DECGRA Set Raster Attributes: "Pan;Pad;Ph;Pv
            if byte == 0x1B:
                ctx.state = PS_ESC
            elif ord('0') <= byte <= ord('9'):
                ctx.param = ctx.param * 10 + (byte - ord('0'))
            elif byte == ord(';'):
                if ctx.nparams < DECSIXEL_PARAMS_MAX:
                    ctx.params[ctx.nparams] = ctx.param
                    ctx.nparams += 1
                ctx.param = 0
            else:
                if ctx.nparams < DECSIXEL_PARAMS_MAX:
                    ctx.params[ctx.nparams] = ctx.param
                    ctx.nparams += 1
                if ctx.nparams > 0:
                    ctx.attributed_pad = ctx.params[0]
                if ctx.nparams > 1:
                    ctx.attributed_pan = ctx.params[1]
                if ctx.nparams > 2 and ctx.params[2] > 0:
                    ctx.attributed_ph = ctx.params[2]
                if ctx.nparams > 3 and ctx.params[3] > 0:
                    ctx.attributed_pv = ctx.params[3]
                if ctx.attributed_pan <= 0:
                    ctx.attributed_pan = 1
                if ctx.attributed_pad <= 0:
                    ctx.attributed_pad = 1
                # 根据光栅属性扩展缓冲区
                if img.width < ctx.attributed_ph or img.height < ctx.attributed_pv:
                    sx = max(img.width, ctx.attributed_ph)
                    sy = max(img.height, ctx.attributed_pv)
                    img.resize(sx, sy, ctx.bgindex)
                ctx.state = PS_DECSIXEL
                ctx.param = 0
                ctx.nparams = 0
                continue  # 不递增 p，当前字符可能是 sixel
            p += 1

        elif ctx.state == PS_DECGRI:
            # DECGRI Graphics Repeat Introducer: !Pn
            if byte == 0x1B:
                ctx.state = PS_ESC
            elif ord('0') <= byte <= ord('9'):
                ctx.param = ctx.param * 10 + (byte - ord('0'))
            else:
                ctx.repeat_count = ctx.param
                if ctx.repeat_count == 0:
                    ctx.repeat_count = 1
                if ctx.repeat_count > 0xFFFF:
                    raise ValueError("Sixel 解码错误: 重复参数过大")
                ctx.state = PS_DECSIXEL
                ctx.param = 0
                ctx.nparams = 0
                continue  # 不递增 p，当前字符可能是 sixel
            p += 1

        elif ctx.state == PS_DECGCI:
            # DECGCI Graphics Color Introducer: #Pc;Pu;Px;Py;Pz
            if byte == 0x1B:
                ctx.state = PS_ESC
            elif ord('0') <= byte <= ord('9'):
                ctx.param = ctx.param * 10 + (byte - ord('0'))
            elif byte == ord(';'):
                if ctx.nparams < DECSIXEL_PARAMS_MAX:
                    ctx.params[ctx.nparams] = ctx.param
                    ctx.nparams += 1
                ctx.param = 0
            else:
                ctx.state = PS_DECSIXEL
                if ctx.nparams < DECSIXEL_PARAMS_MAX:
                    ctx.params[ctx.nparams] = ctx.param
                    ctx.nparams += 1
                ctx.param = 0
                if ctx.nparams > 0:
                    ctx.color_index = max(0, min(ctx.params[0], SIXEL_PALETTE_MAX - 1))
                if ctx.nparams > 4:
                    if ctx.params[1] == 1:
                        # HLS
                        h = min(ctx.params[2], 360)
                        l = min(ctx.params[3], 100)
                        s = min(ctx.params[4], 100)
                        img.palette[ctx.color_index] = _hls_to_rgb(h, l, s)
                    elif ctx.params[1] == 2:
                        # RGB
                        r = min(ctx.params[2], 100)
                        g = min(ctx.params[3], 100)
                        b = min(ctx.params[4], 100)
                        img.palette[ctx.color_index] = _xrgb(r, g, b)
                continue  # 不递增 p，当前字符可能是 sixel
            p += 1
        else:
            p += 1

    # 收尾：裁剪到实际内容范围
    ctx.max_x += 1
    ctx.max_y += 1
    if ctx.max_x < ctx.attributed_ph:
        ctx.max_x = ctx.attributed_ph
    if ctx.max_y < ctx.attributed_pv:
        ctx.max_y = ctx.attributed_pv
    if ctx.max_x < 1:
        ctx.max_x = 1
    if ctx.max_y < 1:
        ctx.max_y = 1
    if img.width > ctx.max_x or img.height > ctx.max_y:
        img.resize(ctx.max_x, ctx.max_y, ctx.bgindex)

    ncolors = img.ncolors + 1
    return img.data, img.width, img.height, img.palette, ncolors


def sixel_to_png(sixel_data):
    """将 Sixel 字节数据解码并返回 PNG 字节"""
    pixels, width, height, palette, ncolors = _sixel_decode_raw(sixel_data)

    img = Image.frombytes('P', (width, height), bytes(pixels))
    # putpalette 需要 768 字节的 (R, G, B) 展开序列
    pal_data = bytearray()
    for i in range(SIXEL_PALETTE_MAX):
        rgb = palette[i]
        pal_data.append((rgb >> 16) & 0xFF)
        pal_data.append((rgb >> 8) & 0xFF)
        pal_data.append(rgb & 0xFF)
    img.putpalette(bytes(pal_data))

    buf = BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def main():
    parser = argparse.ArgumentParser(
        prog='pysix2png',
        add_help=False,
        description='将 DEC SIXEL 图像转换为 PNG 格式',
        epilog='用法: pysix2png -i input.sixel -o output.png\n'
               '       pysix2png < input.sixel > output.png',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('-i', '--input', default=None)
    parser.add_argument('-o', '--output', default=None)
    parser.add_argument('-V', '--version', action='store_true')
    parser.add_argument('-H', '--help', action='store_true')

    args = parser.parse_args()

    if args.version:
        print(f"pysix2png {VERSION}")
        return

    if args.help:
        parser.print_help(sys.stderr)
        return

    # 读取输入
    if args.input and args.input != '-':
        with open(args.input, 'rb') as f:
            sixel_data = f.read()
    else:
        if hasattr(sys.stdin, 'buffer'):
            sixel_data = sys.stdin.buffer.read()
        else:
            sixel_data = sys.stdin.read()
            if isinstance(sixel_data, str):
                sixel_data = sixel_data.encode('latin-1')

    # 解码并输出 PNG
    png_data = sixel_to_png(sixel_data)

    if args.output and args.output != '-':
        with open(args.output, 'wb') as f:
            f.write(png_data)
    else:
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout.buffer.write(png_data)
        else:
            sys.stdout.write(png_data.decode('latin-1'))


if __name__ == '__main__':
    main()
