# pysixel

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-green.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()

[English](README.md) | [简体中文](README_zh.md)

A fast terminal image viewer using the Sixel graphics protocol, with optimized GIF animation support powered by numpy vectorized encoding.

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [Performance](#performance)
- [Project Structure](#project-structure)
- [Technical Documentation](#technical-documentation)
- [Contributing](#contributing)
- [Acknowledgments](#acknowledgments)
- [License](#license)

## Features

- **Sixel image display** — Renders any PIL-supported image format (PNG, JPEG, GIF, BMP, WebP, etc.) in Sixel-capable terminals
- **GIF animation playback** — Automatic detection and smooth looping of animated GIFs with frame-accurate timing; press `Ctrl+C` to stop
- **Numpy vectorized encoding** — 13x speedup over naive Python by replacing per-pixel access with array operations
- **Real-time GIF playback** — Streaming per-frame encode with adaptive delay, achieving 33ms/frame for 500x500 GIFs
- **RLE compression** — 12x output size reduction via Sixel Run-Length Encoding
- **Bayer dithering** — Optional 8x8 ordered dithering (`--dither`) to reduce color banding in low-palette images
- **Zero GPU dependency** — Pure CPU-based encoding using numpy

## Prerequisites

| Dependency | Version | Required |
|------------|---------|----------|
| Python     | >= 3.9  | Yes      |
| Pillow     | >= 9.0  | Yes      |
| numpy      | >= 1.20 | Yes      |
| Sixel-capable terminal | -- | Yes |

**Supported terminals:** Windows Terminal (>= 1.22), xterm, WezTerm, mlterm, foot, and other terminals with Sixel protocol support.

## Installation

### From PyPI (if published)

```bash
pip install pysixel
```

### From Source

```bash
git clone https://github.com/hyfaust/pysixel.git
cd pysixel
pip install -r requirements.txt
```

## Usage

### Display a Static Image

```bash
python pysixel.py photo.png
```

### Play a GIF Animation

```bash
# Auto-detects GIF, loops playback, Ctrl+C to stop
python pysixel.py animation.gif
```

### Force Static Mode (First Frame Only)

```bash
python pysixel.py --no-anim gif.gif
```

### Enable Bayer Dithering

```bash
# Reduces color banding for images with limited palette
python pysixel.py --dither pic.png
```

### Command-Line Options

| Option | Description |
|--------|-------------|
| `--no-anim` | Force static mode -- display only the first frame of GIFs |
| `--dither` | Enable 8x8 Bayer ordered dithering to reduce color banding |

## Performance

Benchmarked on a 500x500 GIF with 33 frames (target frame delay: 30ms/frame).

| Metric | Value |
|--------|-------|
| Single frame encoding | 32ms |
| GIF playback (per frame) | 33ms |
| Output size per frame | 71 KB (12x compression via RLE) |
| vs. frame delay target | 0.91x (real-time) |
| Speedup vs. naive Python | **13.2x** (single frame), **40.6x** (full GIF) |

### Optimization Techniques

| Technique | Speedup | Description |
|-----------|---------|-------------|
| Numpy vectorization | 13.2x | Replace PIL per-pixel access with array operations |
| Streaming encode | 3x (cumulative) | Per-frame encode + release, avoid GC degradation |
| Color reduction (256 to 32) | 2.8x | Fewer colors = fewer iterations per band |
| Batch color computation | 1.2x | Numpy broadcasting for all colors at once |
| RLE compression | Output -92% | DEC VT Sixel `!COUNT CHAR` |
| String caching | 1.1x | Pre-built encoded strings for colors and run lengths |

## Project Structure

```
pysixel/
├── pysixel.py                 # Main script
├── README.md                  # English documentation
├── README_zh.md               # Chinese documentation
├── docs/                      # Technical documentation
│   ├── benchmark-report.md
│   ├── development-record.md
│   ├── library-analysis.md
│   └── performance-guide.md
├── requirements.txt           # Python dependencies
├── LICENSE                    # GPL v3
└── .gitignore
```

## Technical Documentation

Detailed technical documents are available in the [`docs/`](docs/) directory:

- **[Benchmark Report](docs/benchmark-report.md)** -- Comprehensive performance benchmarks across all optimization stages
- **[Development Record](docs/development-record.md)** -- Step-by-step development log covering GIF encoding optimization, from naive implementation to real-time playback
- **[Library Analysis](docs/library-analysis.md)** -- Deep source-code analysis of libsixel and chafa, with lessons applied to this project
- **[Performance Guide](docs/performance-guide.md)** -- Detailed breakdown of optimization techniques and their impact

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Acknowledgments

- [libsixel](https://github.com/saitoha/libsixel) -- The reference Sixel encoder/decoder library by Hayaki Saito. Its Median Cut quantizer, dithering modes, and RLE implementation served as the foundation for understanding the Sixel protocol.
- [chafa](https://github.com/hpjansson/chafa/) -- A versatile terminal graphics library by Hans Petter Jansson. Its Filter Bank optimization, PNN quantizer, and multi-protocol architecture inspired key design decisions in this project.

## License

This project is licensed under the GNU General Public License v3.0 -- see the [LICENSE](LICENSE) file for details.
