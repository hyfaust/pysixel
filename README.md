# pysixel

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-green.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()

[English](README.md) | [简体中文](README_zh.md)

Python Sixel toolkit — encoding, decoding, and viewing tools for Sixel graphics, inspired by libsixel's `img2sixel` and `sixel2png`.

## Table of Contents

- [Tools](#tools)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [pyimg2six — Image to Sixel](#pyimg2six--image-to-sixel)
  - [Features](#features)
  - [Quick Start](#quick-start)
  - [Command-Line Reference](#command-line-reference)
- [pysix2png — Sixel to PNG](#pysix2png--sixel-to-png)
  - [Features](#features-1)
  - [Quick Start](#quick-start-1)
  - [Command-Line Reference](#command-line-reference-1)
- [pysixview — Adaptive Viewer](#pysixview--adaptive-viewer)
- [Performance](#performance)
- [Project Structure](#project-structure)
- [Technical Documentation](#technical-documentation)
- [Contributing](#contributing)
- [Acknowledgments](#acknowledgments)
- [License](#license)

## Tools

| Tool | Description | Libsixel Equivalent |
|------|-------------|---------------------|
| `pyimg2six.py` | Image → Sixel encoder & terminal viewer | `img2sixel` |
| `pysix2png.py` | Sixel → PNG decoder | `sixel2png` |
| `pysixview.py` | Adaptive Sixel viewer — auto-scales wide images to terminal width | -- |

## Prerequisites

| Dependency | Version | Required |
|------------|---------|----------|
| Python     | >= 3.9  | Yes      |
| Pillow     | >= 9.0  | Yes      |
| numpy      | >= 1.20 | Yes (pyimg2six only) |
| Sixel-capable terminal | -- | Yes (for display) |

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

---

## pyimg2six — Image to Sixel

### Features

- **Sixel image display** — Renders any PIL-supported image format (PNG, JPEG, GIF, BMP, WebP, etc.) in Sixel-capable terminals
- **GIF animation playback** — Automatic detection and smooth looping of animated GIFs with frame-accurate timing; press `Ctrl+C` to stop
- **Numpy vectorized encoding** — 13x speedup over naive Python by replacing per-pixel access with array operations
- **Real-time GIF playback** — Streaming per-frame encode with adaptive delay, achieving 33ms/frame for 500x500 GIFs
- **RLE compression** — 12x output size reduction via Sixel Run-Length Encoding
- **Dithering modes** — Bayer 8x8 ordered dithering and Floyd-Steinberg error diffusion with 15-bit hash cache (`-d bayer` / `-d fs`)
- **Raster attributes** — `"1;1;W;H` pixel aspect ratio for correct terminal rendering without height distortion
- **Original resolution** — `--no-resize` flag to keep image at native pixel dimensions
- **Smart optimizations** — Auto-disable FS for low-color images, GIF palette caching, sampling quantization for large images
- **Zero GPU dependency** — Pure CPU-based encoding using numpy

### Quick Start

```bash
# Basic usage
python pyimg2six.py photo.png
python pyimg2six.py animation.gif

# Output control
python pyimg2six.py -o output.six photo.png        # output to file
python pyimg2six.py -8 photo.png                    # 8bit DCS mode
python pyimg2six.py -R photo.png                    # GRI ≤255 (VT240 compat)

# GIF control
python pyimg2six.py -l disable animation.gif        # play once, no loop
python pyimg2six.py -g -l force animation.gif       # ignore delay, force loop

# Resize & crop
python pyimg2six.py -w 400 -H 300 photo.png         # explicit size
python pyimg2six.py -r lanczos3 -w 800 photo.png    # lanczos resampling
python pyimg2six.py -c 200x200+50+50 photo.png      # crop region

# Color & quality
python pyimg2six.py --colors 64 photo.png           # 64 colors
python pyimg2six.py -e photo.png                    # monochrome
python pyimg2six.py -i photo.png                    # inverse (negative)
python pyimg2six.py -B "#ffffff" photo.png          # white background
python pyimg2six.py -q high photo.png               # high quality quantize

# Encoding strategy
python pyimg2six.py -E fast animation.gif           # skip RLE (faster)
python pyimg2six.py -E size -o out.six photo.png    # smaller file

# Terminal compatibility
python pyimg2six.py -P photo.png                    # tmux/screen passthrough
python pyimg2six.py -d bayer photo.png              # Bayer ordered dithering
python pyimg2six.py -d fs photo.png                 # Floyd-Steinberg dithering
python pyimg2six.py --no-resize photo.png           # keep original resolution

# Combined
python pyimg2six.py -w 640 --colors 128 -r lanczos3 -o output.six photo.png
```

### Command-Line Reference

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image` | Image file path (positional) | required |
| `--no-anim` | Static mode, show first frame only | off |
| `-d MODE` | Dithering: none/bayer/fs | none |
| `--colors N` | Palette colors (2-256) | 256 |
| `--max-width COLS` | Max terminal columns | terminal width |
| `--no-resize` | Keep original resolution, no scaling | off |
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

---

## pysix2png — Sixel to PNG

### Features

- **Pure Python Sixel decoder** — State machine based on libsixel 1.8.7's `fromsixel.c`, no C dependencies
- **Standard input/output support** — Reads from file or stdin, writes to file or stdout
- **Full color support** — RGB and HLS color definitions, 256-color palette
- **Raster attribute handling** — Correctly parses Pan/Pad/Ph/Pv aspect ratio and dimension attributes
- **Repeat & RLE decoding** — Handles Sixel repeat introducer (`!Pn`) and all control sequences

### Quick Start

```bash
# Convert a Sixel file to PNG
python pysix2png.py -i input.sixel -o output.png

# Read from stdin, write to stdout (pipe-friendly)
cat input.sixel | python pysix2png.py > output.png

# Show version
python pysix2png.py -V
```

### Command-Line Reference

| Parameter | Description | Default |
|-----------|-------------|---------|
| `-i, --input` | Input Sixel file (or `-` for stdin) | stdin |
| `-o, --output` | Output PNG file (or `-` for stdout) | stdout |
| `-V, --version` | Show version info | -- |
| `-H, --help` | Show help | -- |

---

## pysixview — Adaptive Viewer

Auto-detects terminal width, scales wide Sixel images to fit, passes through narrow ones unchanged.

```bash
# View a .six file (auto-scales if wider than terminal)
python pysixview.py image.six

# Specify max pixel width manually
python pysixview.py -w 800 image.six

# Show image dimensions
python pysixview.py -i image.six

# Adjust multiplier and save
python pysixview.py -m 8 --save image.six
```

| Parameter | Description | Default |
|-----------|-------------|---------|
| `input` | Sixel file path (positional) | required |
| `-w PX` | Max pixel width | terminal columns × multiplier |
| `-m N` | Terminal column multiplier | 8 (saved in ~/.sixview.conf) |
| `--save` | Save multiplier to config | off |
| `-i, --info` | Show image dimensions and exit | off |
| `--no-resize` | Pass through without scaling | off |

---

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
| RLE compression | Output -92% | DEC VT Sixel `!COUNT CHAR` (threshold=3) |
| String caching | 1.1x | Pre-built encoded strings for colors and run lengths |
| Raster attributes | Correct ratio | `"1;1;W;H` eliminates need for char_aspect hack |
| FS hash cache | O(1) lookup | 15-bit cachetable for Floyd-Steinberg color matching |
| Auto-disable FS | Skip when lossless | 15-bit hash detects low-color images, skips diffusion |
| GIF palette cache | Skip re-quantize | Reuse first frame's palette for subsequent frames |
| Sampling quantization | Large image speed | Downsample for MEDIANCUT when pixels > 1M |

## Project Structure

```
pysixel/
├── pyimg2six.py               # Image → Sixel encoder (img2sixel equivalent)
├── pysix2png.py               # Sixel → PNG decoder (sixel2png equivalent)
├── pysixview.py                 # Adaptive Sixel viewer (auto-scale to terminal)
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
