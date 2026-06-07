# pysixel 性能 Benchmark 报告

> 测试日期：2026-06-07
> 测试环境：Windows 11 / Python 3.13 (Anaconda) / Pillow 11.1.0 / numpy 2.x
> 测试图片：`mutou.gif` (500x500, 33 帧, 30ms/帧)
> 项目地址：https://github.com/hyfaust/pysixel

---

## 1. 概述

本报告记录 pysixel 从最初 PIL 逐像素实现到最终 numpy 向量化实现的完整优化过程。核心目标：在终端中以 Sixel 协议实时播放 GIF 动画（帧延迟 30ms，编码耗时 <= 36ms）。

---

## 2. 原始版 vs 优化版（单帧，500x500 GIF）

| 阶段 | 编码时间 | 输出体积 | 加速比 |
|------|---------|---------|--------|
| V0 原始版（PIL 逐像素，256 色） | 475ms | 880KB | 1.0x |
| V1 numpy 向量化 | 121ms | 86KB | 3.9x |
| V2 流式 + 批量 | 102ms | 71KB | 4.7x |
| V3 列预计算（纯 Python） | 46ms | 470KB | 10.3x |
| 最终版（32 色 + RLE + numpy） | 36ms | 71KB | **13.2x** |

从 475ms 到 36ms，总计提速 **13.2 倍**。输出体积从 880KB 降至 71KB（压缩 12.3 倍）。

---

## 3. GIF 33 帧流式播放

| 版本 | 总耗时 | 每帧均值 | vs 目标（36ms） |
|------|--------|---------|----------------|
| V0 原始版 | 48,439ms | 1,468ms | 40.8x |
| 最终版 | 1,192ms | 36ms | **1.0x** |

原始版播放一圈（33 帧）需要 48 秒，最终版仅需 1.2 秒。编码耗时（36ms）与 GIF 帧延迟（30ms）基本持平，实现了**准实时 GIF 动画播放**。

---

## 4. 关键瓶颈分析

### 4.1 PIL 像素访问：绝对瓶颈

V0 原始版的性能剖析：

| 阶段 | 耗时 | 占比 |
|------|------|------|
| resize | 2.67ms | 0.09% |
| quantize | 14.58ms | 0.47% |
| 收集 used_colors | 12.66ms | 0.41% |
| 构建 row_color_map | 13.05ms | 0.42% |
| **Sixel 编码** | **3,025ms** | **98.61%** |

**根因**：256 色 x 500 像素 x 42 bands = 每帧约 **3200 万次** `pixels[x, y]` Python 方法调用。PIL 的 `PixelAccess.__getitem__` 每次调用约 100ns：

```
32,000,000 次 x 100ns/次 = 3.2s（占编码时间的 98.6%）
```

### 4.2 内存累积退化

预编码全部 33 帧时，帧间性能出现严重退化：

| 帧序号 | 预编码全部（ms） | 流式编码（ms） |
|--------|----------------|--------------|
| 帧 0 | 323 | 342 |
| 帧 3 | 1,323 | 329 |
| 帧 32 | — | 309 |

33 帧的 numpy 数组 + 编码字节串全部堆积在内存中（~10MB），触发 GC 压力和内存碎片化。帧 3 开始突然变慢 4 倍。

### 4.3 纯 Python RLE 的陷阱

尝试用纯 Python 循环实现 RLE 压缩：

```python
# 纯 Python RLE —— 反而更慢
for k in range(run):
    out.append(int(vals[start + k]))  # while 循环开销 > 输出节省
```

纯 Python 的 `while` 循环开销使得短 run 的 RLE 编码比直接输出原始数据更慢。最终采用 numpy `np.diff()` + `np.nonzero()` 加速边界检测。

---

## 5. 优化技术及实测效果

### 5.1 numpy 向量化：13.2x

**问题**：3200 万次 PIL `pixels[x,y]` 调用 x 100ns/次 = 3.2s

**方案**：用 `np.array(img)` 一次性将 PIL Image 转为 numpy 数组，再通过批量比较替代逐像素循环。

```python
# 旧：3200 万次 Python 方法调用
pixels = img.load()
for x in range(w):
    for bit in range(6):
        if pixels[x, y] == color_idx:  # 每次 ~100ns
            bits |= 1 << bit

# 新：numpy 批量运算
pixels_np = np.array(img)  # shape (h, w), dtype uint8
mask = (band == color_idx)  # 向量化比较，~5us/3000 元素
bits = (mask * weights).sum(axis=0)  # 向量化累加，~10us/500 元素
```

**效果**：单帧编码 475ms -> 121ms（3.9x），配合减色后达到 13.2x。

### 5.2 流式编码：3x 累积

**问题**：预编码全部帧导致内存累积，帧 3+ 退化到 1300ms+

**方案**：逐帧编码 + 输出 + 释放，保持内存平稳。

```python
# 旧：预编码全部帧（内存累积）
for frame in frames:
    encoded.append(encode_sixel(frame))  # 33 帧数据全部驻留内存

# 新：流式编码（每帧释放）
for frame in frames:
    data = encode_sixel(frame)
    output(data)
    del data  # 立即释放
```

**效果**：消除帧间退化，所有帧稳定在 ~310ms（256 色）/ ~36ms（32 色）。

### 5.3 颜色缩减 256->32：2.8x

**问题**：256 色时每 band 平均 ~134 种颜色，迭代次数多。

**方案**：将默认调色板从 256 色减少到 32 色。

| 调色板 | 每 band 平均颜色数 | 编码耗时 |
|--------|-------------------|---------|
| 256 色 | ~134 | 102ms |
| 128 色 | ~100 | 75ms |
| 64 色 | ~60 | 51ms |
| 32 色 | ~30 | 36ms |

**效果**：256->32 色提速 2.8 倍。编码时间与颜色数近似成正比。

**权衡**：32 色会产生可见色带（color banding），通过 `--dither` 选项（Bayer 有序抖动）可缓解。

### 5.4 批量颜色计算：1.2x

将逐颜色循环改为 numpy broadcasting 一次计算所有颜色：

```python
# 旧：逐颜色计算（134 次 numpy 操作）
for color_idx in band_colors:
    mask = (band == color_idx)
    bits = (mask * weights).sum(axis=0)

# 新：批量计算（1 次 numpy 操作）
masks = (band[np.newaxis, :, :] == band_colors[:, np.newaxis, np.newaxis])
bits_all = (masks.view(np.uint8) * _SIXEL_WEIGHTS).sum(axis=1)
```

**效果**：128 色场景 102ms -> 75ms（1.36x），减少 Python 循环和 numpy 函数调用开销。

### 5.5 RLE 压缩：输出 -92%

Sixel 协议支持 RLE 压缩：`!COUNT CHAR`（COUNT 个连续 CHAR）。

```python
# numpy 加速的 RLE 边界检测
diff = np.diff(vals)
changes = np.nonzero(diff)[0] + 1
boundaries = np.concatenate([[0], changes, [len(vals)]])

for i in range(len(boundaries) - 1):
    run = boundaries[i + 1] - boundaries[i]
    if run >= 4:
        out.extend(b"!")
        out.extend(_RUN_STR[run])
        out.append(v)
    else:
        out.extend(vals[start:start + run].tobytes())
```

| 指标 | 无 RLE | 有 RLE | 压缩比 |
|------|--------|--------|--------|
| 每帧输出 | 880KB | 71KB | **12.3x** |

RLE 大幅减少终端渲染数据量，对实际播放流畅度有显著帮助。

### 5.6 字符串缓存：1.1x

预构建所有可能用到的字节串，避免循环中反复 `encode()`：

```python
_COLOR_STR = [f"#{i}".encode("ascii") for i in range(256)]
_RUN_STR = [str(i).encode("ascii") for i in range(MAX_PX_WIDTH + 1)]
```

循环中直接查表，消除重复的字符串构造和编码开销。

---

## 6. Filter Bank 实验（来自 chafa）

### 6.1 实验背景

分析 chafa 1.18.2 源码后，尝试将其 Filter Bank 优化移植到 Python 实现。

chafa 的 Filter Bank 原理：每 32（或 64）像素为一个 bank，用位域记录该 bank 中出现的颜色。编码时先检查 bank——如果某颜色不存在，直接跳过整个 bank。

```c
// chafa 的 Filter Bank (C 代码)
if (!filter_get(srow, pen, i / FILTER_BANK_WIDTH)) {
    n_reps += FILTER_BANK_WIDTH;  // 跳过 32 像素
    continue;
}
```

### 6.2 实验结果

```
v1 baseline:       34.7ms/帧
v2 + Filter Bank:  82.6ms/帧  ← 反而慢 2.4 倍！
```

### 6.3 根因分析

Filter Bank 是为 C 语言**逐像素循环**设计的优化——跳过 N 个像素可省掉 N 次函数调用开销。但 numpy 向量化已经一次性处理所有像素：

```python
# numpy 已经批量处理，无需逐像素跳过
masks = (band == colors[:, np.newaxis, np.newaxis])  # 一次算完
bits = (masks * weights).sum(axis=1)                  # 一次算完
```

Filter Bank 额外引入的开销：
- `np.zeros((n_colors, n_banks))` 数组分配
- 嵌套循环 `colors x banks` 中的 `np.any()` 调用
- 输出路径的额外分支判断

### 6.4 结论

numpy 向量化已经等价于 Filter Bank 在 C 代码中的效果。对于向量化实现，Filter Bank 是纯开销。

**核心教训**：C 级别的逐像素优化不适用于向量化 Python 实现。从 C 库移植优化时，必须理解底层执行模型的差异。

---

## 7. 输出体积对比

| 版本 | 每帧输出 | 压缩比 |
|------|---------|--------|
| V0 原始版（256 色，无 RLE） | 880KB | 1.0x |
| V1 numpy + RLE（256 色） | 86KB | 10.2x |
| 最终版（32 色 + RLE） | 71KB | **12.3x** |

输出体积直接影响终端渲染速度。880KB/帧的数据量会导致终端光标移动和字符渲染出现明显延迟；71KB/帧则可以流畅渲染。

---

## 8. 最终结论

| 指标 | 原始版 | 最终版 | 提升 |
|------|--------|--------|------|
| 单帧编码 | 475ms | 36ms | **13.2x** |
| GIF 33 帧总编码 | 48.4s | 1.2s | **40.6x** |
| 输出体积/帧 | 860KB | 70KB | **12.3x** |
| 编码 vs 帧延迟 | 1468ms >> 30ms | 36ms ≈ 30ms | 实时 |
| 内存稳定性 | 帧 3 开始退化 | 全程稳定 | 修复 |

最终版在 32 色调色板下实现了准实时 GIF 动画播放，编码耗时（36ms）与 GIF 帧延迟（30ms）基本持平。

---

## 附录：优化手段贡献分解

```
原始版 (475ms/帧)
  │
  ├─ numpy 向量化 ──────── 475ms -> 121ms  (3.9x)   消除 PIL 像素访问
  │
  ├─ 流式编码 ──────────── 解决内存退化     (稳定)   逐帧编码+释放
  │
  ├─ 批量向量化 ────────── 121ms -> 102ms  (1.2x)   broadcasting 合并颜色循环
  │
  ├─ RLE 压缩 ──────────── 输出 880K->86K  (10x)    游程编码减少终端渲染量
  │
  ├─ 减色 256->32 ──────── 102ms -> 36ms   (2.8x)   减少每 band 颜色迭代
  │
  ├─ 字符串缓存 ────────── 微调            (~1.1x)  消除重复 encode()
  │
  ├─ 光栅属性 ──────────── 正确宽高比       (质量)   "1;1;W;H 消除 char_aspect hack
  │
  ├─ FS 哈希缓存 ───────── FS 查找 O(1)    (加速)   15-bit cachetable 替代 O(n_colors)
  │
  ├─ 自动禁用 FS ───────── 低色图跳过 FS    (加速)   15-bit 哈希检测独特色数
  │
  ├─ GIF 调色板缓存 ────── 跳过重复量化     (加速)   后续帧复用第一帧调色板
  │
  └─ 采样量化 ──────────── 大图加速         (加速)   >1M 像素时下采样做 MEDIANCUT
```
