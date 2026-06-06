"""在终端中以 Sixel 格式显示图片（需 Windows Terminal 或其他支持 Sixel 的终端）"""
"""gif仅显示第一帧"""
import sys
from pathlib import Path
from PIL import Image

# 终端最大宽度（字符数），Sixel 每像素 1 列，需根据终端调整
MAX_WIDTH = 80
# 每个字符约 8 像素宽（等宽字体），所以最大像素宽度
MAX_PX_WIDTH = MAX_WIDTH * 8


def rgb_to_sixel_color(idx, r, g, b):
    return f"#{idx};2;{r * 100 // 255};{g * 100 // 255};{b * 100 // 255}"


def quantize(img, max_colors=256):
    """将图片量化为有限调色板"""
    return img.convert("RGB").quantize(max_colors, method=Image.Quantize.MEDIANCUT)


def encode_sixel(img):
    """将 PIL Image 编码为 Sixel 字符串"""
    # 缩放，补偿终端字符宽高比（约 1:2）
    w, h = img.size
    # 终端每个字符约 8px 宽、16px 高，字符宽高比约 0.5
    char_aspect = 0.5
    if w > MAX_PX_WIDTH:
        ratio = MAX_PX_WIDTH / w
        w, h = MAX_PX_WIDTH, int(h * ratio)
    # 补偿：让图片在终端中看起来不变形
    h = int(h * char_aspect)
    img = img.resize((w, h), Image.Resampling.LANCZOS)

    img = quantize(img)
    palette = img.getpalette()
    pixels = img.load()
    w, h = img.size

    num_colors = len(palette) // 3
    colors = {}
    for i in range(num_colors):
        r, g, b = palette[i * 3], palette[i * 3 + 1], palette[i * 3 + 2]
        colors[i] = (r, g, b)

    lines = []
    lines.append("\x1bP0;0;0q")  # DCS 开始

    # 写入使用的颜色定义
    used_colors = set()
    for y in range(h):
        for x in range(w):
            used_colors.add(pixels[x, y])

    for idx in sorted(used_colors):
        r, g, b = colors[idx]
        lines.append(f"#{idx};2;{r * 100 // 255};{g * 100 // 255};{b * 100 // 255}")

    # 逐 sixel 行编码（每行 6 个像素高）
    for sy in range(0, h, 6):
        # 收集本 sixel 行中出现的颜色
        row_colors = set()
        for y in range(sy, min(sy + 6, h)):
            for x in range(w):
                row_colors.add(pixels[x, y])

        for color_idx in sorted(row_colors):
            lines.append(f"#{color_idx}")
            for x in range(w):
                bits = 0
                for bit in range(6):
                    y = sy + bit
                    if y < h and pixels[x, y] == color_idx:
                        bits |= 1 << bit
                lines.append(chr(0x3F + bits))
            lines.append("$")  # 回到行首

        # 去掉最后一个 $，换行
        if lines[-1] == "$":
            lines[-1] = "-"
        else:
            lines.append("-")

    lines.append("\x1b\\")  # ST 结束
    return "".join(lines)


def main():
    if len(sys.argv) < 2:
        theme_dir = Path.home() / "AppData" / "Roaming" / "Typora" / "themes" / "onelight"
        img_dir = theme_dir / "img"
        if img_dir.exists():
            images = list(img_dir.glob("*"))
            if images:
                path = images[0]
            else:
                print("未找到图片")
                sys.exit(1)
        else:
            print(f"用法: {sys.argv[0]} <图片路径>")
            sys.exit(1)
    else:
        path = Path(sys.argv[1])

    if not path.exists():
        print(f"文件不存在: {path}")
        sys.exit(1)

    img = Image.open(path)
    sixel_data = encode_sixel(img)
    # 调试信息输出到 stderr，不干扰 sixel 数据流
    print(f"[{path.name}] {img.size[0]}x{img.size[1]} -> Sixel ({len(sixel_data)} bytes)", file=sys.stderr)
    sys.stdout.write(sixel_data)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
