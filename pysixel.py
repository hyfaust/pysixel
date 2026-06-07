"""在终端中以 Sixel 格式显示图片（需 Windows Terminal 或其他支持 Sixel 的终端）

优化技术:
- numpy 向量化: 替代 PIL 逐像素访问 (~13x 提速)
- 批量颜色计算: numpy broadcasting 一次算所有颜色
- RLE 压缩: DEC VT Sixel 协议 !COUNT CHAR
- 流式编码: 逐帧编码+释放，避免内存退化
- 自适应延迟: 编码耗时从 sleep 中扣除
- 有序抖动: Bayer 8x8 矩阵减少色带 (可选)
"""
import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

_SIXEL_WEIGHTS = np.array([1, 2, 4, 8, 16, 32], dtype=np.uint8).reshape(6, 1)

_COLOR_STR = [f"#{i}".encode("ascii") for i in range(256)]
_RUN_STR = [str(i).encode("ascii") for i in range(4096)]

_BAYER8 = np.array([
    [ 0, 32,  8, 40,  2, 34, 10, 42],
    [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44,  4, 36, 14, 46,  6, 38],
    [60, 28, 52, 20, 62, 30, 54, 22],
    [ 3, 35, 11, 43,  1, 33,  9, 41],
    [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47,  7, 39, 13, 45,  5, 37],
    [63, 31, 55, 23, 61, 29, 53, 21],
], dtype=np.float32) / 64.0 - 0.5


def _get_terminal_columns():
    """获取终端列数，失败时返回 80。"""
    try:
        return os.get_terminal_size().columns
    except (ValueError, OSError):
        return 80


def quantize(img, max_colors=256, dither=False):
    """将图片量化为有限调色板。可选 Bayer 有序抖动。"""
    rgb = img.convert("RGB")
    if dither:
        arr = np.array(rgb, dtype=np.float32)
        h, w = arr.shape[:2]
        tile_y = (h + 7) // 8
        tile_x = (w + 7) // 8
        bayer = np.tile(_BAYER8, (tile_y, tile_x))[:h, :w]
        amplitude = 255.0 / max_colors
        arr += bayer[:, :, np.newaxis] * amplitude
        arr = np.clip(arr, 0, 255).astype(np.uint8)
        rgb = Image.fromarray(arr)
    return rgb.quantize(max_colors, method=Image.Quantize.MEDIANCUT)


def _resize_for_terminal(img, max_px_width):
    """缩放图片以适应终端宽度，补偿字符宽高比。"""
    w, h = img.size
    char_aspect = 0.5
    if w > max_px_width:
        ratio = max_px_width / w
        w, h = max_px_width, int(h * ratio)
    h = int(h * char_aspect)
    return img.resize((w, h), Image.Resampling.LANCZOS)


def _preprocess_frame(img, max_px_width=640, max_colors=256, dither=False):
    """预处理一帧：resize → quantize → numpy array + palette。"""
    img = _resize_for_terminal(img, max_px_width)
    img = quantize(img, max_colors=max_colors, dither=dither)
    palette = img.getpalette()
    w, h = img.size
    num_colors = len(palette) // 3
    palette_colors = np.array(palette[:num_colors * 3], dtype=np.uint8).reshape(num_colors, 3)
    pixels_np = np.array(img, dtype=np.uint8)
    return pixels_np, palette_colors, w, h


def _rle_encode(vals, gri_limit=False):
    """RLE 编码。vals: uint8 数组，值域 [0x3F, 0x7F]。

    gri_limit=True 时限制 RLE 参数 ≤ 255（VT240 兼容）。
    """
    n = len(vals)
    if n == 0:
        return b""

    diff = np.diff(vals)
    changes = np.nonzero(diff)[0] + 1
    boundaries = np.empty(len(changes) + 2, dtype=np.intp)
    boundaries[0] = 0
    boundaries[1:-1] = changes
    boundaries[-1] = n

    out = bytearray()
    append = out.append
    extend = out.extend

    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        run = boundaries[i + 1] - start
        v = int(vals[start])
        if run >= 4:
            if gri_limit:
                # VT240 兼容：拆分为多段 ≤ 255
                while run > 0:
                    chunk = min(run, 255)
                    extend(b"!")
                    extend(_RUN_STR[chunk])
                    append(v)
                    run -= chunk
            else:
                extend(b"!")
                extend(_RUN_STR[run])
                append(v)
        else:
            extend(vals[start:start + run].tobytes())
    return bytes(out)


def encode_sixel(pixels_np, palette_colors, w, h, eight_bit=False, gri_limit=False):
    """将 numpy 像素数组编码为 Sixel 字符串。

    eight_bit=True  使用 8bit DCS (0x90 / 0x9C)
    gri_limit=True  限制 GRI 参数 ≤ 255
    """
    used_colors = np.unique(pixels_np)
    sixel_bands = (h + 5) // 6

    parts = bytearray()
    # DCS 头
    if eight_bit:
        parts.extend(b"\x900;0;0q")
    else:
        parts.extend(b"\x1bP0;0;0q")

    for idx in used_colors:
        r, g, b = int(palette_colors[idx, 0]), int(palette_colors[idx, 1]), int(palette_colors[idx, 2])
        parts.extend(f"#{idx};2;{r * 100 // 255};{g * 100 // 255};{b * 100 // 255}".encode("ascii"))

    for sy in range(0, h, 6):
        band = pixels_np[sy:sy + 6, :]
        band_h = band.shape[0]

        if band_h < 6:
            band_padded = np.zeros((6, w), dtype=np.uint8)
            band_padded[:band_h, :] = band
        else:
            band_padded = band

        band_colors = np.unique(band)
        n_colors = len(band_colors)

        masks = (band_padded[np.newaxis, :, :] == band_colors[:, np.newaxis, np.newaxis])
        bits_all = (masks.view(np.uint8) * _SIXEL_WEIGHTS).sum(axis=1).astype(np.uint8)

        for ci in range(n_colors):
            cidx = int(band_colors[ci])
            parts.extend(_COLOR_STR[cidx])
            parts.extend(_rle_encode(bits_all[ci] + 0x3F, gri_limit=gri_limit))
            parts.append(0x24)

        if parts[-1] == 0x24:
            parts[-1] = 0x2D
        else:
            parts.append(0x2D)

    # DCS 尾
    if eight_bit:
        parts.extend(b"\x9c")
    else:
        parts.extend(b"\x1b\\")

    return bytes(parts), sixel_bands


def get_gif_frames(path, max_px_width=640, max_colors=256, dither=False):
    """提取 GIF 所有帧，返回 (帧列表, 延迟列表) 或 (None, None)。"""
    img = Image.open(path)
    if not getattr(img, "is_animated", False) or img.n_frames <= 1:
        return None, None

    n_frames = img.n_frames
    canvas_size = img.size
    frame_arrays = []
    delays = []

    prev_canvas = None
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))

    for i in range(n_frames):
        img.seek(i)
        disposal = img.disposal_method if hasattr(img, "disposal_method") else 0

        if disposal == 3:
            prev_canvas = canvas.copy()

        frame = img.convert("RGBA")
        canvas.paste(frame, (0, 0), frame if frame.mode == "RGBA" else None)

        pixels_np, palette_colors, w, h = _preprocess_frame(
            canvas.copy(), max_px_width=max_px_width, max_colors=max_colors, dither=dither
        )
        frame_arrays.append((pixels_np, palette_colors, w, h))

        if disposal == 2:
            canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        elif disposal == 3 and prev_canvas is not None:
            canvas = prev_canvas.copy()

        delay = img.info.get("duration", 100)
        if delay <= 0:
            delay = 100
        delays.append(delay / 1000.0)

    return frame_arrays, delays


def _open_output(output_file):
    """打开输出文件，返回 (file_handle, need_close)。stdout 时返回 (None, False)。"""
    if output_file:
        return open(output_file, "wb"), True
    return None, False


def _write(out, data):
    """写入数据到文件或 stdout。"""
    if out is not None:
        out.write(data)
    else:
        sys.stdout.buffer.write(data)


def play_gif(path, max_px_width=640, max_colors=256, dither=False,
             output_file=None, loopmode="auto", eight_bit=False,
             gri_limit=False, ignore_delay=False):
    """在终端中播放 GIF 动画（流式编码 + 帧间差分）。"""
    frame_arrays, delays = get_gif_frames(path, max_px_width=max_px_width, max_colors=max_colors, dither=dither)
    if frame_arrays is None:
        return False

    n_frames = len(frame_arrays)
    print(
        f"[{path.name}] GIF 动画: {n_frames} 帧, "
        f"循环播放中 (Ctrl+C 停止)",
        file=sys.stderr,
    )

    out, need_close = _open_output(output_file)
    prev_pixels = None
    num_bands = 0

    try:
        first = True
        # loopmode: auto=终端循环/文件单次, force=强制循环, disable=只播一次
        if loopmode == "auto" and output_file:
            max_loops = 1  # 输出到文件时默认只播放一次
        elif loopmode == "disable":
            max_loops = 1
        else:
            max_loops = None
        loop_count = 0

        while max_loops is None or loop_count < max_loops:
            for i in range(n_frames):
                pixels_np, palette_colors, w, h = frame_arrays[i]

                if prev_pixels is not None and np.array_equal(pixels_np, prev_pixels):
                    if not ignore_delay:
                        time.sleep(delays[i])
                    continue

                t_frame = time.perf_counter()
                sixel_data, num_bands = encode_sixel(
                    pixels_np, palette_colors, w, h,
                    eight_bit=eight_bit, gri_limit=gri_limit
                )

                if not first:
                    _write(out, f"\x1b[{num_bands}A".encode())
                _write(out, sixel_data)
                if out is None:
                    sys.stdout.flush()

                del sixel_data
                first = False
                prev_pixels = pixels_np

                if not ignore_delay:
                    elapsed = time.perf_counter() - t_frame
                    remaining = delays[i] - elapsed
                    if remaining > 0:
                        time.sleep(remaining)

            loop_count += 1

    except KeyboardInterrupt:
        _write(out, b"\n")
        if out is None:
            sys.stdout.flush()
    finally:
        if need_close:
            out.close()

    return True


def show_static(path, max_px_width=640, max_colors=256, dither=False,
                output_file=None, eight_bit=False, gri_limit=False):
    """显示静态图片。"""
    img = Image.open(path)
    pixels_np, palette_colors, w, h = _preprocess_frame(
        img, max_px_width=max_px_width, max_colors=max_colors, dither=dither
    )
    sixel_data, _ = encode_sixel(
        pixels_np, palette_colors, w, h,
        eight_bit=eight_bit, gri_limit=gri_limit
    )
    print(
        f"[{path.name}] {img.size[0]}x{img.size[1]} -> Sixel ({len(sixel_data)} bytes, {max_colors} colors)",
        file=sys.stderr,
    )

    out, need_close = _open_output(output_file)
    _write(out, sixel_data)
    _write(out, b"\n")
    if need_close:
        out.close()


def main():
    default_cols = _get_terminal_columns()

    parser = argparse.ArgumentParser(
        prog="pysixel",
        description="Sixel 图片终端显示器",
        epilog="支持格式: PNG, JPEG, GIF, BMP, WebP 等 (PIL 支持的所有格式)\n"
               "动画 GIF 会自动循环播放，按 Ctrl+C 停止\n"
               "终端需支持 Sixel 协议 (Windows Terminal, xterm, WezTerm 等)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("image", help="图片文件路径")
    parser.add_argument("--no-anim", action="store_true", help="强制静态模式，GIF 只显示第一帧")
    parser.add_argument("--dither", action="store_true", help="启用 Bayer 有序抖动 (减少色带)")
    parser.add_argument("--colors", type=int, default=256, metavar="N",
                        help="调色板颜色数 (2-256, 默认 256)")
    parser.add_argument("--max-width", type=int, default=default_cols, metavar="COLS",
                        help=f"最大终端列宽 (默认 {default_cols}, 即终端实际宽度)")
    # 批次 1 新增参数
    parser.add_argument("-o", "--output", metavar="FILE", help="输出到文件而非终端")
    parser.add_argument("-l", "--loop", choices=["auto", "force", "disable"], default="auto",
                        help="GIF 循环模式: auto(默认) / force / disable")
    parser.add_argument("-7", dest="bit7", action="store_true", default=True, help="7bit DCS 模式 (默认)")
    parser.add_argument("-8", dest="bit8", action="store_true", help="8bit DCS 模式")
    parser.add_argument("-g", "--no-delay", action="store_true", help="忽略 GIF 帧延迟，尽快播放")
    parser.add_argument("-R", "--gri-limit", action="store_true", help="限制 GRI 参数 ≤ 255 (VT240 兼容)")

    args = parser.parse_args()

    path = Path(args.image)
    if not path.exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        sys.exit(1)

    max_px_width = args.max_width * 8
    max_colors = max(2, min(256, args.colors))
    eight_bit = args.bit8
    gri_limit = args.gri_limit

    common = dict(
        max_px_width=max_px_width, max_colors=max_colors, dither=args.dither,
        output_file=args.output, eight_bit=eight_bit, gri_limit=gri_limit,
    )

    if not args.no_anim:
        try:
            if play_gif(path, loopmode=args.loop, ignore_delay=args.no_delay, **common):
                return
        except Exception:
            pass

    show_static(path, **common)


if __name__ == "__main__":
    main()
