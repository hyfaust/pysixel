# pysixel

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-green.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()

[English](README.md) | [简体中文](README_zh.md)

一款快速的终端图片查看器，使用 Sixel 图形协议，通过 numpy 向量化编码实现高效的 GIF 动画播放。

## 目录

- [特性](#特性)
- [环境要求](#环境要求)
- [安装](#安装)
- [使用方法](#使用方法)
- [性能](#性能)
- [项目结构](#项目结构)
- [技术文档](#技术文档)
- [贡献指南](#贡献指南)
- [致谢](#致谢)
- [许可证](#许可证)

## 特性

- **Sixel 图片显示** — 在支持 Sixel 的终端中渲染 PIL 支持的所有图片格式（PNG、JPEG、GIF、BMP、WebP 等）
- **GIF 动画播放** — 自动检测动画 GIF，循环播放，帧级精确计时；按 `Ctrl+C` 停止
- **numpy 向量化编码** — 用数组操作替代逐像素访问，相比朴素 Python 实现提速 13 倍
- **实时 GIF 播放** — 流式逐帧编码 + 自适应延迟，500x500 GIF 实现 33ms/帧
- **RLE 压缩** — 通过 Sixel 游程编码实现 12 倍输出体积压缩
- **Bayer 抖动** — 可选的 8x8 有序抖动（`--dither`），减少低色数图片的色带伪影
- **零 GPU 依赖** — 纯 CPU 编码，基于 numpy 加速

## 环境要求

| 依赖 | 版本 | 是否必需 |
|------|------|----------|
| Python | >= 3.9 | 是 |
| Pillow | >= 9.0 | 是 |
| numpy | >= 1.20 | 是 |
| 支持 Sixel 的终端 | -- | 是 |

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

## 使用方法

### 显示静态图片

```bash
python pysixel.py photo.png
```

### 播放 GIF 动画

```bash
# 自动检测 GIF，循环播放，Ctrl+C 停止
python pysixel.py animation.gif
```

### 强制静态模式（仅显示第一帧）

```bash
python pysixel.py --no-anim gif.gif
```

### 启用 Bayer 抖动

```bash
# 减少低色数图片的色带伪影
python pysixel.py --dither pic.png
```

### 命令行选项

| 选项 | 说明 |
|------|------|
| `--no-anim` | 强制静态模式 -- 仅显示 GIF 的第一帧 |
| `--dither` | 启用 8x8 Bayer 有序抖动，减少色带伪影 |

## 性能

基准测试条件：500x500 GIF，33 帧，目标帧延迟 30ms/帧。

| 指标 | 数值 |
|------|------|
| 单帧编码 | 32ms |
| GIF 播放（每帧） | 33ms |
| 每帧输出体积 | 71 KB（RLE 压缩 12 倍） |
| vs 帧延迟目标 | 0.91x（实时） |
| vs 朴素 Python 提速 | **13.2 倍**（单帧），**40.6 倍**（完整 GIF） |

### 优化技术

| 技术 | 提速 | 说明 |
|------|------|------|
| numpy 向量化 | 13.2 倍 | 用数组操作替代 PIL 逐像素访问 |
| 流式编码 | 3 倍（累积） | 逐帧编码+释放，避免 GC 退化 |
| 减色 256 到 32 | 2.8 倍 | 更少颜色 = 每 band 更少迭代 |
| 批量颜色计算 | 1.2 倍 | numpy broadcasting 一次计算所有颜色 |
| RLE 压缩 | 输出减少 92% | DEC VT Sixel `!COUNT CHAR` |
| 字符串缓存 | 1.1 倍 | 预构建颜色和长度的编码字符串 |

## 项目结构

```
pysixel/
├── pysixel.py                 # 主脚本
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
