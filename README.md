# fasteztq-dump

独立的本地 SRA → gzip FASTQ 转换器，输出语义对应 SRA Toolkit 3.2.1 的 `fasterq-dump --split-files`。支持无参考依赖的 Normalized 和 Lite 输入、每个 spot 一条或两条非空生物学读段、定长与可变读长。质量由输入的 VDB schema 解码。

## 构建与使用

需要 Linux x86-64、GCC/G++、GNU Make 4.3+、CMake、NASM、curl 和 Python 3.12+。首次构建下载官方 ncbi-vdb 3.2.1、libdeflate 1.22 与 ISA-L 2.31.0 源码，三者静态链接；默认 GCC 选项为 `-O3 -DNDEBUG`，压缩库按运行时 CPU 能力选择实现。开发校验另需 libdeflate 共享库，以及 `/public/bio-informatic-software/sratoolkit.3.2.1-ubuntu64/bin/` 下的 SRA Toolkit 3.2.1。

```sh
make -j2
build/gcc/fasteztq-dump /absolute/path/RUN.sra -e 8 -O /output/directory --level 6
```

`-e` 包含主线程：1–8 线程时主线程同时处理一个计算槽位，9–64 线程时主线程专门顺序写出，其余 N−1 个线程解码、格式化与压缩。缓存和有序队列的槽位数量由线程数决定，缓冲随当前块的读段长度增长并复用；内存使用由分块流水线、背压和共享只读索引控制。开发测试独立观测 RSS。每个块立即压缩为 gzip member，按 spot 顺序写出，输出可以由支持标准串联 gzip 的工具读取。

单读段 spot 写入 `RUN.fastq.gz`；双读段分别写入 `RUN_1.fastq.gz` 与 `RUN_2.fastq.gz`。文件名中的 `.sra`/`.sralite` 仅用于输出命名，解码方式由归档内部结构决定。默认头及加号行保留 accession、spot id、NAME（可用时）与读长。质量字符按原工具规则将 Q≥93 表示为 `~`。`-l/--level 0..12` 选择 libdeflate 压缩级别，默认 6，对应 `fastq-dump --gzip` 所用 zlib 6 的相近档位。`--compressor isal --level 0..3` 可显式选择 ISA-L 的速度档位；ISA-L 0 是其最快压缩档位，libdeflate 0 为存储模式。不同库的级别与压缩率对照见 [压缩实验](reports/compression-comparison.md)。

参考/比对表、技术读段、空读段及超过两条读段的布局会明确报错。缓冲按当前块的读段长度按需分配。已有结果文件会保留。结果先以隐藏临时文件写出，在所有工作线程结束并成功关闭输出后发布；失败会清理本次临时结果。

可以通过 `CC`、`CXX`、`CFLAGS`、`CPPFLAGS`、`LDFLAGS`、`VDB_FLAGS`、`BUILD` 覆盖构建配置。`JOBS` 控制每项依赖构建的并行度，默认 16；`make -j2` 同时构建两个依赖时合计最多约 32 个编译任务。不同编译器使用独立 `BUILD` 目录。

## 开发验证

```sh
python3 scripts/benchmark.py --ids T02 T08 T12 T16 --threads 8 --repeats 1 --compressor libdeflate --level 6 \
  --builds gcc=build/gcc/fasteztq-dump --report reports/local-benchmark.jsonl
```

验收使用显式 `--compressor libdeflate --level 6`。完整矩阵覆盖 20 个输入、8/16 线程、三次测量和 GCC/AOCC 构建。可通过 `--builds gcc=... aocc=...` 指定独立构建的可执行文件。计时覆盖转换进程从启动到退出；原工具输出 FASTQ，新工具输出 gzip FASTQ。每次运行预读输入形成热页缓存，交替执行顺序。独立校验子进程在计时结束后逐成员解压所有 gzip 内容并逐字节比较，保留字节数、SHA-256、记录数、流映射、CPU 时间、OS 峰值 RSS 和进程树采样。全部转换输出及临时文件位于 `/dev/shm/fasteztq-bench/`，每组校验后清理。

正式转换路径执行解码边界、读段布局、质量长度和输出错误检查。开发一致性比较由 `scripts/benchmark.py` 执行。测试输入及来源见 `tests/TEST_DATA.md`、`tests/metadata/verification.json`；需求与验收标准见 `DEVELOPMENT_PLAN.md`。

```sh
make check
make -j2 BUILD=build/aocc CC=/opt/AMD/aocc-compiler-5.0.0/bin/clang \
  CXX=/opt/AMD/aocc-compiler-5.0.0/bin/clang++ \
  CFLAGS='-O3 -DNDEBUG -march=znver2' VDB_FLAGS='-march=znver2'
```

AOCC 示例针对本机 AMD EPYC 7502；编译器和架构选项按目标机器显式指定。`make check` 在 `/dev/shm` 创建小型 SRA，验证混合布局、名称、质量边界、截断和写入失败清理，同时检查开发校验器对后续 gzip 成员损坏的检测能力。

模块职责和边界见 [ARCHITECTURE.md](ARCHITECTURE.md)。实验日志及最终性能表位于 [reports](reports/README.md)。

## 当前验收结果

基线 fasterq-dump 3.2.1 输出未压缩 FASTQ，新工具直接输出 libdeflate 6 级 gzip FASTQ。所有正式计时均使用完整输入、8/16 线程各三轮，计时后独立逐字节比对全部输出。

来自 RNA-seq 样品清单的 6.06、10.00、19.92 GB 三个 Normalized 大样本，GCC 构建共 36 次转换和 18 次全文件比较全部通过，累计比较 1.35 TB，最高 RSS 1756.9 MiB。8 线程速度比分别为 0.609×、0.532×、0.464×，16 线程分别为 0.886×、0.709×、0.633×（原版耗时 / 新工具耗时）。三个大样本在两档线程数下均慢于未压缩基线，当前默认压缩配置的速度目标在这些大样本上仍未达成。详见 [大样本报告](reports/large-samples.md)。

20 个约 0.027–1.20 GB 输入的 GCC/AOCC 矩阵保存了 360 次转换、240 次完整比较，全部逐字节一致，峰值 RSS 812.9 MiB。在这一测试矩阵中，16 线程两种构建对全部 20 个输入均加速，累计速度比约 1.71×；8 线程累计耗时基本持平，GCC/AOCC 分别有 6/8 个输入回退。AOCC 在该矩阵的总体收益接近 GCC，默认构建采用 GCC。具体结果与测量源码版本见 [20 输入矩阵](reports/final-results.md)。
