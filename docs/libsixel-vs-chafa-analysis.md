# libsixel vs chafa 深度分析报告

> 分析日期：2026-06-07  
> 分析对象：libsixel 1.8.7-r2 / chafa 1.18.2

---

## 1. 总览

| 维度 | libsixel 1.8.7-r2 | chafa 1.18.2 |
|------|-------------------|--------------|
| **定位** | 专用 Sixel 编解码库 | 多协议终端图形框架 |
| **许可证** | MIT | LGPL v3+ |
| **作者** | Hayaki Saito | Hans Petter Jansson |
| **语言** | 纯 C，无外部运行时依赖 | C，依赖 GLib |
| **构建** | GNU Autotools | GNU Autotools |
| **输出协议** | Sixel only | Sixel / Kitty / iTerm2 / 字符画 |
| **量化算法** | Median Cut | PNN (Pairwise Nearest Neighbor) |
| **抖动方法** | 8 种 | 3 种 (None / FS / Ordered) |
| **SIMD 优化** | 无 | AVX2 / SSE4.1 / MMX |
| **Python 绑定** | ctypes 内置 | GObject Introspection |
| **CLI 工具** | img2sixel / sixel2png | chafa |

---

## 2. libsixel 深度分析

### 2.1 源码结构

```
sixel-1.8.7-r2/
├── include/
│   └── sixel.h              # 唯一公共 API 头文件 (1169行)
├── src/                     # 核心库 (24 .c + 17 .h)
│   ├── tosixel.c            # ★ Sixel 编码器核心
│   ├── fromsixel.c          # Sixel 解码器
│   ├── encoder.c            # 高级编码器封装
│   ├── decoder.c            # 高级解码器封装
│   ├── quant.c              # ★ 颜色量化 (Median Cut)
│   ├── dither.c             # ★ 抖动处理 (8种)
│   ├── loader.c             # 图像加载 (PNG/JPEG/GIF/BMP/PNM)
│   ├── frame.c              # 帧对象
│   ├── output.c             # 输出上下文、缓冲区管理
│   ├── pixelformat.c        # 22种像素格式转换
│   ├── scale.c              # 10种重采样滤波器
│   ├── fromgif.c            # 内置 GIF 解码
│   ├── frompnm.c            # 内置 PNM 解码
│   ├── stb_image.h          # stb_image 单头文件库
│   ├── tty.c                # 终端 Sixel 支持检测
│   ├── allocator.c          # 自定义内存分配器 (引用计数)
│   └── ...
├── converters/
│   ├── img2sixel.c          # 图片→Sixel 命令行工具
│   └── sixel2png.c          # Sixel→PNG 命令行工具
├── python/                  # Python 绑定 (ctypes)
└── tests/                   # 安全回归测试 (CVE PoC)
```

### 2.2 公共 API 设计

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

### 2.3 Sixel 编码算法 (`tosixel.c`)

`sixel_encode_body()` 约 250 行，核心流程：

**Step 1: 输出 DCS 头部**
```
ESC P 0;0;0 q "1;1;WIDTH;HEIGHT
```

**Step 2: 输出调色板**
```
#0;2;R%;G%;B%    (RGB 模式，值 0-100)
#1;2;R%;G%;B%
...
```

**Step 3: 逐条带编码**（每 6 行像素为一个条带）
```c
// 构建 map[color][x] 位掩码
for (y = 0; y < height; y++) {
    map[pixel * width + x] |= (1 << i);  // i = 0-5
    if (++i < 6) continue;  // 每 6 行编码一次
    
    // 对每种颜色提取连续非零区间
    for (c = 0; c < ncolors; c++) {
        // 创建 sixel_node 链表
    }
    // 按起始位置排序，输出各颜色的 Sixel 字符
    output = '$' (回车) + '#N' (切色) + sixel_chars
    output = '-' (换行到下一条带)
}
```

**Step 4: RLE 压缩**
```
连续 ≥ 3 个相同字符 → !COUNT CHAR
例: ???????? → !8?
VT240 兼容模式限制 N ≤ 255
```

**Step 5: DCS 尾部**
```
ESC \
```

### 2.4 颜色量化 (`quant.c`) — Median Cut

基于 Paul Heckbert 论文 (SIGGRAPH '82)，从 netpbm 库移植：

```
computeHistogram()
  → hash = (R>>3) | ((G>>3)<<5) | ((B>>3)<<10)  // 24bit→15bit (32768桶)
  → 按 qualityMode 控制采样: LOW=18K / HIGH=1.1M / FULL=4M 像素

mediancut()
  → 初始 box 包含所有颜色
  → 循环: 找最大 box → splitBox()
  → 直到 box 数 = 请求色数

splitBox()
  → findBoxBoundaries() // RGB 空间 min/max
  → 选择最大维度 (直接比较 或 加权亮度)
  → qsort 排序 → 找中位点 → 一分为二
```

代表色选择 3 种策略：
- `REP_CENTER_BOX`: box 各维中点
- `REP_AVERAGE_COLORS`: box 内颜色平均
- `REP_AVERAGE_PIXELS`: 按像素频次加权平均 (Heckbert 推荐)

### 2.5 抖动实现 (8 种)

| 方法 | 算法 | 特点 |
|------|------|------|
| NONE | 无抖动 | 最快，色带明显 |
| **Floyd-Steinberg** | 误差扩散 7/16, 3/16, 5/16, 1/16 | 经典，平衡质量与速度 |
| Atkinson | 仅扩散 75% 误差 | 更锐利的对比度 |
| Jarvis-Judice-Ninke | 5×3 扩散核 | 更平滑，更慢 |
| Stucki | 5×3 扩散核变体 | 类似 JJN |
| Burkes | 5×3 扩散核变体 | 类似 JJN |
| **A-Dither** | 算术位置掩码 | 确定性，无依赖 |
| **X-Dither** | XOR 位置掩码 | 确定性，无依赖 |

算术抖动公式：
```c
mask_a(x, y, c) = ((((x + c*67) + y*236) * 119) & 255) / 128.0 - 1.0
mask_x(x, y, c) = ((((x + c*29) ^ y*149) * 1234) & 511) / 256.0 - 1.0
```

### 2.6 编码策略选项

| 选项 | 值 | 说明 |
|------|-----|------|
| 质量模式 | LOW / HIGH / FULL / HIGHCOLOR | 控制采样密度和色深 |
| 编码策略 | FAST / SIZE | 速度优先 或 体积优先 |
| 调色板类型 | RGB / HLS | 颜色空间 |
| 8bit/7bit | 7bit=ESC P / 8bit=0x90 | C1 控制字符 |
| GNU Screen 穿透 | `-P` 选项 | 适配 screen/tmux |

### 2.7 图像加载

通过魔术字节自动检测格式：

| 格式 | 解码器 | 条件 |
|------|--------|------|
| PNG | libpng 或 stb_image | `--with-png` |
| JPEG | libjpeg | `--with-jpeg` |
| GIF | 内置 fromgif.c (LZW) | 始终可用 |
| PNM | 内置 frompnm.c | 始终可用 |
| BMP/TGA/TIFF/PSD/HDR | stb_image | 始终可用 |
| Sixel | 内置 fromsixel.c | 始终可用 |
| URL | libcurl | `--with-libcurl` |

### 2.8 安全记录

1.8.7 版本修复了大量 CVE：
- 高色编码器整数溢出
- Sixel 解析器 repeat/count 整数溢出
- 多个 use-after-free (GIF loader, gdkpixbuf, encoder)
- 整数溢出导致堆溢出 (PNG writer)

---

## 3. chafa 深度分析

### 3.1 源码结构

```
chafa-1.18.2/
├── chafa/                   # 核心库
│   ├── chafa.h              # 总头文件
│   ├── chafa-common.h       # 公共枚举 (像素格式、输出模式、抖动等)
│   ├── chafa-canvas.c/h     # ★ Canvas — 核心绘图表面
│   ├── chafa-canvas-config.c/h  # Canvas 配置
│   ├── chafa-symbol-map.c/h     # ★ 符号映射系统
│   ├── chafa-term-info.c/h      # 终端能力描述
│   ├── chafa-term-db.c/h        # 终端数据库
│   ├── chafa-frame.c/h          # 帧对象
│   ├── chafa-image.c/h          # 图像对象
│   ├── chafa-placement.c/h      # 放置对象
│   ├── chafa-features.c/h       # SIMD 特性检测
│   ├── chafa-util.c/h           # 工具函数
│   └── internal/                # 内部实现
│       ├── chafa-sixel-canvas.c/h   # ★ Sixel 编码器
│       ├── chafa-kitty-canvas.c/h   # Kitty 协议编码器
│       ├── chafa-iterm2-canvas.c/h  # iTerm2 协议编码器
│       ├── chafa-palette.c/h        # ★ 颜色量化 (PNN)
│       ├── chafa-color.c/h          # 颜色空间转换 (RGB↔DIN99d)
│       ├── chafa-color-table.c/h    # 颜色查找表
│       ├── chafa-color-hash.c/h     # 颜色哈希缓存
│       ├── chafa-dither.c/h         # 抖动实现
│       ├── chafa-indexed-image.c/h  # 索引图像 (量化+抖动)
│       ├── chafa-pixops.c/h         # 像素操作 (符号模式核心)
│       ├── chafa-canvas-printer.c/h # 输出序列化
│       ├── chafa-passthrough-encoder.c/h  # tmux/screen 穿透
│       ├── chafa-symbols.c          # 符号数据库加载
│       ├── chafa-symbols-ascii.h    # ASCII 符号集
│       ├── chafa-symbols-block.h    # Unicode Block 符号集
│       ├── chafa-symbols-kana.h     # 假名符号集
│       ├── chafa-symbols-latin.h    # Latin 符号集
│       ├── chafa-symbols-misc-narrow.h  # 窄符号集
│       ├── chafa-pca.c/h            # PCA (主成分分析)
│       ├── chafa-noise.c/h          # 噪声表
│       ├── chafa-work-cell.c/h      # 工作单元格
│       ├── chafa-batch.c/h          # 批处理
│       ├── chafa-avx2.c             # AVX2 优化路径
│       ├── chafa-sse41.c            # SSE4.1 优化路径
│       ├── chafa-mmx.c              # MMX 优化路径
│       ├── chafa-popcnt.c           # popcount 优化
│       ├── chafa-base64.c/h         # Base64 编码 (Kitty 协议)
│       └── smolscale/               # 内嵌图像缩放库
├── tools/
│   └── chafa/               # CLI 工具
├── examples/                # 示例代码
├── libnsgif/                # 内嵌 GIF 解码库
├── lodepng/                 # 内嵌 PNG 解码库
└── tests/                   # 测试
```

### 3.2 四种输出模式

```c
typedef enum {
    CHAFA_PIXEL_MODE_SYMBOLS,  // 字符画 (ANSI art)
    CHAFA_PIXEL_MODE_SIXELS,   // Sixel 协议
    CHAFA_PIXEL_MODE_KITTY,    # Kitty 终端协议
    CHAFA_PIXEL_MODE_ITERM2,   # iTerm2 协议
} ChafaPixelMode;
```

**字符画模式 (SYMBOLS)** 是 chafa 最独特的功能：
- 将每个终端单元格视为一个"像素"
- 使用 Unicode 字符（Block 元素、ASCII、假名、Latin 等）近似图像
- 每个字符有前景色和背景色
- 通过符号映射表选择最佳匹配字符

### 3.3 Canvas 架构

```
ChafaCanvasConfig  → 配置 (像素模式、符号映射、调色板类型、抖动等)
     ↓
ChafaCanvas        → 绘图表面
     ├── ChafaPlacement  → 图像放置位置
     ├── ChafaImage      → 源图像
     └── 输出后端:
          ├── 符号模式 → chafa-pixops.c (逐单元格匹配)
          ├── Sixel    → chafa-sixel-canvas.c
          ├── Kitty    → chafa-kitty-canvas.c
          └── iTerm2   → chafa-iterm2-canvas.c
```

### 3.4 Sixel 编码器 (`chafa-sixel-canvas.c`)

chafa 的 Sixel 编码器比 libsixel 更紧凑（523 行 vs 250 行），但使用了更巧妙的位操作：

**核心数据结构：**
```c
typedef struct {
    guint64 d;  // 6 个字节各存储一个像素的调色板索引
} SixelData;
```

**编码流程：**

1. **`fetch_sixel_row()`** — 将 6 行像素打包到 `SixelData` 数组
   - 每个 `SixelData.d` 的 6 个字节分别存储 6 行的调色板索引
   - 字节顺序重排为 `351240`（优化后续位操作）

2. **`sixel_data_to_schar()`** — 向量化 Sixel 字符计算
   - 用 SIMD 友好的位操作一次性比较 6 个字节
   - `~(d ^ expanded_pen)` → 匹配的字节变为 0xFF
   - 通过移位和 AND 操作压缩为 6-bit 位图
   - 最终加 `'?'` 得到 Sixel 字符

3. **`build_sixel_row_ansi()`** — 构建 Sixel 输出行
   - 使用 **Filter Bank** 优化：每 64 像素为一个 bank，用位域记录该 bank 中出现的颜色
   - 如果某个颜色在当前 bank 中不存在，跳过整个 bank（64 像素）
   - 这是 chafa 独有的优化，大幅减少颜色遍历

4. **RLE 压缩**：`format_schar_reps()`
   - ≥ 4 个重复 → `!COUNT CHAR`
   - 限制 COUNT ≤ 255（与 libsixel 相同的 VT240 兼容）

### 3.5 颜色量化 — PNN 算法 (`chafa-palette.c`)

chafa 使用 **PNN (Pairwise Nearest Neighbor)** 算法，而非 libsixel 的 Median Cut：

```
灵感来源: nQuant (Mark Tyler, Dmitry Groshev, Miller Cy Chan)
论文参考: DOI:10.1117/1.1412423, DOI:10.1117/1.1604396
```

**算法流程：**

1. **采样**：按质量等级采样像素（-w 1=16K ~ -w 9=67M）
2. **分桶**：按 RGB 高位 bit 分桶（3-5 bit/通道 → 512~32768 个桶）
3. **PNN 合并**：
   - 对每个桶找到最近邻桶（距离 = 加权颜色差异 + 计数权重）
   - 距离公式：`nerr = count1*count2/(count1+count2) * weighted_distance`
   - 使用优先队列（堆）合并最近的桶对
   - 重复直到桶数 = 目标色数
4. **代表色**：取每个桶的加权平均色

**质量等级参数：**

| 等级 | 采样数 | bits/通道 | 桶数 |
|------|--------|-----------|------|
| -w 1 | 16,384 | 3 | 512 |
| -w 3 | 65,536 | 4 | 4,096 |
| -w 5 | 262,144 | 4 | 4,096 |
| -w 7 | 1,048,576 | 5 | 32,768 |
| -w 9 | 67,108,864 | 5 | 32,768 |

**PNN vs Median Cut：**
- PNN 通常产生更好的颜色质量（全局最优 vs 贪心分裂）
- PNN 在高色数时更快（桶合并 vs 反复排序）
- Median Cut 实现更简单，内存占用更少

### 3.6 颜色空间 — DIN99d

chafa 使用 **DIN99d** 色彩空间进行颜色比较，而非简单的 RGB 欧氏距离：

```c
chafa_color_rgb_to_din99d(&rgb_color, &din99d_color);
```

DIN99d 是一个感知均匀色彩空间，更接近人眼对颜色差异的感知。这使得 chafa 在颜色匹配时比 libsixel 的 RGB 欧氏距离更准确。

### 3.7 符号映射系统

chafa 最独特的特性是其符号映射系统：

```c
ChafaSymbolMap *map = chafa_symbol_map_new();
chafa_symbol_map_add_by_tags(map, CHAFA_SYMBOL_TAG_BLOCK);
chafa_symbol_map_add_by_tags(map, CHAFA_SYMBOL_TAG_BORDER);
chafa_canvas_config_set_symbol_map(config, map);
```

**符号集分类：**
- `chafa-symbols-ascii.h` — ASCII 可打印字符
- `chafa-symbols-block.h` — Unicode Block 元素 (▀▄█▌▐等)
- `chafa-symbols-kana.h` — 日文假名
- `chafa-symbols-latin.h` — Latin 扩展字符
- `chafa-symbols-misc-narrow.h` — 窄符号

**符号匹配原理：**
每个 Unicode 字符有一个预计算的"形状"（8×8 或 16×16 位图）。对每个终端单元格：
1. 将图像区域缩放到单元格大小
2. 计算前景色和背景色（PCA 主成分分析确定最佳分割）
3. 遍历符号映射表，找到与图像形状最匹配的字符
4. 输出 `\x1b[38;2;R;G;Bm` (前景) + `\x1b[48;2;R;G;Bm` (背景) + 字符

### 3.8 SIMD 优化

chafa 在多个层面使用 SIMD 指令：

| 文件 | 指令集 | 用途 |
|------|--------|------|
| `chafa-avx2.c` | AVX2 (256-bit) | 颜色差异计算、批量像素处理 |
| `chafa-sse41.c` | SSE4.1 (128-bit) | 颜色差异计算 |
| `chafa-mmx.c` | MMX (64-bit) | 颜色差异计算（旧 CPU） |
| `chafa-popcnt.c` | POPCNT | 位计数加速 |

运行时检测 CPU 特性，选择最优路径：
```c
ChafaSIMDLevel level = chafa_get_simd_level();
// 根据 level 选择 avx2 / sse41 / mmx / 标准 C 路径
```

### 3.9 依赖

- **GLib** — 核心依赖（数据类型、内存管理、主循环）
- **内嵌库**：libnsgif (GIF)、lodepng (PNG)、smolscale (缩放)
- **可选**：libjpeg、libwebp、libtiff

### 3.10 构建

```bash
./configure
make
make install
```

---

## 4. 核心差异对比

### 4.1 设计哲学

| 维度 | libsixel | chafa |
|------|----------|-------|
| **设计目标** | Sixel 协议的参考实现 | 通用终端图形框架 |
| **API 风格** | 底层，暴露 Sixel 细节 | 高层，隐藏协议差异 |
| **依赖策略** | 零依赖（自包含） | 依赖 GLib 生态 |
| **扩展性** | 仅 Sixel | 插件式协议后端 |

### 4.2 编码算法对比

| 维度 | libsixel | chafa |
|------|----------|-------|
| **量化** | Median Cut (经典) | PNN (更现代) |
| **颜色空间** | RGB 欧氏距离 | DIN99d 感知均匀 |
| **抖动** | 8 种 (FS/Atkinson/JJN/Stucki/Burkes/A-Dither/X-Dither) | 3 种 (None/FS/Ordered) |
| **Sixel 编码** | 逐颜色遍历 + 链表排序 | Filter Bank 跳跃 + 位操作向量化 |
| **RLE** | `!COUNT CHAR` (≤255) | `!COUNT CHAR` (≤255) |
| **高色模式** | 15bpp 动态调色板 | 不支持 |
| **SIMD** | 无 | AVX2/SSE4.1/MMX |

### 4.3 Sixel 编码效率对比

```
libsixel 编码路径:
  像素 → map[color][x] 位掩码 → 链表节点排序 → 逐颜色输出
  问题: 链表分配 + 排序开销大

chafa 编码路径:
  像素 → SixelData (6字节打包) → Filter Bank 位域 → 位操作向量化输出
  优势: Filter Bank 跳过无关颜色，位操作替代逐像素比较
```

chafa 的 Filter Bank 优化：
```c
// 每 64 像素为一个 bank
#define FILTER_BANK_WIDTH 64

// 记录每个 bank 中出现的颜色
filter_set(srow, pen, bank);

// 编码时先检查 bank
if (!filter_get(srow, pen, i / FILTER_BANK_WIDTH)) {
    // 该颜色在此 bank 中不存在，跳过 64 像素
    n_reps += FILTER_BANK_WIDTH;
    continue;
}
```

### 4.4 独有特性

**libsoxel 独有：**
- HLS 调色板模式
- 15bpp 高色模式（动态调色板重定义）
- GNU Screen 穿透 (`-P`)
- 肤色校正（R 通道误差加权）
- 内置 Sixel 解码器（Sixel→像素）
- `sixel_encoder_encode_bytes()` API
- 终端 Sixel 支持自动检测

**chafa 独有：**
- 字符画模式（Unicode 符号匹配）
- Kitty 协议支持
- iTerm2 协议支持
- DIN99d 感知均匀色彩空间
- PNN 量化算法
- SIMD 加速 (AVX2/SSE4.1/MMX)
- Filter Bank 跳跃优化
- PCA 主成分分析（字符画前景/背景分割）
- tmux/screen 穿透（通用 Passthrough 系统）
- 内嵌图像缩放库 (smolscale)
- 终端能力数据库（自动检测终端类型）

---

## 5. 性能预期分析

### 5.1 编码速度

基于算法分析的预期：

| 场景 | libsixel | chafa | 原因 |
|------|----------|-------|------|
| 小图 (< 100×100) | 快 | 快 | 数据量小，差异不明显 |
| 中图 (500×500) | 中 | **快** | Filter Bank + SIMD 优势显现 |
| 大图 (1920×1080) | 慢 | **快** | Filter Bank 大幅减少颜色遍历 |
| 低色数 (≤ 16) | 快 | 快 | 颜色少，两种算法都快 |
| 高色数 (256) | 中 | **快** | PNN + Filter Bank 优势 |

### 5.2 输出体积

两种库都使用相同的 RLE 压缩（`!COUNT CHAR`，≤255），输出体积主要取决于：
- 调色板质量（PNN 通常更好 → 更少的噪声 → 更好的 RLE 压缩）
- 抖动方法（误差扩散增加噪声 → 降低 RLE 效率）

### 5.3 内存占用

| 维度 | libsixel | chafa |
|------|----------|-------|
| 库体积 | ~200KB .so | ~500KB .so |
| 运行时依赖 | 无 | GLib (~1MB) |
| 编码内存 | map[n_colors × width] | SixelData[width] + FilterBits |
| 量化内存 | 直方图 32768 桶 | PNN bins 32768 + 堆 |

---

## 6. 适用场景推荐

| 场景 | 推荐 | 理由 |
|------|------|------|
| **嵌入式/最小依赖** | libsixel | 零依赖，MIT 许可 |
| **纯 Sixel 编解码** | libsixel | 专注实现，API 更底层灵活 |
| **高色/动态调色板** | libsixel | 15bpp 高色模式独有 |
| **通用终端图形工具** | chafa | 多协议支持，CLI 工具完善 |
| **字符画输出** | chafa | 独有的符号匹配系统 |
| **Kitty/iTerm2 终端** | chafa | 原生协议支持 |
| **最佳颜色质量** | chafa | PNN + DIN99d 更优 |
| **最大编码速度** | chafa | SIMD + Filter Bank |
| **Python 脚本集成** | libsixel | 内置 ctypes 绑定 |
| **GLib/GNOME 生态** | chafa | 原生 GLib 集成 |
| **安全敏感环境** | chafa | 更少的历史 CVE |

---

## 7. 对 sixel-show.py 的启示

分析两个 C 库后，我们的 Python 实现可以借鉴的优化：

| 优化 | 来源 | 实施结果 |
|------|------|----------|
| Filter Bank 跳跃 | chafa | ❌ **已回退** — numpy 向量化已等效，额外 bank 计算反增开销 (2.4x 慢) |
| RLE 优化 | libsixel | ✅ 已应用 — 短 run 用 `.tobytes()` 替代逐字节 append (~1.1x) |
| Bayer 有序抖动 | libsixel A-Dither | ✅ 已应用 — `--dither` 选项减少色带 (编码 +80%) |
| PNN 量化 | chafa | 🔜 未实施 — PIL 的 MEDIANCUT 已足够，PNN 需要 C 扩展 |
| DIN99d 色彩空间 | chafa | 🔜 未实施 — 需要完整的色彩空间转换库 |
| 肤色校正 | libsixel | 🔜 未实施 — 人像图片专用，优先级低 |
| 8bit Sixel 模式 | libsixel | 🔜 未实施 — 终端兼容性考虑 |

### 7.1 关键经验：C 优化 ≠ Python 优化

**Filter Bank 的教训**：

chafa 的 Filter Bank 是典型的 C 级别微优化——通过减少分支和内存访问来加速逐像素循环。但在 numpy 向量化实现中，这类优化不仅无效，反而有害：

| 方面 | C 逐像素循环 | numpy 向量化 |
|------|-------------|-------------|
| 基本操作 | 每像素一次函数调用 | 整个数组一次 C 调用 |
| Filter Bank 收益 | 跳过 N 次调用 = 节省 N×开销 | 无调用可跳过 |
| Filter Bank 开销 | 位域检查（极低） | 数组分配 + `np.any()` + 分支 |
| 净效果 | **正收益** | **负收益** |

**原则**：从 C 库移植优化到 Python/numpy 时，必须理解底层执行模型的差异。C 级别的逐像素优化通常不适用于向量化实现。

### 7.2 真正有效的 Python 优化

本项目中实际有效的优化（按收益排序）：

| 优化 | 收益 | 原理 |
|------|------|------|
| numpy 向量化 | 13.2x | 消除 PIL 逐像素 Python 调用 |
| 流式编码 | 3x (累积) | 避免内存累积导致 GC 退化 |
| 减色 256→32 | 2.8x | 减少每 band 颜色迭代次数 |
| 批量颜色计算 | 1.2x | broadcasting 合并颜色循环 |
| RLE 压缩 | 输出 -92% | 减少终端渲染量 |
| 字符串缓存 | 1.1x | 避免循环中反复 encode() |
