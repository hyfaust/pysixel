"""pysixview — 自适应 Sixel 文件查看器

自动检测终端宽度，超宽图像缩放后输出，未超宽直接输出。
用法:
    pysixview.py input.six
    pysixview.py -w 800 input.six
    pysixview.py -m 8 --save input.six   # 保存乘数设置
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from pysix2png import _sixel_decode_raw, SIXEL_PALETTE_MAX
from pyimg2six import encode_sixel, _resize_for_terminal, quantize, _get_terminal_columns

_CONFIG_PATH = Path.home() / ".sixview.conf"
_DEFAULT_MULTIPLIER = 8


def _load_multiplier():
    """从 ~/.sixview.conf 读取已保存的乘数。"""
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return int(data.get("multiplier", _DEFAULT_MULTIPLIER))
    except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError):
        return _DEFAULT_MULTIPLIER


def _save_multiplier(multiplier):
    """保存乘数到 ~/.sixview.conf。"""
    _CONFIG_PATH.write_text(json.dumps({"multiplier": multiplier}), encoding="utf-8")


def _parse_raster_width(data, head_bytes=512):
    """快速解析 Sixel 光栅属性中的图像宽度，仅读文件头。"""
    head = data[:head_bytes]
    m = re.search(rb'"(\d+);(\d+);(\d+);(\d+)', head)
    if m:
        return int(m.group(3))
    return None


def _parse_raster_size(data, head_bytes=512):
    """快速解析 Sixel 光栅属性中的图像宽高，仅读文件头。"""
    head = data[:head_bytes]
    m = re.search(rb'"(\d+);(\d+);(\d+);(\d+)', head)
    if m:
        return int(m.group(3)), int(m.group(4))
    return None, None


def _decode_to_image(sixel_data):
    """将 Sixel 字节数据解码为 PIL RGB Image。"""
    pixels, width, height, palette, ncolors = _sixel_decode_raw(sixel_data)
    img = Image.frombytes('P', (width, height), bytes(pixels))
    pal_data = bytearray()
    for i in range(SIXEL_PALETTE_MAX):
        rgb = palette[i]
        pal_data.append((rgb >> 16) & 0xFF)
        pal_data.append((rgb >> 8) & 0xFF)
        pal_data.append(rgb & 0xFF)
    img.putpalette(bytes(pal_data))
    return img.convert('RGB')


def _encode_image(img, max_px_width):
    """将 PIL Image 编码为 Sixel 字节（缩放 + 量化 + 编码）。"""
    img = _resize_for_terminal(img, max_px_width)
    quantized = quantize(img, max_colors=256, dither="none", quality="auto")
    palette = quantized.getpalette()
    w, h = quantized.size
    num_colors = len(palette) // 3
    palette_colors = np.array(palette[:num_colors * 3], dtype=np.uint8).reshape(num_colors, 3)
    pixels_np = np.array(quantized, dtype=np.uint8)
    sixel_data, _ = encode_sixel(pixels_np, palette_colors, w, h)
    return sixel_data


def main():
    saved_multiplier = _load_multiplier()

    parser = argparse.ArgumentParser(
        prog="pysixview",
        description="自适应 Sixel 文件查看器 — 超宽图像自动缩放",
    )
    parser.add_argument("input", help="Sixel 文件路径")
    parser.add_argument("-w", "--width", type=int, metavar="PX",
                        help="最大像素宽度（默认终端列数 × 乘数）")
    parser.add_argument("-m", "--multiplier", type=int, default=saved_multiplier, metavar="N",
                        help=f"终端列数乘数（已保存: {saved_multiplier}）")
    parser.add_argument("--save", action="store_true",
                        help="将乘数保存到 ~/.sixview.conf")
    parser.add_argument("-i", "--info", action="store_true",
                        help="显示图像尺寸后退出")
    parser.add_argument("--no-resize", action="store_true",
                        help="不缩放，直接输出原文件")
    args = parser.parse_args()

    if args.save:
        _save_multiplier(args.multiplier)
        print(f"已保存乘数 {args.multiplier} 到 {_CONFIG_PATH}", file=sys.stderr)

    path = Path(args.input)
    if not path.exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        sys.exit(1)

    data = path.read_bytes()
    if not data:
        sys.exit(0)

    if args.info:
        w, h = _parse_raster_size(data)
        if w is not None:
            print(f"{w}x{h}")
        else:
            print("无法解析光栅属性", file=sys.stderr)
            sys.exit(1)
        return

    if args.no_resize:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        return

    terminal_cols = _get_terminal_columns()
    max_px_width = args.width if args.width else terminal_cols * args.multiplier

    # 快速解析图像宽度
    img_width = _parse_raster_width(data)

    if img_width is not None and img_width <= max_px_width:
        # 未超宽（≤ 终端宽度 80%），直接输出
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    else:
        # 超宽或无法解析宽度，解码→缩放→重编码
        img = _decode_to_image(data)
        sixel_data = _encode_image(img, max_px_width)
        sys.stdout.buffer.write(sixel_data)
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
