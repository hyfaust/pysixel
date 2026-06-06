# Nuitka 编译指南

> 适用版本：Nuitka 4.1.2 / Python 3.13 / Windows 11  
> 最后更新：2026-06-06

---

## 1. Nuitka 简介

Nuitka 是一个 Python 编译器，将 Python 源码编译为 C 代码，再通过 C 编译器（如 GCC、MSVC、Zig）生成原生可执行文件或扩展模块。

**与 PyInstaller 的区别**：

| 特性 | Nuitka | PyInstaller |
|------|--------|-------------|
| 原理 | 编译为 C → 机器码 | 打包 Python 字节码 + 解释器 |
| 运行速度 | 快 2-5x | 与直接运行相同 |
| 启动速度 | 快（无解释器启动） | 慢（需解压/启动解释器） |
| 体积 | 较小（可裁剪） | 较大（包含完整解释器） |
| 反编译难度 | 高（机器码） | 低（字节码可还原） |
| 编译时间 | 长（需 C 编译） | 短（仅打包） |

---

## 2. 安装

### 2.1 安装 Nuitka

```bash
pip install nuitka
```

### 2.2 C 编译器

Nuitka 依赖 C 编译器将生成的 C 代码编译为机器码。首次运行时会自动下载 `ziglang`：

```bash
python -m nuitka --version
# 首次运行会提示下载 ziglang，选择 Yes 即可
# 下载位置：~/.local/Nuitka/ 或 AppData/Local/Nuitka/
```

**支持的编译器**（Windows）：

| 编译器 | 获取方式 | 说明 |
|--------|----------|------|
| Zig | 自动下载（推荐） | Nuitka 默认使用，无需手动安装 |
| MinGW (winlibs-gcc) | 手动安装 | 需要精确版本匹配 |
| MSVC (Visual Studio) | 安装 VS Build Tools | 系统级安装，较重 |

---

## 3. 编译模式

### 3.1 Standalone 模式（推荐）

生成包含所有依赖的**文件夹**，可独立运行，不依赖系统 Python。

```bash
python -m nuitka --standalone your_script.py
```

输出结构：
```
your_script.dist/
├── your_script.build/     # 编译中间文件（可删除）
└── your_script.dist/      # 运行目录
    ├── your_script.exe    # 主程序
    ├── python313.dll      # Python 运行时
    ├── PIL/               # 依赖库
    └── ...                # 其他依赖
```

**优点**：启动快，运行快  
**缺点**：分发时需打包整个文件夹

### 3.2 Onefile 模式

将所有依赖打包为**单个 exe 文件**。

```bash
python -m nuitka --onefile your_script.py
```

**优点**：单文件分发方便  
**缺点**：首次启动需解压到临时目录，启动略慢；文件体积更大

### 3.3 模块模式

编译为 Python 扩展模块（`.pyd` / `.so`），可在 Python 中 `import`。

```bash
python -m nuitka --module your_module.py
```

---

## 4. 常用选项速查

### 基本选项

| 选项 | 说明 |
|------|------|
| `--standalone` | 独立模式，输出包含所有依赖的文件夹 |
| `--onefile` | 单文件模式 |
| `--module` | 编译为扩展模块 |
| `--output-filename=xxx.exe` | 指定输出文件名 |
| `--output-dir=路径` | 指定输出目录 |

### 依赖控制

| 选项 | 说明 |
|------|------|
| `--include-package=PIL` | 强制包含某个包（处理隐式导入） |
| `--include-module=module` | 包含单个模块 |
| `--include-data-files=src=dst` | 打包数据文件 |
| `--include-data-dir=src=dst` | 打包整个数据目录 |
| `--noinclude-custom-mode=disable` | 禁用自动包含检测 |

### Windows 专用

| 选项 | 说明 |
|------|------|
| `--windows-console-mode=disable` | 隐藏控制台窗口（GUI 程序用） |
| `--windows-console-mode=force` | 强制显示控制台 |
| `--windows-icon-from-ico=icon.ico` | 设置 exe 图标 |
| `--windows-uac-admin` | 请求管理员权限 |

### 优化选项

| 选项 | 说明 |
|------|------|
| `--enable-optimization` | 启用优化（实验性） |
| `--follow-imports` | 编译所有导入的模块 |
| `--assume-yes-for-downloads` | 非交互模式，自动下载依赖 |

### 调试选项

| 选项 | 说明 |
|------|------|
| `--verbose` | 详细编译日志 |
| `--debug` | 调试模式（保留断言等） |
| `--show-progress` | 显示编译进度 |
| `--show-scons` | 显示 C 编译过程 |

---

## 5. 实战：编译 sixel-show.py

### 5.1 基本编译

```bash
python -m nuitka --standalone --assume-yes-for-downloads \
    --output-filename=sixel-show.exe \
    --output-dir=./sixel-show.dist \
    --include-package=PIL \
    sixel-show.py
```

**逐项解释**：

1. `--standalone` — 生成可独立运行的目录（不依赖系统 Python）
2. `--assume-yes-for-downloads` — 自动下载 ziglang C 编译器（首次需要，约 100MB）
3. `--output-filename=sixel-show.exe` — 指定输出 exe 文件名
4. `--output-dir=./sixel-show.dist` — 指定输出目录
5. `--include-package=PIL` — 显式包含 Pillow 库（Nuitka 自动检测可能遗漏部分子模块）

### 5.2 编译输出

```
Nuitka: Starting Python compilation with:
  Version '4.1.2' on Python 3.13
...
Nuitka-Scons: Backend C compiler: zig.exe 0.16.0
Nuitka-Scons: Backend C linking with 113 files
...
Nuitka: Successfully created 'sixel-show.dist/sixel-show.dist/sixel-show.exe'.
```

最终产物：
```
sixel-show.dist/
└── sixel-show.dist/
    ├── sixel-show.exe    # 主程序 (~14.8MB)
    ├── python313.dll     # Python 运行时
    ├── PIL/              # Pillow 库
    └── _internal/        # Nuitka 运行时
```

### 5.3 添加 numpy 依赖

优化后的 `sixel-show.py` 使用了 numpy，需要额外包含。numpy 包含大量测试模块（mypy、numba、pytest 等），会导致编译超时。必须使用 `--nofollow-import-to` 排除：

```bash
python -m nuitka --standalone --assume-yes-for-downloads \
    --output-filename=sixel-show.exe \
    --output-dir=./sixel-show.dist \
    --include-package=PIL \
    --include-package=numpy \
    --nofollow-import-to=mypy,numba,pytest,setuptools,pandas,matplotlib,scipy,numpy._core.tests,numpy.lib.tests,numpy.random.tests,numpy.typing.tests,numpy.tests,numpy.f2py.tests,numpy.linalg.tests,numpy.ma.tests,numpy.polynomial.tests,numpy.fft.tests,numpy.distutils,numpy.testing \
    --noinclude-numba-mode=nofollow \
    --jobs=4 \
    sixel-show.py
```

**编译产物**：exe 约 29.9MB（含 58 个 numpy/mkl DLL），编译耗时约 395 秒。

**性能注意**：含 numpy 的 exe 启动反而比 Python 直接调用**慢 1.84x**（365ms vs 199ms），原因是 standalone 模式需要加载大量 numpy/mkl DLL。对于 numpy 重度依赖的脚本，直接用 `python sixel-show.py` 是最优选择。详见 `benchmark-report.md` Benchmark C。

### 5.4 创建 BAT wrapper

```bat
@echo off
python "%~dp0sixel-show.py" %*
```

Benchmark 显示 BAT wrapper 与直接 Python 调用无显著性能差异（< 4ms）。

---

## 6. 常见问题

### Q: 编译报错 "module not found"

**原因**：Nuitka 未能自动检测到某些隐式导入的模块。  
**解决**：使用 `--include-package=包名` 或 `--include-module=模块名` 显式包含。

### Q: 编译后 exe 运行报错

**原因**：缺少数据文件或动态链接库。  
**解决**：
1. 检查是否需要 `--include-data-files` 或 `--include-data-dir`
2. 使用 `--verbose` 查看详细的导入链
3. 确认所有子包都已通过 `--include-package` 包含

### Q: 编译时间很长

**原因**：Nuitka 需要将 Python 编译为 C 再编译为机器码，涉及大量 C 文件。  
**解决**：
1. 首次编译后，Nuitka 会缓存中间结果，后续编译会更快
2. 使用 `--jobs=N` 指定并行编译线程数
3. 使用 `--noinclude-custom-mode=disable` 跳过不需要的模块

### Q: exe 体积太大

**解决**：
1. 使用 `--onefile` 模式（但启动略慢）
2. 使用 `--nofollow-import-to=模块名` 排除不需要的模块
3. 使用 UPX 压缩 exe：`--enable-plugin=upx`

### Q: ziglang 下载失败

**解决**：
1. 检查网络连接
2. 手动下载 zig 并添加到 PATH
3. 使用 `--mingw64` 指定 MinGW 编译器

---

## 7. 进阶用法

### 7.1 跨平台编译

Nuitka 支持通过 `--target-platform` 指定目标平台，但交叉编译支持有限。建议在目标平台上直接编译。

### 7.2 商业项目

Nuitka 有商业版本（Nuitka Commercial），提供：
- 更强的代码保护（混淆、加密）
- 更小的体积
- 更快的编译
- 优先技术支持

### 7.3 与 CI/CD 集成

```yaml
# GitHub Actions 示例
- name: Build with Nuitka
  run: |
    pip install nuitka
    python -m nuitka --standalone --assume-yes-for-downloads \
        --output-filename=myapp.exe \
        --include-package=PIL \
        main.py
```

### 7.4 性能对比参考

本项目的 Benchmark 数据（sixel-show.py，含 Pillow + numpy）：

| 方式 | 启动 + 执行 (ms) | 相对速度 |
|------|-----------------|----------|
| Nuitka exe (standalone) | 110 | 0.19x |
| Python 直接调用 | 594 | 1.00x |
| BAT wrapper | 596 | 0.99x |

Nuitka 编译后启动速度提升约 **5.3 倍**，主要来自消除 Python 解释器启动和模块导入开销。

---

## 8. 参考资源

- [Nuitka 官方文档](https://nuitka.net/doc/user-documentation.html)
- [Nuitka GitHub](https://github.com/Nuitka/Nuitka)
- [Nuitka Options 完整列表](https://nuitka.net/doc/user-documentation.html#complete-options-list)
