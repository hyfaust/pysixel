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

### Quick Start

```bash
# Basic usage
python pysixel.py photo.png
python pysixel.py animation.gif

# Output control
python pysixel.py -o output.six photo.png        # output to file
python pysixel.py -8 photo.png                    # 8bit DCS mode
python pysixel.py -R photo.png                    # GRI ≤255 (VT240 compat)

# GIF control
python pysixel.py -l disable animation.gif        # play once, no loop
python pysixel.py -g -l force animation.gif       # ignore delay, force loop

# Resize & crop
python pysixel.py -w 400 -H 300 photo.png         # explicit size
python pysixel.py -r lanczos3 -w 800 photo.png    # lanczos resampling
python pysixel.py -c 200x200+50+50 photo.png      # crop region

# Color & quality
python pysixel.py --colors 64 photo.png           # 64 colors
python pysixel.py -e photo.png                    # monochrome
python pysixel.py -i photo.png                    # inverse (negative)
python pysixel.py -B "#ffffff" photo.png          # white background
python pysixel.py -q high photo.png               # high quality quantize

# Encoding strategy
python pysixel.py -E fast animation.gif           # skip RLE (faster)
python pysixel.py -E size -o out.six photo.png    # smaller file

# Terminal compatibility
python pysixel.py -P photo.png                    # tmux/screen passthrough
python pysixel.py --dither photo.png              # Bayer dithering

# Combined
python pysixel.py -w 640 --colors 128 -d fs -r lanczos3 -o output.six photo.png
```

### Command-Line Reference

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image` | Image file path (positional) | required |
| `--no-anim` | Static mode, show first frame only | off |
| `--dither` | Enable Bayer 8×8 ordered dithering | off |
| `--colors N` | Palette colors (2-256) | 256 |
| `--max-width COLS` | Max terminal columns | terminal width |
| `-o FILE` | Output to file | stdout |
| `-l MODE` | GIF loop: auto/force/disable | auto |
| `-8` | 8bit DCS mode | off (7bit) |
| `-g` | Ignore GIF frame delay | off |
| `-R` | GRI limit ≤255 (VT240) | off |
| `-w PX` | Output width in pixels | auto |
| `-H PX` | Output height in pixels | auto |
| `-r FILTER` | Resampling: nearest/bilinear/bicubic/lanczos2/3/4/gaussian/hamming | bilinear |
| `-c WxH+X+Y` | Crop region | none |
| `-e` | Monochrome (grayscale) | off |
| `-B COLOR` | Background color (#rrggbb) | none |
| `-E MODE` | Encode policy: auto/fast/size | auto |
| `-q MODE` | Quality: auto/low/high/full | auto |
| `-P` | tmux/screen passthrough | off |
| `-i` | Invert colors (negative) | off |

## Performance

Benchmarked on a 500x500 GIF with 33 frames (target frame delay: 30ms/frame).

| Metric | Value |
|--------|-------|
| Single frame encoding | 32ms |
| GIF playback (per frame) | 33ms |
| Output size per frame | 71 KB (12x compression via RLE) |
| vs. frame delay target | 0.91x (real-time) |
| Speedup vs. naive Python | **13.2x** (single frame), **40.6x** (full GIF) |

> **Tip:** For GIF playback where speed matters more than output size, use `-E fast` to skip RLE encoding and gain additional throughput. Conversely, use `-E size` with `-o` to minimize file size for saved output.

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
