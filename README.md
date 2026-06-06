# Sixel Show

[English](README.md) | [简体中文](README_zh.md)

---

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-green.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()

> A fast terminal image viewer using the Sixel graphics protocol, with optimized GIF animation support.

Sixel Show renders images directly in your terminal using the Sixel protocol. It features GPU-free, numpy-accelerated encoding that achieves real-time GIF playback at 33ms per frame on a 500×500 image.

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [Performance](#performance)
- [Project Structure](#project-structure)
- [Technical Documentation](#technical-documentation)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Sixel image display** — Renders any PIL-supported image format (PNG, JPEG, GIF, BMP, WebP, etc.) in Sixel-capable terminals
- **GIF animation playback** — Automatic detection and smooth looping of animated GIFs with frame-accurate timing
- **Optimized encoding** — numpy vectorized encoding achieving 13x speedup over naive Python implementation
- **Real-time playback** — Streaming per-frame encode with adaptive delay, reaching 33ms/frame for 500×500 GIFs
- **RLE compression** — 12x output size reduction via Sixel Run-Length Encoding
- **Bayer dithering** — Optional ordered dithering to reduce color banding in low-palette images
- **Zero GPU dependency** — Pure CPU-based encoding using numpy

## Prerequisites

| Dependency | Version | Required |
|------------|---------|----------|
| Python     | >= 3.9  | Yes      |
| Pillow     | >= 9.0  | Yes      |
| numpy      | >= 1.20 | Yes      |
| Sixel-capable terminal | — | Yes |

**Supported terminals:** Windows Terminal (≥ 1.22), xterm, WezTerm, mlterm, foot, and other terminals with Sixel protocol support.

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd sixel_build

# Install dependencies
pip install pillow numpy
```

## Usage

### Display a Static Image

```bash
python sixel-show.py photo.png
```

### Play a GIF Animation

```bash
# Auto-detects GIF, loops playback, Ctrl+C to stop
python sixel-show.py animation.gif
```

### Force Static Mode (First Frame Only)

```bash
python sixel-show.py --no-anim animation.gif
```

### Enable Bayer Dithering

```bash
# Reduces color banding for images with limited palette
python sixel-show.py --dither photo.png
```

### Show Help

```bash
python sixel-show.py
```

### Command-Line Options

| Option | Description |
|--------|-------------|
| `--no-anim` | Force static mode — display only the first frame of GIFs |
| `--dither` | Enable 8×8 Bayer ordered dithering to reduce color banding |

## Performance

Benchmarked on a 500×500 animated GIF (33 frames, 30ms/frame target):

| Metric | Value |
|--------|-------|
| Single frame encoding | 32ms |
| GIF playback (per frame) | 33ms |
| Output size per frame | 71 KB (12x compression via RLE) |
| vs. frame delay target | 0.91x ✅ (real-time) |
| Speedup vs. naive Python | **13.2x** (single frame), **40.6x** (full GIF) |

### Optimization Techniques

| Technique | Speedup | Source |
|-----------|---------|--------|
| numpy vectorization | 13.2x | Replace PIL per-pixel access with array operations |
| Streaming encode | 3x (cumulative) | Per-frame encode + release, avoid GC degradation |
| Color reduction (256→32) | 2.8x | Fewer colors = fewer iterations per band |
| Batch color computation | 1.2x | numpy broadcasting for all colors at once |
| RLE compression | Output -92% | DEC VT Sixel `!COUNT CHAR` |
| String caching | 1.1x | Pre-built encoded strings for colors and run lengths |

## Project Structure

```
sixel_build/
├── sixel-show.py              # Main script — Sixel image viewer and GIF player
├── sixel-show.bat             # Windows BAT wrapper
├── docs/                      # Technical documentation
│   ├── benchmark-report.md    # Performance benchmarks (A/B/C/D)
│   ├── gif-animation-dev-record.md   # GIF optimization development log
│   ├── libsixel-vs-chafa-analysis.md # C library analysis (libsixel vs chafa)
│   └── nuitka-compilation-guide.md   # Nuitka exe compilation guide
├── benchmark.py               # Benchmark: exe vs Python vs BAT
├── benchmark_final.py         # Benchmark: original vs optimized
├── benchmark_v2.py            # Benchmark: v1 vs v2 comparison
├── benchmark_compare.py       # Benchmark: detailed version comparison
├── profile_sixel.py           # Profiling: single-frame encoding breakdown
├── profile_detail.py          # Profiling: per-frame detailed timing
├── profile_streaming.py       # Profiling: streaming encode verification
└── LICENSE                    # GPL v3
```

## Technical Documentation

Detailed technical documents are available in the [`docs/`](docs/) directory:

- **[Benchmark Report](docs/benchmark-report.md)** — Comprehensive performance benchmarks across all optimization stages, including Nuitka exe compilation results
- **[GIF Animation Development Record](docs/gif-animation-dev-record.md)** — Step-by-step development log covering 14 optimization stages, from naive implementation to real-time playback
- **[libsixel vs chafa Analysis](docs/libsixel-vs-chafa-analysis.md)** — Deep source-code analysis of two major C Sixel libraries, with lessons applied to this project
- **[Nuitka Compilation Guide](docs/nuitka-compilation-guide.md)** — How to compile the Python script into a standalone executable using Nuitka

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the GNU General Public License v3.0 — see the [LICENSE](LICENSE) file for details.
