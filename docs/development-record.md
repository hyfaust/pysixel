# pysixel GIF 动画播放开发记录

> 作者：hyfaust
> 项目：pysixel — 终端 Sixel 图片显示器
> 仓库：https://github.com/hyfaust/pysixel
> 许可证：GPL v3
> 记录日期：2026-06-07

---

## 目录

1. [Sixel 协议基础](#1-sixel-协议基础)
2. [V0：原始实现](#2-v0原始实现)
3. [GIF 帧提取与 Disposal 处理](#3-gif-帧提取与-disposal-处理)
4. [numpy 向量化](#4-numpy-向量化)
5. [流式编码](#5-流式编码)
6. [RLE 压缩](#6-rle-压缩)
7. [批量颜色计算](#7-批量颜色计算)
8. [颜色缩减](#8-颜色缩减)
9. [字符串缓存](#9-字符串缓存)
10. [Bayer 有序抖动](#10-bayer-有序抖动)
11. [自适应延迟](#11-自适应延迟)
12. [Filter Bank 实验](#12-filter-bank-实验)
13. [Bug 修复](#13-bug-修复)
14. [CLI 帮助信息](#14-cli-帮助信息)
15. [纯 Python 优化分析](#15-纯-python-优化分析)

---

## 1. Sixel 协议基础

Sixel 是一种古老的终端图形协议，最初由 DEC 为 VT240 终端设计，现被 Windows Terminal、xterm、WezTerm 等现代终端重新支持。

### 1.1 DCS 序列

Sixel 图像以 DCS（Device Control String）序列包裹：

```
ESC P 0;0;0q ... ESC \
    ^^^^^^^
    参数: P1;P2;P3
    P1=0 表示不锁定调色板
    P2=0 表示像素宽高比 1:1
    P3=0 表示无水平网格
```

### 1.2 6 像素条带

Sixel 将图像按每 6 行像素为一个"条带"（band）编码。每个像素列是一个 6-bit 值：

```
行 0 → bit 0 → 权重 1
行 1 → bit 1 → 权重 2
行 2 → bit 2 → 权重 4
行 3 → bit 3 → 权重 8
行 4 → bit 4 → 权重 16
行 5 → bit 5 → 权重 32
```

6 个 bit 的值加上 `?`（ASCII 0x3F）即为 Sixel 字符。例如 `?` = 0x3F = 63 = 全部 6 行点亮。

### 1.3 颜色切换与 RLE

```sixel
#0;2;100;0;0    设置颜色 0 为 RGB(255,0,0)（值为百分比）
#1;2;0;100;0    设置颜色 1 为 RGB(0,255,0)
????????        输出 8 列颜色 0 的像素
$               回车（不换行，回到当前条带起始列）
#1              切换到颜色 1
????????        输出 8 列颜色 1 的像素
-               换行到下一个条带
```

RLE 格式：`!COUNT CHAR` — 将 CHAR 重复 COUNT 次。例如 `!8?` 等价于 `????????`。

---

## 2. V0：原始实现

### 2.1 实现方式

原始版本使用 PIL 逐像素访问，256 色调色板：

```python
def encode_sixel(img):
    """原始版：PIL 逐像素编码"""
    pixels = img.load()
    w, h = img.size
    palette = img.getpalette()

    # 逐 band、逐颜色、逐像素
    for sy in range(0, h, 6):
        for color_idx in range(256):
            for x in range(w):
                bits = 0
                for bit in range(6):
                    y = sy + bit
                    if y < h and pixels[x, y] == color_idx:
                        bits |= 1 << bit
                if bits > 0:
                    sixel_char = chr(bits + 0x3F)
                    output(sixel_char)
```

### 2.2 性能

- 单帧编码：**475ms**
- 输出体积：880KB/帧
- 500x500 GIF 33 帧总耗时：**48.4 秒**

### 2.3 瓶颈

```
32,000,000 次 pixels[x,y] 调用 x 100ns/次 = 3.2s（占编码时间 98.6%）
```

---

## 3. GIF 帧提取与 Disposal 处理

### 3.1 GIF Disposal Methods

GIF 格式允许每帧指定不同的"处置方式"，控制帧之间的叠加行为：

| Disposal | 含义 | 处理方式 |
|----------|------|----------|
| 0 / 1 | 未指定 / 不处置 | 直接叠加到画布 |
| 2 | 恢复背景 | 清除当前帧区域为背景色 |
| 3 | 恢复上一帧 | 将画布恢复到当前帧绘制前的状态 |

### 3.2 实现代码

```python
def get_gif_frames(path, dither=False):
    """提取 GIF 所有帧，处理 disposal 和合成"""
    img = Image.open(path)
    canvas = Image.new("RGBA", img.size, (0, 0, 0, 0))
    prev_canvas = None

    for i in range(img.n_frames):
        img.seek(i)
        disposal = img.disposal_method if hasattr(img, "disposal_method") else 0

        if disposal == 3:
            prev_canvas = canvas.copy()

        frame = img.convert("RGBA")
        canvas.paste(frame, (0, 0), frame)

        # 预处理：resize -> quantize -> numpy array
        pixels_np, palette_colors, w, h = _preprocess_frame(canvas.copy(), dither=dither)

        if disposal == 2:
            canvas = Image.new("RGBA", img.size, (0, 0, 0, 0))
        elif disposal == 3 and prev_canvas is not None:
            canvas = prev_canvas.copy()
```

### 3.3 动画播放

动画的核心是**原地覆盖**：每次输出新帧前，将光标上移到动画区域顶部。

```python
sys.stdout.write(f"\x1b[{num_bands}A")  # \x1b[nA = 光标上移 n 行
sys.stdout.buffer.write(sixel_data)
sys.stdout.flush()
```

Sixel 图像在终端中占据固定行数（`ceil(height / 6)` 行）。通过精确上移这些行数，新帧覆盖旧帧，实现动画效果。

---

## 4. numpy 向量化

### 4.1 变更内容

将 PIL `PixelAccess` 替换为 `np.array(img)`，用批量比较替代逐像素循环。

### 4.2 优化前

```python
# 旧：3200 万次 Python 方法调用
pixels = img.load()
for color_idx in band_colors:
    for x in range(w):
        for bit in range(6):
            if pixels[x, y] == color_idx:  # 每次 ~100ns
                bits |= 1 << bit
```

### 4.3 优化后

```python
# 新：numpy 批量运算
pixels_np = np.array(img)  # shape (h, w), dtype uint8
_SIXEL_WEIGHTS = np.array([1, 2, 4, 8, 16, 32], dtype=np.uint8).reshape(6, 1)

for color_idx in band_colors:
    mask = (band == color_idx)  # 向量化比较，~5us/3000 元素
    bits = (mask.view(np.uint8) * _SIXEL_WEIGHTS).sum(axis=0)  # 向量化累加
```

### 4.4 原理

| 方面 | Python 循环 | numpy 向量化 |
|------|------------|-------------|
| 循环开销 | 每次迭代 ~50ns Python 开销 | 无 Python 循环，C 层批量处理 |
| 类型检查 | 每次比较都做动态类型检查 | 编译时确定类型 |
| 缓存友好 | 随机访问 PIL 像素 | 连续内存访问 |
| SIMD | 无 | 可利用 CPU SIMD 指令 |

### 4.5 效果

```
编码耗时: 475ms -> 121ms（3.9x 提速）
```

---

## 5. 流式编码

### 5.1 问题

预编码全部 33 帧时，帧 0-2 正常（~320ms），帧 3 开始突然变慢（~1300ms）：

```
帧 0:  323ms  ← 正常
帧 3: 1323ms  ← 突然 4x 变慢！
```

### 5.2 根因

33 帧的 numpy 数组 + 编码字节串全部堆积在内存中（~10MB），触发：
1. Python 内存分配器碎片化
2. GC 压力——大量临时对象触发垃圾回收
3. CPU 缓存污染——工作集超出 L2/L3 缓存

### 5.3 优化前

```python
# 预编码全部帧（内存累积）
encoded = []
for frame in frames:
    encoded.append(encode_sixel(frame))  # 33 帧数据全部驻留内存
```

### 5.4 优化后

```python
# 流式编码（逐帧释放）
for i in range(n_frames):
    sixel_data, num_bands = encode_sixel(pixels_np, palette_colors, w, h)
    sys.stdout.buffer.write(sixel_data)
    sys.stdout.flush()
    del sixel_data  # 立即释放，保持内存平稳
```

### 5.5 效果

| 帧序号 | 预编码全部 | 流式编码 |
|--------|-----------|---------|
| 帧 0 | 323ms | 342ms |
| 帧 3 | 1,323ms | 329ms |
| 帧 32 | — | 309ms |

流式编码全程稳定，消除了 4 倍退化。

---

## 6. RLE 压缩

### 6.1 变更内容

添加 `_rle_encode()` 函数，对 Sixel 字符序列进行游程编码。

### 6.2 优化前

```python
# 旧：逐字节 append（慢）
for k in range(run):
    out.append(int(vals[start + k]))
```

### 6.3 优化后

```python
# 新：numpy 加速边界检测 + 切片 tobytes
def _rle_encode(vals):
    diff = np.diff(vals)
    changes = np.nonzero(diff)[0] + 1
    boundaries = np.empty(len(changes) + 2, dtype=np.intp)
    boundaries[0] = 0
    boundaries[1:-1] = changes
    boundaries[-1] = n

    out = bytearray()
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        run = boundaries[i + 1] - start
        v = int(vals[start])
        if run >= 4:
            out.extend(b"!")
            out.extend(_RUN_STR[run])
            out.append(v)
        else:
            out.extend(vals[start:start + run].tobytes())
    return bytes(out)
```

### 6.4 RLE 阈值

仅对连续 >= 4 次的重复进行 RLE 编码。因为 `!4X` 本身占 3 字节（`!`, `4`, `X`），与 4 个 `X` 相同，只有 >= 4 时才有收益。

### 6.5 效果

| 指标 | 无 RLE | 有 RLE |
|------|--------|--------|
| 每帧输出 | 880KB | 86KB |
| 压缩比 | 1.0x | **10.2x** |

---

## 7. 批量颜色计算

### 7.1 优化前

```python
# 逐颜色循环（134 次 numpy 操作）
for color_idx in band_colors:
    mask = (band == color_idx)
    bits = (mask * weights).sum(axis=0)
```

### 7.2 优化后

```python
# 批量计算（1 次 numpy 操作）
masks = (band_padded[np.newaxis, :, :] == band_colors[:, np.newaxis, np.newaxis])
bits_all = (masks.view(np.uint8) * _SIXEL_WEIGHTS).sum(axis=1).astype(np.uint8)
```

### 7.3 原理

numpy Broadcasting 将 `n_colors` 次独立操作合并为 1 次：

```
band_padded:  shape (6, w)                 # 6 行像素
band_colors:  shape (n_colors,)            # 该 band 中的颜色

band_padded[np.newaxis, :, :]              # shape (1, 6, w)
band_colors[:, np.newaxis, np.newaxis]     # shape (n_colors, 1, 1)

masks:         shape (n_colors, 6, w)      # 每个颜色对每个像素的掩码
```

### 7.4 效果

```
128 色: 102ms -> 75ms（1.36x 提速）
```

---

## 8. 颜色缩减

### 8.1 变更内容

将默认调色板从 256 色减少到 32 色：

```python
DEFAULT_COLORS = 32  # 原为 256
```

### 8.2 原理

减少每 band 的颜色迭代次数。编码时间与颜色数近似成正比：

| 调色板 | 每 band 平均颜色数 | 编码耗时 |
|--------|-------------------|---------|
| 256 色 | ~134 | 102ms |
| 128 色 | ~100 | 75ms |
| 64 色 | ~60 | 51ms |
| 32 色 | ~30 | 36ms |

### 8.3 效果

256 -> 32 色提速 **2.8 倍**。

### 8.4 质量权衡

32 色会产生可见的色带（color banding），但对 GIF 动画（本身色彩有限）通常可接受。通过 `--dither` 选项（Bayer 有序抖动）可缓解。

---

## 9. 字符串缓存

### 9.1 优化前

```python
# 循环中反复 encode()
parts.extend(f"#{color_idx}".encode("ascii"))
parts.extend(str(run).encode("ascii"))
```

### 9.2 优化后

```python
# 预构建（模块加载时一次性）
_COLOR_STR = [f"#{i}".encode("ascii") for i in range(256)]
_RUN_STR = [str(i).encode("ascii") for i in range(MAX_PX_WIDTH + 1)]

# 循环中直接查表
parts.extend(_COLOR_STR[cidx])
parts.extend(_RUN_STR[run])
```

### 9.3 效果

约 **1.1x** 提速。消除循环中重复的字符串构造和编码开销。

---

## 10. Bayer 有序抖动

### 10.1 背景

32 色调色板在色彩丰富的图片上会产生明显色带。Bayer 有序抖动通过在量化前添加位置相关偏移来减少色带。

### 10.2 实现

来源：libsixel 的 A-Dither 抖动方法。

```python
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

def quantize(img, max_colors=DEFAULT_COLORS, dither=False):
    rgb = img.convert("RGB")
    if dither:
        arr = np.array(rgb, dtype=np.float32)
        h, w = arr.shape[:2]
        bayer = np.tile(_BAYER8, ((h + 7) // 8, (w + 7) // 8))[:h, :w]
        arr += bayer[:, :, np.newaxis] * (255.0 / max_colors)
        arr = np.clip(arr, 0, 255).astype(np.uint8)
        rgb = Image.fromarray(arr)
    return rgb.quantize(max_colors, method=Image.Quantize.MEDIANCUT)
```

### 10.3 效果

| 指标 | 无抖动 | 有抖动 |
|------|--------|--------|
| 单帧编码 | 31.7ms | 60.6ms |
| 输出体积 | 71KB | 143KB |

抖动减少色带伪影，但编码耗时增加约 80%，输出体积翻倍。

---

## 11. 自适应延迟

### 11.1 问题

GIF 帧延迟是帧间间隔，不是帧显示时间。如果编码耗时 36ms、帧延迟 30ms：

```
旧方式: 实际帧时间 = 36ms + 30ms = 66ms（~15 fps）
新方式: 实际帧时间 = 36ms（编码已超过延迟，不 sleep）（~28 fps）
```

### 11.2 优化前

```python
time.sleep(delays[i])  # 固定延迟，不扣除编码时间
```

### 11.3 优化后

```python
t_frame = time.perf_counter()
sixel_data, num_bands = encode_sixel(pixels_np, palette_colors, w, h)
# ... output ...
elapsed = time.perf_counter() - t_frame
remaining = delays[i] - elapsed
if remaining > 0:
    time.sleep(remaining)
```

### 11.4 时间线

```
|-- 编码 --|-- sleep --|-- 编码 --|-- sleep --|
           |<-- 帧延迟 -->|         |<-- 帧延迟 -->|
```

---

## 12. Filter Bank 实验

### 12.1 来源

分析 chafa 1.18.2 源码中的 Filter Bank 优化后，尝试移植到 Python。

### 12.2 chafa 的 Filter Bank（C 代码）

```c
// 每 64 像素为一个 bank，用位域记录哪些颜色出现
if (!filter_get(srow, pen, i / FILTER_BANK_WIDTH)) {
    n_reps += FILTER_BANK_WIDTH;  // 跳过 64 像素
    continue;
}
```

### 12.3 Python 移植实现

```python
bank_has_color = np.zeros((n_colors, n_banks), dtype=bool)
for ci in range(n_colors):
    for bi in range(n_banks):
        bstart = bi * FILTER_BANK_WIDTH
        bend = min(bstart + FILTER_BANK_WIDTH, w)
        if np.any(bits_all[ci, bstart:bend] != 0x3F):
            bank_has_color[ci, bi] = True
```

### 12.4 结果：慢 2.4 倍，已回退

```
v1 baseline:       34.7ms/帧
v2 + Filter Bank:  82.6ms/帧  ← 更慢！
```

**根因**：Filter Bank 是为 C 语言逐像素循环设计的。numpy 向量化已经一次性处理所有像素，Filter Bank 额外引入的数组分配 + `np.any()` 调用 + 分支判断超过了它节省的时间。

**结论**：已回退。C 级别的逐像素优化不适用于向量化 Python 实现。

---

## 13. Bug 修复

### 13.1 `_RUN_STR` IndexError（图片宽度 > 512px）

**现象**：处理宽度 > 512px 的图片时抛出 `IndexError: list index out of range`

**根因**：`_RUN_STR` 列表大小为 513（覆盖 run <= 512），但 `MAX_PX_WIDTH = 640`。当图片宽度为 613px 且产生长 RLE run 时，`_RUN_STR[run]` 越界。

**修复前**：
```python
_RUN_STR = [str(i).encode("ascii") for i in range(513)]  # 只覆盖到 512
```

**修复后**：
```python
_RUN_STR = [str(i).encode("ascii") for i in range(MAX_PX_WIDTH + 1)]  # 覆盖到 640
```

**教训**：预构建缓存的大小必须与所有可能的输入范围一致。

---

## 14. CLI 帮助信息

### 14.1 变更内容

当用户不带参数调用脚本时，显示帮助信息而非报错。

```python
def main():
    if not args:
        prog = Path(sys.argv[0]).name
        print(f"pysixel — Sixel 图片终端显示器\n")
        print(f"用法: {prog} [选项] <图片路径>\n")
        print(f"选项:")
        print(f"  --no-anim    强制静态模式，GIF 只显示第一帧")
        print(f"  --dither     启用 Bayer 有序抖动 (减少色带)\n")
        print(f"支持格式: PNG, JPEG, GIF, BMP, WebP 等")
        print(f"动画 GIF 会自动循环播放，按 Ctrl+C 停止")
        print(f"终端需支持 Sixel 协议 (Windows Terminal, xterm, WezTerm 等)")
        sys.exit(0)
```

---

## 15. 纯 Python 优化分析

### 15.1 列预计算方案

在不依赖 numpy 的情况下，通过预计算每列的颜色映射实现优化：

```python
# 纯 Python 列预计算
col_colors = []
for x in range(w):
    col = [pixels_np[y, x] for y in range(h)]
    col_colors.append(col)

# 编码时直接查表
for sy in range(0, h, 6):
    for x in range(w):
        bits = 0
        for bit in range(6):
            if sy + bit < h:
                bits |= (1 << bit) if col_colors[x][sy + bit] == color_idx else 0
```

### 15.2 性能

| 方案 | 单帧编码 | 加速比 | 需要 numpy |
|------|---------|--------|-----------|
| V0 原始版 | 475ms | 1.0x | 否 |
| 纯 Python 列预计算 | 48ms | **9.9x** | 否 |
| numpy 向量化（最终版） | 36ms | 13.2x | 是 |

纯 Python 列预计算可达 9.9x 加速，接近 numpy 版本的性能。这说明 PIL `pixels[x,y]` 的 Python 方法调用开销是主要瓶颈，消除它就能获得巨大提升。

---

## 16. 最终架构

### 16.1 数据流

```
图片文件
  │
  ▼
resize (Lanczos) → 量化 (MEDIANCUT, 32色) → numpy array
  │
  ▼
encode_sixel()
  ├── 批量向量化 (numpy broadcasting)
  ├── _rle_encode() (numpy 加速)
  └── bytearray 构建输出
  │
  ▼
stdout.buffer.write() → 终端渲染
```

### 16.2 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 编码方式 | 流式（逐帧编码+释放） | 避免内存累积退化 |
| 调色板大小 | 32 色 | 编码速度 ≈ 帧延迟目标 |
| 像素表示 | numpy uint8 数组 | 比 PIL PixelAccess 快 ~30x |
| 颜色计算 | numpy broadcasting | 一次算所有颜色 |
| RLE 阈值 | >= 4 | 3 字节标记 vs 3 字节原始数据，>=4 才有收益 |
| 帧延迟 | 自适应扣除 | 避免编码+延迟叠加导致帧率减半 |
| 抖动 | Bayer 有序抖动（可选） | 减少色带，编码 +80% |

### 16.3 性能总结

| 指标 | V0 原始版 | 最终版 | 提升 |
|------|----------|--------|------|
| 单帧编码 | 475ms | 36ms | **13.2x** |
| GIF 33 帧 | 48.4s | 1.2s | **40.6x** |
| 输出体积/帧 | 860KB | 70KB | **12.3x** |
| 内存行为 | 帧 3 退化 | 全程稳定 | 修复 |
