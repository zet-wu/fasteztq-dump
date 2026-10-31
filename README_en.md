# fasteztq-dump

[简体中文](README.md)

A faster command-line tool for converting SRA to gzip FASTQ, with multithreading support. Supports Normalized and Lite SRA archives created from FASTQ, with one or two nonempty biological reads per spot.

## Build

Supports Linux x86-64. Building requires GCC/G++, GNU Make, CMake 3.16+, pkg-config, and the development packages for libdeflate 1.14+ and ISA-L 2.31.0+. Correctness tests use the Python 3.9+ standard library.

Debian/Ubuntu:

```sh
sudo apt install build-essential cmake pkg-config libdeflate-dev libisal-dev python3 git
```

Red Hat family (version 9 examples below): first enable [CRB and EPEL](https://www.redhat.com/en/blog/install-epel-linux) for your distribution.

CentOS Stream 9:

```sh
sudo dnf install dnf-plugins-core
sudo dnf config-manager --set-enabled crb
sudo dnf install epel-release epel-next-release
```

RHEL 9:

```sh
sudo subscription-manager repos --enable codeready-builder-for-rhel-9-x86_64-rpms
sudo dnf install https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm
```

Then install the development dependencies. On Fedora, run this command directly:

```sh
sudo dnf install gcc gcc-c++ make cmake pkgconf-pkg-config libdeflate-devel isa-l-devel python3 git
```

ncbi-vdb is pinned to the commit for version 3.2.1 through a Git submodule. Use `git clone --recurse-submodules` when cloning the repository. For an existing checkout, run:

```sh
git submodule update --init --recursive
make JOBS=4
```

The executable is built at `build/release/fasteztq-dump`. ncbi-vdb is compiled from the submodule source and linked statically. libdeflate and ISA-L are located through pkg-config, using the libraries provided by your installation. For compression libraries installed in custom locations, set `PKG_CONFIG_PATH` and configure the runtime shared-library search path for your environment.

Use `CC`, `CXX`, `CFLAGS`, `CPPFLAGS`, `LDFLAGS`, and `VDB_FLAGS` to configure compilation, `BUILD` to select the build directory, and `JOBS` to set the parallelism used to build the dependency library. Use separate build directories for different configurations:

```sh
make BUILD=build/debug CFLAGS='-O0 -g' VDB_FLAGS='-O0 -g' JOBS=4
make install PREFIX="$HOME/.local"
```

Installation supports `PREFIX`, `BINDIR`, and `DESTDIR`.

## Usage

```sh
build/release/fasteztq-dump reads.sra -O fastq -e 4 --level 6
```

| Option | Description |
|---|---|
| `-O`, `--outdir` | Output directory; defaults to the current directory |
| `-e`, `--threads` | Thread count; defaults to 8 |
| `-l`, `--level` | Compression level: 0–12 for libdeflate, default 6; 0–3 for ISA-L, default 1 |
| `--compressor` | `libdeflate` or `isal` |
| `-h`, `--help` | Show help |
| `-v`, `--version` | Show the program and decoder library versions |

Output behavior matches `fasterq-dump --split-files` from [sra-tools](https://github.com/ncbi/sra-tools). Spots with one read are written to `reads.fastq.gz`; spots with two reads are written to `reads_1.fastq.gz` and `reads_2.fastq.gz`. Mixed layouts are routed according to the number of reads in each spot, preserving spot order within each stream. Output names use the input filename with the `.sra` or `.sralite` suffix removed.

FASTQ headers and plus lines contain the input name, spot ID, and read length. When the input provides a NAME column, its value is included; an empty NAME uses the spot ID. Quality scores are decoded by the VDB schema and represented as Phred+33, with Q≥93 encoded as `~`. Lite quality scores are reconstructed according to the archive's schema.

## Tests

```sh
make check JOBS=4
```

Tests generate small SRA archives locally and compare the decompressed FASTQ with the expected content defined by the test records. Coverage includes single-read, paired-read, and mixed layouts; names; quality boundaries; Lite quality reconstruction; ordering across blocks; compression levels; index mappings; and cleanup after invalid input or write failures. Test data and results are stored in Python temporary directories, whose location can be set through `TMPDIR`, and cleaned up after the tests.

See [ARCHITECTURE.md](ARCHITECTURE.md) for module descriptions.
