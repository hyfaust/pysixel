# libsixel vs chafa 源码分析

> 分析日期：2026-06-07
> 分析对象：libsixel 1.8.7-r2 / chafa 1.18.2
> 关联项目：pysixel — https://github.com/hyfaust/pysixel

---

## 1. 总览

本报告对两个主流 C 语言 Sixel 库进行深度源码分析，提炼可应用于 Python 实现的优化经验。

| 维度 | libsixel 1.8.7-r2 | chafa 1.18.2 |
|------|-------------------|--------------|
| 许可证 | MIT | LGPL v3+ |
| 作者 | Hayaki Saito | Hans Petter Jansson |
| 语言 | 纯 C，无外部运行时依赖 | C，依赖 GLib |
| 定位 | Sixel 参考实现 | 多协议终端图形框架 |
| 输出协议 | Sixel | Sixel / Kitty / iTerm2 / 字符画 |
| 源码 | https://github.com/saitoha/libsixel | https://github.com/hpjansson/chafa/ |

---

## 2. libsixel 1.8.7-r2

### 2.1 定位与特点

libsixel 是 Sixel 协议的**参考实现**，专注于 Sixel 编解码，零外部依赖。MIT 许可证使其可自由集成到各类项目中。

### 2.2 源码结构

```
sixel-1.8.7-r2/
├── include/
│   └── sixel.h              # 唯一公共 API 头文件
├── src/
│   ├── tosixel.c            # Sixel 编码器核心
│   ├── fromsixel.c          # Sixel 解码器
│   ├── encoder.c            # 高级编码器封装
│   ├── decoder.c            # 高级解码器封装
│   ├── quant.c              # 颜色量化 (Median Cut)
│   ├── dither.c             # 抖动处理 (8 种)
│   ├── loader.c             # 图像加载 (PNG/JPEG/GIF/BMP/PNM)
│   ├── fromgif.c            # 内置 GIF 解码 (LZW)
│   ├── frompnm.c            # 内置 PNM 解码
│   ├── stb_image.h          # stb_image 单头文件库
│   ├── tty.c                # 终端 Sixel 支持检测
│   ├── pixelformat.c        # 22 种像素格式转换
│   ├── scale.c              # 10 种重采样滤波器
│   ├── output.c             # 输出上下文、缓冲区管理
│   ├── frame.c              # 帧对象
│   ├── allocator.c          # 自定义内存分配器 (引用计数)
│   └── ...
├── converters/
│   ├── img2sixel.c          # 图片→Sixel 命令行工具
│   └── sixel2png.c          # Sixel→PNG 命令行工具
├── python/                  # Python 绑定 (ctypes)
└── tests/                   # 安全回归测试 (CVE PoC)
```

### 2.3 公共 API

面向对象的 C 风格 API，通过不透明指针暴露：

```
sixel_allocator_t   → 自定义分配器 (引用计数)
sixel_output_t      → 输出上下文 (封装写回调函数)
sixel_dither_t      → 抖动/量化上下文 (管理调色板)
sixel_frame_t       → 图像帧对象
sixel_encoder_t     → 高级编码器 (文件→Sixel)
sixel_decoder_t     → 高级解码器 (Sixel→文件)
```

典型编码流程：

```c
sixel_dither_new(&dither, 256, NULL);
sixel_dither_initialize(dither, pixels, width, height, PIXFMT_RGB888,
                        SIXEL_LARGE_NORM, SIXEL_REP_CENTER_BOX, 256);
sixel_dither_set_diffusion_type(dither, SIXEL_DIFFUSE_FS);
sixel_output_new(&output, 0, NULL);
sixel_encode(pixels, width, height, 1, dither, output);
```

### 2.4 Sixel 编码算法（tosixel.c）

`sixel_encode_body()` 约 250 行，核心流程：

**Step 1 — 输出 DCS 头部**：`ESC P 0;0;0q`

**Step 2 — 输出调色板**：`#N;2;R%;G%;B%`（RGB 模式，值 0-100）

**Step 3 — 逐条带编码**（每 6 行像素为一个条带）：

```c
// 构建 map[color][x] 位掩码
for (y = 0; y < height; y++) {
    map[pixel * width + x] |= (1 << i);  // i = 0-5
    if (++i < 6) continue;  // 每 6 行编码一次

    // 对每种颜色提取连续非零区间
    // 按起始位置排序，输出各颜色的 Sixel 字符
    output = '$' (回车) + '#N' (切色) + sixel_chars
    output = '-' (换行到下一条带)
}
```

**Step 4 — RLE 压缩**：连续 >= 3 个相同字符 → `!COUNT CHAR`，VT240 兼容模式限制 N <= 255。

**Step 5 — DCS 尾部**：`ESC \`

### 2.5 颜色量化 — Median Cut

基于 Paul Heckbert 论文 (SIGGRAPH '82)，从 netpbm 库移植：

```
computeHistogram()
  → hash = (R>>3) | ((G>>3)<<5) | ((B>>3)<<10)  // 24bit→15bit (32768 桶)
  → 按 qualityMode 控制采样: LOW=18K / HIGH=1.1M / FULL=4M 像素

mediancut()
  → 初始 box 包含所有颜色
  → 循环: 找最大 box → splitBox()
  → 直到 box 数 = 目标色数

splitBox()
  → findBoxBoundaries() // RGB 空间 min/max
  → 选择最大维度 (直接比较 或 加权亮度)
  → qsort 排序 → 找中位点 → 一分为二
```

代表色选择 3 种策略：

| 策略 | 说明 |
|------|------|
| `REP_CENTER_BOX` | box 各维中点 |
| `REP_AVERAGE_COLORS` | box 内颜色平均 |
| `REP_AVERAGE_PIXELS` | 按像素频次加权平均（Heckbert 推荐） |

### 2.6 抖动实现（8 种）

| 方法 | 算法 | 特点 |
|------|------|------|
| NONE | 无抖动 | 最快，色带明显 |
| **Floyd-Steinberg** | 误差扩散 7/16, 3/16, 5/16, 1/16 | 经典，平衡质量与速度 |
| Atkinson | 仅扩散 75% 误差 | 更锐利的对比度 |
| Jarvis-Judice-Ninke | 5x3 扩散核 | 更平滑，更慢 |
| Stucki | 5x3 扩散核变体 | 类似 JJN |
| Burkes | 5x3 扩散核变体 | 类似 JJN |
| **A-Dither** | 算术位置掩码 | 确定性，无依赖 |
| **X-Dither** | XOR 位置掩码 | 确定性，无依赖 |

算术抖动公式：

```c
mask_a(x, y, c) = ((((x + c*67) + y*236) * 119) & 255) / 128.0 - 1.0
mask_x(x, y, c) = ((((x + c*29) ^ y*149) * 1234) & 511) / 256.0 - 1.0
```

### 2.7 15bpp 高色模式

libsixel 独有的高色模式：每 band 重新定义调色板，突破 256 色限制。通过动态调色板重定义实现 15bpp（32768 色）显示质量。

### 2.8 图像加载

通过魔术字节自动检测格式：

| 格式 | 解码器 | 条件 |
|------|--------|------|
| PNG | libpng 或 stb_image | `--with-png` |
| JPEG | libjpeg | `--with-jpeg` |
| GIF | 内置 fromgif.c (LZW) | 始终可用 |
| PNM | 内置 frompnm.c | 始终可用 |
| BMP/TGA/TIFF/PSD/HDR | stb_image | 始终可用 |
| Sixel | 内置 fromsixel.c | 始终可用 |

### 2.9 安全记录

1.8.7 版本修复了大量 CVE，包括高色编码器整数溢出、Sixel 解析器 repeat/count 整数溢出、多个 use-after-free 等。

---

## 3. chafa 1.18.2

### 3.1 定位与特点

chafa 是一个**多协议终端图形框架**，支持 Sixel、Kitty、iTerm2 和字符画四种输出模式。使用 GLib 作为基础依赖，提供更现代的量化算法和 SIMD 优化。

### 3.2 源码结构

```
chafa-1.18.2/
├── chafa/
│   ├── chafa.h              # 总头文件
│   ├── chafa-common.h       # 公共枚举
│   ├── chafa-canvas.c/h     # 核心绘图表面
│   ├── chafa-canvas-config.c/h  # Canvas 配置
│   ├── chafa-symbol-map.c/h     # 符号映射系统
│   ├── chafa-term-info.c/h      # 终端能力描述
│   ├── chafa-frame.c/h          # 帧对象
│   ├── chafa-image.c/h          # 图像对象
│   ├── chafa-features.c/h       # SIMD 特性检测
│   └── internal/
│       ├── chafa-sixel-canvas.c/h   # Sixel 编码器
│       ├── chafa-kitty-canvas.c/h   # Kitty 协议编码器
│       ├── chafa-iterm2-canvas.c/h  # iTerm2 协议编码器
│       ├── chafa-palette.c/h        # 颜色量化 (PNN)
│       ├── chafa-color.c/h          # 颜色空间转换 (RGB↔DIN99d)
│       ├── chafa-dither.c/h         # 抖动实现
│       ├── chafa-pixops.c/h         # 像素操作 (符号模式核心)
│       ├── chafa-pca.c/h            # PCA (主成分分析)
│       ├── chafa-avx2.c             # AVX2 优化路径
│       ├── chafa-sse41.c            # SSE4.1 优化路径
│       ├── chafa-mmx.c              # MMX 优化路径
│       ├── chafa-popcnt.c           # popcount 优化
│       └── smolscale/               # 内嵌图像缩放库
├── tools/
│   └── chafa/               # CLI 工具
├── libnsgif/                # 内嵌 GIF 解码库
├── lodepng/                 # 内嵌 PNG 解码库
└── tests/
```

### 3.3 四种输出模式

| 模式 | 说明 |
|------|------|
| `SYMBOLS` | 字符画（Unicode 符号匹配，chafa 最独特的功能） |
| `SIXELS` | Sixel 协议 |
| `KITTY` | Kitty 终端协议 |
| `ITERM2` | iTerm2 协议 |

字符画模式将每个终端单元格视为一个"像素"，使用 Unicode 字符（Block 元素、ASCII、假名、Latin 等）近似图像，每个字符有前景色和背景色。

### 3.4 Sixel 编码器（chafa-sixel-canvas.c）

chafa 的 Sixel 编码器比 libsixel 更紧凑（523 行 vs 250 行），使用了更巧妙的位操作：

**核心数据结构**：

```c
typedef struct {
    guint64 d;  // 6 个字节各存储一个像素的调色板索引
} SixelData;
```

**编码流程**：

1. `fetch_sixel_row()` — 将 6 行像素打包到 `SixelData` 数组，字节顺序重排为 `351240`（优化后续位操作）

2. `sixel_data_to_schar()` — 向量化 Sixel 字符计算：`~(d ^ expanded_pen)` 匹配的字节变为 0xFF，通过移位和 AND 压缩为 6-bit 位图

3. `build_sixel_row_ansi()` — 使用 **Filter Bank** 优化：每 64 像素为一个 bank，用位域记录出现的颜色，跳过不存在颜色的 bank

4. RLE 压缩：>= 4 个重复 → `!COUNT CHAR`，限制 COUNT <= 255

### 3.5 颜色量化 — PNN 算法

chafa 使用 **PNN (Pairwise Nearest Neighbor)** 算法，灵感来自 nQuant，参考论文 DOI:10.1117/1.1412423。

算法流程：

1. **采样**：按质量等级采样像素（-w 1=16K ~ -w 9=67M）
2. **分桶**：按 RGB 高位 bit 分桶（3-5 bit/通道 → 512~32768 个桶）
3. **PNN 合并**：对每个桶找到最近邻桶，距离 = 加权颜色差异 + 计数权重，使用优先队列（堆）合并最近的桶对，重复直到桶数 = 目标色数
4. **代表色**：取每个桶的加权平均色

PNN vs Median Cut：

| 方面 | Median Cut (libsixel) | PNN (chafa) |
|------|----------------------|-------------|
| 算法策略 | 贪心分裂 | 全局最优合并 |
| 颜色质量 | 良好 | 通常更好 |
| 高色数速度 | 需反复排序 | 桶合并更快 |
| 实现复杂度 | 较低 | 较高 |
| 内存占用 | 较少 | 较多（桶 + 堆） |

### 3.6 颜色空间 — DIN99d

chafa 使用 **DIN99d** 感知均匀色彩空间进行颜色比较，而非简单的 RGB 欧氏距离：

```c
chafa_color_rgb_to_din99d(&rgb_color, &din99d_color);
```

DIN99d 更接近人眼对颜色差异的感知，使颜色匹配更准确。

### 3.7 符号映射系统

chafa 最独特的特性。每个 Unicode 字符有一个预计算的"形状"（8x8 或 16x16 位图）：

```
对每个终端单元格:
1. 将图像区域缩放到单元格大小
2. 计算前景色和背景色（PCA 主成分分析确定最佳分割）
3. 遍历符号映射表，找到与图像形状最匹配的字符
4. 输出前景色 + 背景色 + 字符
```

符号集包括：ASCII 可打印字符、Unicode Block 元素（▀▄█▌▐等）、日文假名、Latin 扩展字符等。

### 3.8 SIMD 优化

chafa 在多个层面使用 SIMD 指令，运行时检测 CPU 特性选择最优路径：

| 文件 | 指令集 | 用途 |
|------|--------|------|
| `chafa-avx2.c` | AVX2 (256-bit) | 颜色差异计算、批量像素处理 |
| `chafa-sse41.c` | SSE4.1 (128-bit) | 颜色差异计算 |
| `chafa-mmx.c` | MMX (64-bit) | 颜色差异计算（旧 CPU） |
| `chafa-popcnt.c` | POPCNT | 位计数加速 |

### 3.9 Filter Bank 优化

chafa 独有的 Sixel 编码优化：

```c
// 每 64 像素为一个 bank，用位域记录该 bank 中出现的颜色
#define FILTER_BANK_WIDTH 64

filter_set(srow, pen, bank);  // 标记某颜色在某 bank 中存在

// 编码时先检查 bank
if (!filter_get(srow, pen, i / FILTER_BANK_WIDTH)) {
    n_reps += FILTER_BANK_WIDTH;  // 跳过 64 像素
    continue;
}
```

大幅减少 C 逐像素循环中的无效颜色遍历。但在 Python/numpy 向量化实现中不适用（详见第 5 节）。

### 3.10 依赖

- **GLib** — 核心依赖（数据类型、内存管理、主循环）
- **内嵌库**：libnsgif (GIF)、lodepng (PNG)、smolscale (缩放)
- **可选**：libjpeg、libwebp、libtiff

---

## 4. 核心架构对比

| 方面 | libsixel | chafa |
|------|----------|-------|
| 设计哲学 | Sixel 参考实现 | 多协议框架 |
| API 风格 | 底层，暴露 Sixel 细节 | 高层，隐藏协议差异 |
| 依赖策略 | 零依赖（自包含） | 依赖 GLib 生态 |
| 扩展性 | 仅 Sixel | 插件式协议后端 |
| 量化算法 | Median Cut（经典） | PNN（更现代） |
| 颜色空间 | RGB 欧氏距离 | DIN99d 感知均匀 |
| 抖动方法 | 8 种 | 3 种 |
| Sixel 编码 | 逐颜色遍历 + 链表排序 | Filter Bank + 位操作向量化 |
| RLE | `!COUNT CHAR` (<=255) | `!COUNT CHAR` (<=255) |
| 高色模式 | 15bpp 动态调色板 | 不支持 |
| SIMD | 无 | AVX2 / SSE4.1 / MMX |
| Python 绑定 | ctypes 内置 | GObject Introspection |
| 库体积 | ~200KB .so | ~500KB .so |
| 运行时依赖 | 无 | GLib (~1MB) |

---

## 5. 应用于 pysixel 的经验

### 5.1 已采纳的技术

| 技术 | 来源 | 实施效果 |
|------|------|---------|
| RLE 压缩 | libsixel | 已应用 — 短 run 用 `.tobytes()` 替代逐字节 append，输出减少 92% |
| Bayer 有序抖动 | libsixel A-Dither | 已应用 — `--dither` 选项减少 32 色色带伪影 |
| MEDIANCUT 量化 | libsixel (via PIL) | 已应用 — PIL 内置的 MEDIANCUT 足够满足需求 |

### 5.2 已尝试并回退的技术

| 技术 | 来源 | 回退原因 |
|------|------|---------|
| Filter Bank 跳跃 | chafa | 慢 2.4 倍 — numpy 向量化已等效，额外 bank 计算反增开销 |

### 5.3 已记录但未实施的技术

| 技术 | 来源 | 未实施原因 |
|------|------|-----------|
| PNN 量化 | chafa | PIL MEDIANCUT 已足够，PNN 需要 C 扩展 |
| DIN99d 色彩空间 | chafa | 需要完整的色彩空间转换库 |
| 肤色校正 | libsixel | 人像图片专用，优先级低 |
| 8bit Sixel 模式 | libsixel | 终端兼容性考虑 |

### 5.4 核心教训：C 优化不等于 Python 优化

Filter Bank 的实验结果揭示了一个关键原则：

| 方面 | C 逐像素循环 | numpy 向量化 |
|------|-------------|-------------|
| 基本操作 | 每像素一次函数调用 | 整个数组一次 C 调用 |
| Filter Bank 收益 | 跳过 N 次调用 = 节省 N x 开销 | 无调用可跳过 |
| Filter Bank 开销 | 位域检查（极低） | 数组分配 + `np.any()` + 分支 |
| 净效果 | **正收益** | **负收益** |

**原则**：从 C 库移植优化到 Python/numpy 时，必须理解底层执行模型的差异。C 级别的逐像素优化（如 Filter Bank、per-pixel branching）通常不适用于向量化实现，因为 numpy 已经在 C 层批量处理所有元素。

### 5.5 真正有效的 Python 优化

本项目中实际有效的优化（按收益排序）：

| 优化 | 收益 | 原理 |
|------|------|------|
| numpy 向量化 | 13.2x | 消除 PIL 逐像素 Python 调用 |
| 流式编码 | 3x (累积) | 避免内存累积导致 GC 退化 |
| 减色 256->32 | 2.8x | 减少每 band 颜色迭代次数 |
| 批量颜色计算 | 1.2x | broadcasting 合并颜色循环 |
| RLE 压缩 | 输出 -92% | 减少终端渲染量 |
| 字符串缓存 | 1.1x | 避免循环中反复 encode() |

---

## 6. 适用场景推荐

| 场景 | 推荐 | 理由 |
|------|------|------|
| 嵌入式 / 最小依赖 | libsixel | 零依赖，MIT 许可 |
| 纯 Sixel 编解码 | libsixel | 专注实现，API 更底层灵活 |
| 高色 / 动态调色板 | libsixel | 15bpp 高色模式独有 |
| 通用终端图形工具 | chafa | 多协议支持，CLI 工具完善 |
| 字符画输出 | chafa | 独有的符号匹配系统 |
| Kitty / iTerm2 终端 | chafa | 原生协议支持 |
| 最佳颜色质量 | chafa | PNN + DIN99d 更优 |
| 最大编码速度 | chafa | SIMD + Filter Bank |
| Python 脚本集成 | libsixel | 内置 ctypes 绑定 |
| 安全敏感环境 | chafa | 更少的历史 CVE |
