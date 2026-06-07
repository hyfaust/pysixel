# pysixel

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-green.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()

[English](README.md) | [简体中文](README_zh.md)

Python Sixel 工具集 — Sixel 图形的编码、解码和自适应查看，灵感来自 libsixel 的 `img2sixel` 和 `sixel2png`。

## 目录

- [工具一览](#工具一览)
- [环境要求](#环境要求)
- [安装](#安装)
- [pyimg2six — 图片转 Sixel](#pyimg2six--图片转-sixel)
  - [特性](#特性)
  - [快速开始](#快速开始)
  - [命令行参数一览](#命令行参数一览)
- [pysix2png — Sixel 转 PNG](#pysix2png--sixel-转-png)
  - [特性](#特性-1)
  - [快速开始](#快速开始-1)
  - [命令行参数一览](#命令行参数一览-1)
- [pysixview — 自适应查看器](#pysixview--自适应查看器)
- [性能](#性能)
- [项目结构](#项目结构)
- [技术文档](#技术文档)
- [贡献指南](#贡献指南)
- [致谢](#致谢)
- [许可证](#许可证)

## 工具一览

| 工具 | 说明 | libsixel 对应 |
|------|------|---------------|
| `pyimg2six.py` | 图片 → Sixel 编码器 & 终端查看器 | `img2sixel` |
| `pysix2png.py` | Sixel → PNG 解码器 | `sixel2png` |
| `pysixview.py` | 自适应 Sixel 查看器 — 超宽图像自动缩放至终端宽度 | -- |

## 环境要求

| 依赖 | 版本 | 是否必需 |
|------|------|----------|
| Python | >= 3.9 | 是 |
| Pillow | >= 9.0 | 是 |
| numpy | >= 1.20 | 是（仅 pyimg2six） |
| 支持 Sixel 的终端 | -- | 是（仅显示时） |

**支持的终端：** Windows Terminal (>= 1.22)、xterm、WezTerm、mlterm、foot 等支持 Sixel 协议的终端。

## 安装

### 通过 PyPI 安装（如已发布）

```bash
pip install pysixel
```

### 从源码安装

```bash
git clone https://github.com/hyfaust/pysixel.git
cd pysixel
pip install -r requirements.txt
```

---

## pyimg2six — 图片转 Sixel

### 特性

- **Sixel 图片显示** — 在支持 Sixel 的终端中渲染 PIL 支持的所有图片格式（PNG、JPEG、GIF、BMP、WebP 等）
- **GIF 动画播放** — 自动检测动画 GIF，循环播放，帧级精确计时；按 `Ctrl+C` 停止
- **numpy 向量化编码** — 用数组操作替代逐像素访问，相比朴素 Python 实现提速 13 倍
- **实时 GIF 播放** — 流式逐帧编码 + 自适应延迟，500x500 GIF 实现 33ms/帧
- **RLE 压缩** — 通过 Sixel 游程编码实现 12 倍输出体积压缩
- **抖动模式** — Bayer 8x8 有序抖动和 Floyd-Steinberg 误差扩散，FS 内置 15-bit 哈希缓存（`-d bayer` / `-d fs`）
- **光栅属性** — 输出 `"1;1;W;H` 像素宽高比，终端正确渲染无需高度压缩
- **保持原始分辨率** — `--no-resize` 选项，不缩放图片
- **智能优化** — 低色图自动跳过 FS、GIF 调色板缓存、大图采样量化
- **零 GPU 依赖** — 纯 CPU 编码，基于 numpy 加速

### 快速开始

```bash
# 基本用法
python pyimg2six.py photo.png
python pyimg2six.py animation.gif

# 输出控制
python pyimg2six.py -o output.six photo.png        # 输出到文件
python pyimg2six.py -8 photo.png                    # 8bit DCS 模式
python pyimg2six.py -R photo.png                    # GRI ≤255（VT240 兼容）

# GIF 控制
python pyimg2six.py -l disable animation.gif        # 播放一次，不循环
python pyimg2six.py -g -l force animation.gif       # 忽略帧延迟，强制循环

# 缩放与裁剪
python pyimg2six.py -w 400 -H 300 photo.png         # 指定尺寸
python pyimg2six.py -r lanczos3 -w 800 photo.png    # lanczos 重采样
python pyimg2six.py -c 200x200+50+50 photo.png      # 裁剪区域

# 颜色与质量
python pyimg2six.py --colors 64 photo.png           # 64 色
python pyimg2six.py -e photo.png                    # 单色（灰度）
python pyimg2six.py -i photo.png                    # 反色（负片）
python pyimg2six.py -B "#ffffff" photo.png          # 白色背景
python pyimg2six.py -q high photo.png               # 高质量量化

# 编码策略
python pyimg2six.py -E fast animation.gif           # 跳过 RLE（更快）
python pyimg2six.py -E size -o out.six photo.png    # 更小文件

# 终端兼容
python pyimg2six.py -P photo.png                    # tmux/screen 透传
python pyimg2six.py -d bayer photo.png              # Bayer 有序抖动
python pyimg2six.py -d fs photo.png                 # Floyd-Steinberg 误差扩散
python pyimg2six.py --no-resize photo.png           # 保持原始分辨率

# 组合使用
python pyimg2six.py -w 640 --colors 128 -r lanczos3 -o output.six photo.png
```

### 命令行参数一览

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `image` | 图片文件路径（位置参数） | 必填 |
| `--no-anim` | 静态模式，仅显示第一帧 | 关闭 |
| `-d MODE` | 抖动模式：none/bayer/fs | none |
| `--colors N` | 调色板颜色数（2-256） | 256 |
| `--max-width COLS` | 最大终端列数 | 终端宽度 |
| `--no-resize` | 保持原始分辨率，不缩放 | 关闭 |
| `-o FILE` | 输出到文件 | stdout |
| `-l MODE` | GIF 循环模式：auto/force/disable | auto |
| `-8` | 8bit DCS 模式 | 关闭（7bit） |
| `-g` | 忽略 GIF 帧延迟 | 关闭 |
| `-R` | GRI 限制 ≤255（VT240） | 关闭 |
| `-w PX` | 输出宽度（像素） | 自动 |
| `-H PX` | 输出高度（像素） | 自动 |
| `-r FILTER` | 重采样算法：nearest/bilinear/bicubic/lanczos2/3/4/gaussian/hamming | bilinear |
| `-c WxH+X+Y` | 裁剪区域 | 无 |
| `-e` | 单色模式（灰度） | 关闭 |
| `-B COLOR` | 背景颜色（#rrggbb） | 无 |
| `-E MODE` | 编码策略：auto/fast/size | auto |
| `-q MODE` | 质量：auto/low/high/full | auto |
| `-P` | tmux/screen 透传 | 关闭 |
| `-i` | 反色（负片） | 关闭 |

---

## pysix2png — Sixel 转 PNG

### 特性

- **纯 Python Sixel 解码器** — 基于 libsixel 1.8.7 的 `fromsixel.c` 状态机实现，无 C 依赖
- **标准输入/输出支持** — 从文件或 stdin 读取，写入文件或 stdout
- **完整颜色支持** — RGB 和 HLS 颜色定义，256 色调色板
- **光栅属性处理** — 正确解析 Pan/Pad/Ph/Pv 宽高比和尺寸属性
- **重复与 RLE 解码** — 处理 Sixel 重复引入符（`!Pn`）和所有控制序列

### 快速开始

```bash
# 将 Sixel 文件转换为 PNG
python pysix2png.py -i input.sixel -o output.png

# 从 stdin 读取，写入 stdout（管道友好）
cat input.sixel | python pysix2png.py > output.png

# 显示版本
python pysix2png.py -V
```

### 命令行参数一览

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-i, --input` | 输入 Sixel 文件（`-` 表示 stdin） | stdin |
| `-o, --output` | 输出 PNG 文件（`-` 表示 stdout） | stdout |
| `-V, --version` | 显示版本信息 | -- |
| `-H, --help` | 显示帮助信息 | -- |

---

## pysixview — 自适应查看器

自动检测终端宽度，超宽 Sixel 图像缩放后输出，未超宽直接输出。

```bash
# 查看 .six 文件（超宽时自动缩放）
python pysixview.py image.six

# 手动指定最大像素宽度
python pysixview.py -w 800 image.six

# 显示图像尺寸
python pysixview.py -i image.six

# 调整乘数并保存
python pysixview.py -m 8 --save image.six
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `input` | Sixel 文件路径（位置参数） | 必填 |
| `-w PX` | 最大像素宽度 | 终端列数 × 乘数 |
| `-m N` | 终端列数乘数 | 8（保存在 ~/.sixview.conf） |
| `--save` | 保存乘数到配置文件 | 关闭 |
| `-i, --info` | 显示图像尺寸后退出 | 关闭 |
| `--no-resize` | 不缩放，直接输出 | 关闭 |

---

## 性能

基准测试条件：500x500 GIF，33 帧，目标帧延迟 30ms/帧。

| 指标 | 数值 |
|------|------|
| 单帧编码 | 32ms |
| GIF 播放（每帧） | 33ms |
| 每帧输出体积 | 71 KB（RLE 压缩 12 倍） |
| vs 帧延迟目标 | 0.91x（实时） |
| vs 朴素 Python 提速 | **13.2 倍**（单帧），**40.6 倍**（完整 GIF） |

> **提示：** 在 GIF 播放场景中，若速度优先于输出体积，可使用 `-E fast` 跳过 RLE 编码以获得更高吞吐。反之，配合 `-o` 使用 `-E size` 可最小化保存文件的体积。

### 优化技术

| 技术 | 提速 | 说明 |
|------|------|------|
| numpy 向量化 | 13.2 倍 | 用数组操作替代 PIL 逐像素访问 |
| 流式编码 | 3 倍（累积） | 逐帧编码+释放，避免 GC 退化 |
| 减色 256 到 32 | 2.8 倍 | 更少颜色 = 每 band 更少迭代 |
| 批量颜色计算 | 1.2 倍 | numpy broadcasting 一次计算所有颜色 |
| RLE 压缩 | 输出减少 92% | DEC VT Sixel `!COUNT CHAR`（阈值=3） |
| 字符串缓存 | 1.1 倍 | 预构建颜色和长度的编码字符串 |
| 光栅属性 | 正确宽高比 | `"1;1;W;H` 消除 char_aspect hack |
| FS 哈希缓存 | O(1) 查找 | 15-bit cachetable 加速 Floyd-Steinberg 颜色匹配 |
| 自动禁用 FS | 无损时跳过 | 15-bit 哈希检测低色图，跳过误差扩散 |
| GIF 调色板缓存 | 跳过重复量化 | 后续帧复用第一帧调色板 |
| 采样量化 | 大图加速 | 像素数 > 1M 时下采样做 MEDIANCUT |

## 项目结构

```
pysixel/
├── pyimg2six.py               # 图片→Sixel 编码器（img2sixel 等价）
├── pysix2png.py               # Sixel→PNG 解码器（sixel2png 等价）
├── pysixview.py                 # 自适应 Sixel 查看器（自动缩放至终端宽度）
├── README.md                  # 英文文档
├── README_zh.md               # 中文文档
├── docs/                      # 技术文档
│   ├── benchmark-report.md
│   ├── development-record.md
│   ├── library-analysis.md
│   └── performance-guide.md
├── requirements.txt           # Python 依赖
├── LICENSE                    # GPL v3 许可证
└── .gitignore
```

## 技术文档

详细技术文档位于 [`docs/`](docs/) 目录：

- **[性能基准测试报告](docs/benchmark-report.md)** -- 所有优化阶段的全面性能基准测试
- **[开发记录](docs/development-record.md)** -- GIF 编码优化的逐步开发日志，从朴素实现到实时播放
- **[库分析](docs/library-analysis.md)** -- libsixel 和 chafa 的深度源码分析，以及在本项目中的应用经验
- **[性能指南](docs/performance-guide.md)** -- 各项优化技术的详细分解及其效果

## 贡献指南

欢迎贡献！请随时提交 Issue 和 Pull Request。

1. Fork 本仓库
2. 创建特性分支（`git checkout -b feature/amazing-feature`）
3. 提交更改（`git commit -m 'Add amazing feature'`）
4. 推送到分支（`git push origin feature/amazing-feature`）
5. 创建 Pull Request

## 致谢

- [libsixel](https://github.com/saitoha/libsixel) -- Hayaki Saito 开发的 Sixel 参考实现库。其 Median Cut 量化器、抖动模式和 RLE 实现是本项目理解 Sixel 协议的基础。
- [chafa](https://github.com/hpjansson/chafa/) -- Hans Petter Jansson 开发的通用终端图形库。其 Filter Bank 优化、PNN 量化器和多协议架构启发了本项目的关键设计决策。

## 许可证

本项目基于 GNU 通用公共许可证 v3.0 授权 -- 详见 [LICENSE](LICENSE) 文件。
