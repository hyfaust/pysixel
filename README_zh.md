# Sixel Show

[English](README.md) | [简体中文](README_zh.md)

---

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-green.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()

> 一款快速的终端图片查看器，使用 Sixel 图形协议，支持优化的 GIF 动画播放。

Sixel Show 使用 Sixel 协议在终端中直接渲染图片。通过 numpy 加速的编码器，在 500×500 的 GIF 上实现了每帧 33ms 的实时播放，无需 GPU 加速。

## 目录

- [特性](#特性)
- [环境要求](#环境要求)
- [安装](#安装)
- [使用方法](#使用方法)
- [性能](#性能)
- [项目结构](#项目结构)
- [技术文档](#技术文档)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

## 特性

- **Sixel 图片显示** — 在支持 Sixel 的终端中渲染 PIL 支持的所有图片格式（PNG、JPEG、GIF、BMP、WebP 等）
- **GIF 动画播放** — 自动检测动画 GIF，循环播放，帧级精确计时
- **优化编码** — numpy 向量化编码，相比朴素 Python 实现提速 13 倍
- **实时播放** — 流式逐帧编码 + 自适应延迟，500×500 GIF 实现 33ms/帧
- **RLE 压缩** — 通过 Sixel 游程编码实现 12 倍输出体积压缩
- **Bayer 抖动** — 可选的有序抖动，减少低色数图片的色带伪影
- **零 GPU 依赖** — 纯 CPU 编码，基于 numpy 加速

## 环境要求

| 依赖 | 版本 | 是否必需 |
|------|------|----------|
| Python | >= 3.9 | 是 |
| Pillow | >= 9.0 | 是 |
| numpy | >= 1.20 | 是 |
| 支持 Sixel 的终端 | — | 是 |

**支持的终端：** Windows Terminal (≥ 1.22)、xterm、WezTerm、mlterm、foot 等支持 Sixel 协议的终端。

## 安装

```bash
# 克隆仓库
git clone <repository-url>
cd sixel_build

# 安装依赖
pip install pillow numpy
```

## 使用方法

### 显示静态图片

```bash
python sixel-show.py photo.png
```

### 播放 GIF 动画

```bash
# 自动检测 GIF，循环播放，Ctrl+C 停止
python sixel-show.py animation.gif
```

### 强制静态模式（仅显示第一帧）

```bash
python sixel-show.py --no-anim animation.gif
```

### 启用 Bayer 抖动

```bash
# 减少低色数图片的色带伪影
python sixel-show.py --dither photo.png
```

### 显示帮助信息

```bash
python sixel-show.py
```

### 命令行选项

| 选项 | 说明 |
|------|------|
| `--no-anim` | 强制静态模式 — 仅显示 GIF 的第一帧 |
| `--dither` | 启用 8×8 Bayer 有序抖动，减少色带伪影 |

## 性能

测试图片：500×500 动画 GIF（33 帧，目标帧延迟 30ms/帧）

| 指标 | 数值 |
|------|------|
| 单帧编码 | 32ms |
| GIF 播放（每帧） | 33ms |
| 每帧输出体积 | 71 KB（RLE 压缩 12 倍） |
| vs 帧延迟目标 | 0.91x ✅（实时） |
| vs 朴素 Python 提速 | **13.2 倍**（单帧），**40.6 倍**（完整 GIF） |

### 优化技术

| 技术 | 提速 | 来源 |
|------|------|------|
| numpy 向量化 | 13.2 倍 | 用数组操作替代 PIL 逐像素访问 |
| 流式编码 | 3 倍（累积） | 逐帧编码+释放，避免 GC 退化 |
| 减色 256→32 | 2.8 倍 | 更少颜色 = 每 band 更少迭代 |
| 批量颜色计算 | 1.2 倍 | numpy broadcasting 一次算所有颜色 |
| RLE 压缩 | 输出减少 92% | DEC VT Sixel `!COUNT CHAR` |
| 字符串缓存 | 1.1 倍 | 预构建颜色和长度的编码字符串 |

## 项目结构

```
sixel_build/
├── sixel-show.py              # 主脚本 — Sixel 图片查看器和 GIF 播放器
├── sixel-show.bat             # Windows BAT 包装器
├── docs/                      # 技术文档
│   ├── benchmark-report.md    # 性能基准测试 (A/B/C/D)
│   ├── gif-animation-dev-record.md   # GIF 优化开发记录
│   ├── libsixel-vs-chafa-analysis.md # C 库分析 (libsixel vs chafa)
│   └── nuitka-compilation-guide.md   # Nuitka 编译指南
├── benchmark.py               # 基准测试：exe vs Python vs BAT
├── benchmark_final.py         # 基准测试：原始版 vs 优化版
├── benchmark_v2.py            # 基准测试：v1 vs v2 对比
├── benchmark_compare.py       # 基准测试：详细版本对比
├── profile_sixel.py           # 性能分析：单帧编码拆解
├── profile_detail.py          # 性能分析：逐帧详细计时
├── profile_streaming.py       # 性能分析：流式编码验证
└── LICENSE                    # GPL v3 许可证
```

## 技术文档

详细技术文档位于 [`docs/`](docs/) 目录：

- **[性能基准测试报告](docs/benchmark-report.md)** — 所有优化阶段的全面性能基准，包括 Nuitka exe 编译结果
- **[GIF 动画开发记录](docs/gif-animation-dev-record.md)** — 14 个优化阶段的逐步开发日志，从朴素实现到实时播放
- **[libsixel vs chafa 分析](docs/libsixel-vs-chafa-analysis.md)** — 两个主流 C Sixel 库的深度源码分析，以及在本项目中的应用经验
- **[Nuitka 编译指南](docs/nuitka-compilation-guide.md)** — 使用 Nuitka 将 Python 脚本编译为独立可执行文件的方法

## 贡献指南

欢迎贡献！请随时提交 Issue 和 Pull Request。

1. Fork 本仓库
2. 创建特性分支（`git checkout -b feature/amazing-feature`）
3. 提交更改（`git commit -m 'Add amazing feature'`）
4. 推送到分支（`git push origin feature/amazing-feature`）
5. 创建 Pull Request

## 许可证

本项目基于 GNU 通用公共许可证 v3.0 授权 — 详见 [LICENSE](LICENSE) 文件。
