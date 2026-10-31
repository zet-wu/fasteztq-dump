# fasteztq-dump

[English](README_en.md)

更快的 SRA 转换为 gzip FASTQ 的命令行工具，支持多线程。仅支持由 FASTQ 打包得到的 Normalized、Lite SRA 输入，每个 spot 含一条或两条非空生物学读段的布局。

## 构建

支持 Linux x86-64。构建需要 GCC/G++、GNU Make、CMake 3.16+、pkg-config，以及 libdeflate 1.14+ 和 ISA-L 2.31.0+ 开发包。正确性测试使用 Python 3.9+ 标准库。

Debian/Ubuntu：

```sh
sudo apt install build-essential cmake pkg-config libdeflate-dev libisal-dev python3 git
```

Red Hat 系（以 9 系列为例）：先按发行版启用 [CRB 和 EPEL](https://www.redhat.com/en/blog/install-epel-linux)。

CentOS Stream 9：

```sh
sudo dnf install dnf-plugins-core
sudo dnf config-manager --set-enabled crb
sudo dnf install epel-release epel-next-release
```

RHEL 9：

```sh
sudo subscription-manager repos --enable codeready-builder-for-rhel-9-x86_64-rpms
sudo dnf install https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm
```

然后安装开发依赖；Fedora 可直接执行此命令：

```sh
sudo dnf install gcc gcc-c++ make cmake pkgconf-pkg-config libdeflate-devel isa-l-devel python3 git
```

ncbi-vdb 通过 Git 子模块固定在 3.2.1 对应提交。获取仓库时使用 `git clone --recurse-submodules`；已有工作副本可执行：

```sh
git submodule update --init --recursive
make JOBS=4
```

生成的程序为 `build/release/fasteztq-dump`。ncbi-vdb 从子模块源码编译并静态链接；libdeflate 和 ISA-L 通过 pkg-config 查找，使用安装环境提供的库。安装到自定义位置的压缩库可通过 `PKG_CONFIG_PATH` 指定，运行时共享库搜索路径按安装环境配置。

`CC`、`CXX`、`CFLAGS`、`CPPFLAGS`、`LDFLAGS` 和 `VDB_FLAGS` 用于指定编译配置，`BUILD` 指定构建目录，`JOBS` 指定依赖库的构建并行度。不同配置使用独立构建目录：

```sh
make BUILD=build/debug CFLAGS='-O0 -g' VDB_FLAGS='-O0 -g' JOBS=4
make install PREFIX="$HOME/.local"
```

安装支持 `PREFIX`、`BINDIR` 和 `DESTDIR`。

## 使用

```sh
build/release/fasteztq-dump reads.sra -O fastq -e 4 --level 6
```

| 参数 | 含义 |
|---|---|
| `-O`、`--outdir` | 输出目录，默认当前目录 |
| `-e`、`--threads` | 线程数，默认 8 |
| `-l`、`--level` | 压缩级别，libdeflate 为 0–12，默认 6；ISA-L 为 0-3，默认 1 |
| `--compressor` | `libdeflate` 或 `isal` |
| `-h`、`--help` | 显示帮助 |
| `-v`、`--version` | 显示程序和解码库版本 |

输出行为与 [sra-tools](https://github.com/ncbi/sra-tools) 中的 `fasterq-dump --split-files`一致。单读段 spot 写入 `reads.fastq.gz`，双读段分别写入 `reads_1.fastq.gz`、`reads_2.fastq.gz`。混合布局按各 spot 的读段数量分流，各流保留 spot 顺序。输出名取输入路径的文件名，并去掉 `.sra` 或 `.sralite` 后缀。

FASTQ 头部和加号行包含输入名称、spot id 和读长。输入提供 NAME 列时加入该值，空 NAME 使用 spot id。质量由 VDB schema 解码，以 Phred+33 表示，Q≥93 编码为 `~`。Lite 的质量恢复遵循其 schema。

## 测试

```sh
make check JOBS=4
```

测试现场生成小型 SRA 归档，并将解压后的 FASTQ 与测试记录定义的预期内容比较。覆盖单读段、双读段、混合布局、名称、质量边界、Lite 质量恢复、跨块顺序、压缩级别、索引映射，以及异常输入和写入失败清理。测试数据和结果存放在 Python 临时目录中，位置可通过 `TMPDIR` 指定，测试结束后清理。

模块说明见 [ARCHITECTURE.md](ARCHITECTURE.md)。
