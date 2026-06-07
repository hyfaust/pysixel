"""在终端中以 Sixel 格式显示图片（需 Windows Terminal 或其他支持 Sixel 的终端）

优化技术:
- numpy 向量化: 替代 PIL 逐像素访问 (~13x 提速)
- 批量颜色计算: numpy broadcasting 一次算所有颜色
- RLE 压缩: DEC VT Sixel 协议 !COUNT CHAR
- 流式编码: 逐帧编码+释放，避免内存退化
- 自适应延迟: 编码耗时从 sleep 中扣除
- 抖动模式: Bayer 8x8 有序抖动 / Floyd-Steinberg 误差扩散 (可选)
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


def quantize(img, max_colors=256, dither="none", quality="auto"):
    """将图片量化为有限调色板。dither: "none" / "bayer"。quality 控制量化质量。"""
    rgb = img.convert("RGB")
    if dither == "bayer":
        arr = np.array(rgb, dtype=np.float32)
        h, w = arr.shape[:2]
        tile_y = (h + 7) // 8
        tile_x = (w + 7) // 8
        bayer = np.tile(_BAYER8, (tile_y, tile_x))[:h, :w]
        amplitude = 255.0 / max_colors
        arr += bayer[:, :, np.newaxis] * amplitude
        arr = np.clip(arr, 0, 255).astype(np.uint8)
        rgb = Image.fromarray(arr)
    method = Image.Quantize.MEDIANCUT
    if quality == "high":
        method = Image.Quantize.FASTOCTREE
    return rgb.quantize(max_colors, method=method)


def _floyd_steinberg(rgb_np, palette_colors, w, h):
    """Floyd-Steinberg 误差扩散抖动（与 libsixel diffuse_fs 一致）。

    对量化后的像素进行误差扩散：对每个像素找最近调色板色，
    计算量化误差，按 FS 权重传播到相邻像素。

    权重分布:
              curr    7/16
    3/16    5/16    1/16
    """
    pal = palette_colors.astype(np.float32)

    # 工作缓冲区
    err = rgb_np.astype(np.float32).reshape(h, w, 3)
    out = np.empty((h, w), dtype=np.uint8)

    for y in range(h):
        for x in range(w):
            r, g, b = err[y, x, 0], err[y, x, 1], err[y, x, 2]
            # clamp
            r = max(0.0, min(255.0, r))
            g = max(0.0, min(255.0, g))
            b = max(0.0, min(255.0, b))

            # 找最近调色板色
            dr = pal[:, 0] - r
            dg = pal[:, 1] - g
            db = pal[:, 2] - b
            dist = dr * dr + dg * dg + db * db
            best = int(np.argmin(dist))
            out[y, x] = best

            # 量化误差
            er = r - pal[best, 0]
            eg = g - pal[best, 1]
            eb = b - pal[best, 2]

            # Floyd-Steinberg 误差传播
            # 右 (7/16)
            if x < w - 1:
                err[y, x + 1, 0] += er * (7.0 / 16.0)
                err[y, x + 1, 1] += eg * (7.0 / 16.0)
                err[y, x + 1, 2] += eb * (7.0 / 16.0)
            # 左下 (3/16)
            if x > 0 and y < h - 1:
                err[y + 1, x - 1, 0] += er * (3.0 / 16.0)
                err[y + 1, x - 1, 1] += eg * (3.0 / 16.0)
                err[y + 1, x - 1, 2] += eb * (3.0 / 16.0)
            # 下 (5/16)
            if y < h - 1:
                err[y + 1, x, 0] += er * (5.0 / 16.0)
                err[y + 1, x, 1] += eg * (5.0 / 16.0)
                err[y + 1, x, 2] += eb * (5.0 / 16.0)
            # 右下 (1/16)
            if x < w - 1 and y < h - 1:
                err[y + 1, x + 1, 0] += er * (1.0 / 16.0)
                err[y + 1, x + 1, 1] += eg * (1.0 / 16.0)
                err[y + 1, x + 1, 2] += eb * (1.0 / 16.0)

    return out


_RESAMPLE_FILTERS = {
    "nearest": Image.Resampling.NEAREST,
    "bilinear": Image.Resampling.BILINEAR,
    "bicubic": Image.Resampling.BICUBIC,
    "lanczos2": Image.Resampling.LANCZOS,
    "lanczos3": Image.Resampling.LANCZOS,
    "lanczos4": Image.Resampling.LANCZOS,
    "gaussian": Image.Resampling.BOX,
    "hamming": Image.Resampling.HAMMING,
}


def _parse_color(color_str):
    """解析颜色字符串，返回 (R, G, B) 元组。"""
    s = color_str.strip().lstrip("#")
    if len(s) == 3:
        return (int(s[0]*2, 16), int(s[1]*2, 16), int(s[2]*2, 16))
    if len(s) == 6:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    raise ValueError(f"无法解析颜色: {color_str}")


def _parse_crop(crop_str):
    """解析裁剪字符串 'WxH+X+Y'，返回 (x, y, w, h)。"""
    import re
    m = re.match(r"(\d+)x(\d+)\+(\d+)\+(\d+)", crop_str)
    if not m:
        raise ValueError(f"无法解析裁剪: {crop_str} (格式: WxH+X+Y)")
    w, h, x, y = int(m[1]), int(m[2]), int(m[3]), int(m[4])
    return (x, y, x + w, y + h)


def _resize_for_terminal(img, max_px_width, target_w=None, target_h=None, resample="bilinear"):
    """缩放图片。优先使用 target_w/target_h，否则按 max_px_width 自动缩放。"""
    resample_filter = _RESAMPLE_FILTERS.get(resample, Image.Resampling.LANCZOS)

    if target_w or target_h:
        # 显式指定宽高
        w, h = img.size
        if target_w and target_h:
            w, h = target_w, target_h
        elif target_w:
            ratio = target_w / w
            w, h = target_w, int(h * ratio)
        else:
            ratio = target_h / h
            w, h = int(w * ratio), target_h
        return img.resize((w, h), resample_filter)
    else:
        # 自动缩放（适应终端宽度）
        w, h = img.size
        if w > max_px_width:
            ratio = max_px_width / w
            w, h = max_px_width, int(h * ratio)
        return img.resize((w, h), resample_filter)


def _preprocess_frame(img, max_px_width=640, max_colors=256, dither="none",
                      target_w=None, target_h=None, resample="bilinear",
                      crop=None, monochrome=False, bgcolor=None,
                      inverse=False, quality="auto", no_resize=False):
    """预处理一帧：crop → resize → monochrome/bgcolor → quantize → numpy。"""
    if crop:
        img = img.crop(crop)
    if bgcolor:
        bg = Image.new("RGB", img.size, bgcolor)
        if img.mode == "RGBA":
            bg.paste(img, mask=img.split()[3])
            img = bg
        else:
            img = img.convert("RGB")
    if not no_resize:
        img = _resize_for_terminal(img, max_px_width, target_w=target_w, target_h=target_h, resample=resample)
    if monochrome:
        img = img.convert("L")
    if inverse:
        from PIL import ImageOps
        img = ImageOps.invert(img.convert("RGB"))

    if dither == "fs":
        # Floyd-Steinberg: 先量化获取调色板，再误差扩散
        rgb_np = np.array(img.convert("RGB"), dtype=np.uint8)
        # A1: 用 15-bit 哈希估算独特色数，若 ≤ max_colors 则跳过 FS
        r16 = rgb_np[:, :, 0].astype(np.uint16)
        g16 = rgb_np[:, :, 1].astype(np.uint16)
        b16 = rgb_np[:, :, 2].astype(np.uint16)
        hashes = (r16 >> 3) << 10 | (g16 >> 3) << 5 | (b16 >> 3)
        unique_count = len(np.unique(hashes))
        if unique_count <= max_colors:
            # 原图颜色数不超过调色板，量化无损，跳过 FS
            img = quantize(img, max_colors=max_colors, dither="none", quality=quality)
            palette = img.getpalette()
            w, h = img.size
            num_colors = len(palette) // 3
            palette_colors = np.array(palette[:num_colors * 3], dtype=np.uint8).reshape(num_colors, 3)
            pixels_np = np.array(img, dtype=np.uint8)
            return pixels_np, palette_colors, w, h
        quantized = quantize(img, max_colors=max_colors, dither="none", quality=quality)
        palette = quantized.getpalette()
        w, h = quantized.size
        num_colors = len(palette) // 3
        palette_colors = np.array(palette[:num_colors * 3], dtype=np.uint8).reshape(num_colors, 3)
        pixels_np = _floyd_steinberg(rgb_np, palette_colors, w, h)
        return pixels_np, palette_colors, w, h
    else:
        img = quantize(img, max_colors=max_colors, dither=dither, quality=quality)
        palette = img.getpalette()
        w, h = img.size
        num_colors = len(palette) // 3
        palette_colors = np.array(palette[:num_colors * 3], dtype=np.uint8).reshape(num_colors, 3)
        pixels_np = np.array(img, dtype=np.uint8)
        return pixels_np, palette_colors, w, h


def _map_to_palette(rgb_np, palette_colors):
    """将 RGB 像素映射到最近调色板色（numpy 向量化）。"""
    h, w = rgb_np.shape[:2]
    flat = rgb_np.reshape(-1, 3).astype(np.float32)
    pal = palette_colors.astype(np.float32)
    diff = flat[:, np.newaxis, :] - pal[np.newaxis, :, :]
    dist = (diff * diff).sum(axis=2)
    return dist.argmin(axis=1).reshape(h, w).astype(np.uint8)


def _rle_encode(vals, gri_limit=False, encode_policy="auto"):
    """RLE 编码。vals: uint8 数组，值域 [0x3F, 0x7F]。

    gri_limit=True  限制 RLE 参数 ≤ 255（VT240 兼容）。
    encode_policy: "auto" / "fast" (跳过RLE) / "size" (阈值=2)
    """
    n = len(vals)
    if n == 0:
        return b""

    # fast 模式：跳过 RLE，直接返回原始字节
    if encode_policy == "fast":
        return vals.tobytes()

    rle_threshold = 2 if encode_policy == "size" else 3

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
        if run >= rle_threshold:
            if gri_limit:
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


def encode_sixel(pixels_np, palette_colors, w, h, eight_bit=False, gri_limit=False,
                 encode_policy="auto", passthrough=False):
    """将 numpy 像素数组编码为 Sixel 字符串。

    eight_bit=True      使用 8bit DCS (0x90 / 0x9C)
    gri_limit=True      限制 GRI 参数 ≤ 255
    encode_policy       "auto" / "fast" / "size"
    passthrough=True    包裹 tmux/screen 穿透序列
    """
    used_colors = np.unique(pixels_np)
    sixel_bands = (h + 5) // 6

    parts = bytearray()

    # tmux/screen 穿透头
    if passthrough:
        parts.extend(b"\x1bPtmux;")
        parts.extend(b"\x1b\\")

    # DCS 头 + 光栅属性
    if eight_bit:
        parts.extend(b"\x900;0;0q")
    else:
        parts.extend(b"\x1bP0;0;0q")
    parts.extend(f'"1;1;{w};{h}'.encode("ascii"))

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
            parts.extend(_rle_encode(bits_all[ci] + 0x3F, gri_limit=gri_limit, encode_policy=encode_policy))
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

    # tmux/screen 穿透尾
    if passthrough:
        parts.extend(b"\x1b\\")

    return bytes(parts), sixel_bands


def get_gif_frames(path, max_px_width=640, max_colors=256, dither="none",
                   target_w=None, target_h=None, resample="bilinear",
                   crop=None, monochrome=False, bgcolor=None,
                   inverse=False, quality="auto", no_resize=False):
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
    cached_palette = None  # A2: 调色板缓存

    for i in range(n_frames):
        img.seek(i)
        disposal = img.disposal_method if hasattr(img, "disposal_method") else 0

        if disposal == 3:
            prev_canvas = canvas.copy()

        frame = img.convert("RGBA")
        canvas.paste(frame, (0, 0), frame if frame.mode == "RGBA" else None)

        if cached_palette is not None and dither != "fs":
            # A2: 复用调色板，跳过量化
            frame_img = canvas.copy()
            if crop:
                frame_img = frame_img.crop(crop)
            if bgcolor:
                bg = Image.new("RGB", frame_img.size, bgcolor)
                if frame_img.mode == "RGBA":
                    bg.paste(frame_img, mask=frame_img.split()[3])
                    frame_img = bg
                else:
                    frame_img = frame_img.convert("RGB")
            if not no_resize:
                frame_img = _resize_for_terminal(frame_img, max_px_width, target_w=target_w, target_h=target_h, resample=resample)
            if monochrome:
                frame_img = frame_img.convert("L")
            if inverse:
                from PIL import ImageOps
                frame_img = ImageOps.invert(frame_img.convert("RGB"))
            rgb_np = np.array(frame_img.convert("RGB"), dtype=np.uint8)
            w, h = frame_img.size
            pixels_np = _map_to_palette(rgb_np, cached_palette)
            frame_arrays.append((pixels_np, cached_palette, w, h))
        else:
            pixels_np, palette_colors, w, h = _preprocess_frame(
                canvas.copy(), max_px_width=max_px_width, max_colors=max_colors, dither=dither,
                target_w=target_w, target_h=target_h, resample=resample,
                crop=crop, monochrome=monochrome, bgcolor=bgcolor,
                inverse=inverse, quality=quality, no_resize=no_resize
            )
            if cached_palette is None:
                cached_palette = palette_colors
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


def play_gif(path, max_px_width=640, max_colors=256, dither="none",
             output_file=None, loopmode="auto", eight_bit=False,
             gri_limit=False, ignore_delay=False,
             target_w=None, target_h=None, resample="bilinear",
             crop=None, monochrome=False, bgcolor=None,
             inverse=False, quality="auto", encode_policy="auto",
             passthrough=False, no_resize=False):
    """在终端中播放 GIF 动画（流式编码 + 帧间差分）。"""
    frame_arrays, delays = get_gif_frames(
        path, max_px_width=max_px_width, max_colors=max_colors, dither=dither,
        target_w=target_w, target_h=target_h, resample=resample,
        crop=crop, monochrome=monochrome, bgcolor=bgcolor,
        inverse=inverse, quality=quality, no_resize=no_resize
    )
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
                    eight_bit=eight_bit, gri_limit=gri_limit,
                    encode_policy=encode_policy, passthrough=passthrough
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


def show_static(path, max_px_width=640, max_colors=256, dither="none",
                output_file=None, eight_bit=False, gri_limit=False,
                target_w=None, target_h=None, resample="bilinear",
                crop=None, monochrome=False, bgcolor=None,
                inverse=False, quality="auto", encode_policy="auto",
                passthrough=False, no_resize=False):
    """显示静态图片。"""
    img = Image.open(path)
    pixels_np, palette_colors, w, h = _preprocess_frame(
        img, max_px_width=max_px_width, max_colors=max_colors, dither=dither,
        target_w=target_w, target_h=target_h, resample=resample,
        crop=crop, monochrome=monochrome, bgcolor=bgcolor,
        inverse=inverse, quality=quality, no_resize=no_resize
    )
    sixel_data, _ = encode_sixel(
        pixels_np, palette_colors, w, h,
        eight_bit=eight_bit, gri_limit=gri_limit,
        encode_policy=encode_policy, passthrough=passthrough
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
        prog="pyimg2six",
        description="Sixel 图片终端显示器",
        epilog="支持格式: PNG, JPEG, GIF, BMP, WebP 等 (PIL 支持的所有格式)\n"
               "动画 GIF 会自动循环播放，按 Ctrl+C 停止\n"
               "终端需支持 Sixel 协议 (Windows Terminal, xterm, WezTerm 等)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("image", help="图片文件路径")
    parser.add_argument("--no-anim", action="store_true", help="强制静态模式，GIF 只显示第一帧")
    parser.add_argument("-d", "--dither", default="none", choices=["none", "bayer", "fs"],
                        help="抖动模式: none(默认) / bayer(Bayer有序) / fs(Floyd-Steinberg误差扩散)")
    parser.add_argument("--colors", type=int, default=256, metavar="N",
                        help="调色板颜色数 (2-256, 默认 256)")
    parser.add_argument("--max-width", type=int, default=default_cols, metavar="COLS",
                        help=f"最大终端列宽 (默认 {default_cols}, 即终端实际宽度)")
    parser.add_argument("--no-resize", action="store_true",
                        help="保持原始分辨率，不缩放")
    # 批次 1 参数
    parser.add_argument("-o", "--output", metavar="FILE", help="输出到文件而非终端")
    parser.add_argument("-l", "--loop", choices=["auto", "force", "disable"], default="auto",
                        help="GIF 循环模式: auto(默认) / force / disable")
    parser.add_argument("-7", dest="bit7", action="store_true", default=True, help="7bit DCS 模式 (默认)")
    parser.add_argument("-8", dest="bit8", action="store_true", help="8bit DCS 模式")
    parser.add_argument("-g", "--no-delay", action="store_true", help="忽略 GIF 帧延迟，尽快播放")
    parser.add_argument("-R", "--gri-limit", action="store_true", help="限制 GRI 参数 ≤ 255 (VT240 兼容)")
    # 批次 2 参数
    parser.add_argument("-w", "--width", type=int, metavar="PX", help="输出宽度 (像素)")
    parser.add_argument("-H", "--height", type=int, metavar="PX", help="输出高度 (像素)")
    parser.add_argument("-r", "--resample", default="bilinear",
                        choices=list(_RESAMPLE_FILTERS.keys()),
                        help="重采样滤波器 (默认 bilinear)")
    parser.add_argument("-c", "--crop", metavar="WxH+X+Y", help="裁剪区域 (如 100x100+10+10)")
    parser.add_argument("-e", "--monochrome", action="store_true", help="单色模式 (灰度)")
    parser.add_argument("-B", "--bgcolor", metavar="COLOR", help="背景色 (如 #ffffff)")
    # 批次 3 参数
    parser.add_argument("-E", "--encode", default="auto",
                        choices=["auto", "fast", "size"],
                        help="编码策略: auto(默认) / fast(跳过RLE) / size(更小体积)")
    parser.add_argument("-q", "--quality", default="auto",
                        choices=["auto", "low", "high", "full"],
                        help="量化质量: auto(默认) / low(快) / high / full(最佳)")
    parser.add_argument("-P", "--passthrough", action="store_true",
                        help="tmux/screen 穿透模式")
    parser.add_argument("-i", "--inverse", action="store_true", help="反转颜色 (底片效果)")

    args = parser.parse_args()

    path = Path(args.image)
    if not path.exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        sys.exit(1)

    max_px_width = args.max_width * 8
    max_colors = max(2, min(256, args.colors))
    eight_bit = args.bit8
    gri_limit = args.gri_limit

    # 解析批次 2 参数
    crop_box = _parse_crop(args.crop) if args.crop else None
    bgcolor_rgb = _parse_color(args.bgcolor) if args.bgcolor else None

    common = dict(
        max_px_width=max_px_width, max_colors=max_colors, dither=args.dither,
        output_file=args.output, eight_bit=eight_bit, gri_limit=gri_limit,
        target_w=args.width, target_h=args.height, resample=args.resample,
        crop=crop_box, monochrome=args.monochrome, bgcolor=bgcolor_rgb,
        inverse=args.inverse, quality=args.quality, encode_policy=args.encode,
        passthrough=args.passthrough, no_resize=args.no_resize,
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
