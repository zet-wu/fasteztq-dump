# 大样本转换与内存限制移除

## 原有 8 线程回退与大小

原 20 输入矩阵中，GCC 在 8 线程的 6 个回退输入恰为 SRA 最大的 6 个。SRA 字节数与速度比的 Spearman 相关系数为 -0.947。速度比定义为原版耗时 / 新程序耗时，大于 1 表示新程序更快。

| 输入 | 格式 | SRA GB | 速度比 |
|---|---|---:|---:|
| T19 / ERR3317432 | Lite | 0.669 | 0.825× |
| T15 / SRR27205627 | Normalized | 0.714 | 0.698× |
| T09 / SRR29087938 | Lite | 0.720 | 0.949× |
| T01 / SRR4407952 | Normalized | 0.774 | 0.795× |
| T10 / SRR14492484 | Lite | 1.091 | 0.910× |
| T20 / SRR14035937 | Lite | 1.199 | 0.663× |

AOCC 的 8 线程回退还包括 T04、T14，速度比分别约 0.993×、0.995×，两者接近持平，应与明显回退分开看。

这是所选输入中的相关性。输入格式、质量值、读长、NAME 索引及输出量也同时变化，不能仅凭相关性断定 SRA 大小是原因。小文件的速度比受到启动开销影响；完整大文件测试用于检查持续吞吐。

## 样品与方法

从 `/home/wangzeyu/wangzeyu-nvme1/coexpress-evolution/rnaseq/cohorts/` 样品清单选取三个较大 Normalized SRA，保留原始质量值。6 GB 样本复用既有缓存；10/20 GB 样本下载至当前项目 `tests/data/large/`，原始文件均保留。

| 输入 | 物种 | SRA GB | spot 数 | 抽样读长 |
|---|---|---:|---:|---|
| SRR31783948 | Zea mays | 6.056 | 94,543,049 | 101 |
| SRR30352331 | Brachypodium distachyon | 9.996 | 76,322,455 | 100 |
| SRR9158204 | Oryza sativa | 19.925 | 141,298,604 | 151 |

下载使用 `sra-pub-run-odp.s3.dualstack.us-east-1.amazonaws.com`，aria2 每文件 16 连接；AAAA-only 局部解析器与 `--interface=::` 保证 IPv6，实际 IPv6 TCP 连接已记录。下载后按来源元数据校验大小、MD5，并对全部输入执行 VDB 完整验证及布局抽样。下载日志、命令及连接证据见 [下载记录](large-samples-logs/)。

使用 GCC 12.2.0、`-O3 -DNDEBUG`，默认 libdeflate 6。每个样本在 8/16 线程各重复三轮，串行运行并交替原版/新程序顺序。每次计时前预读完整输入；输出和临时文件均写入 `/dev/shm`，逐组比较后清理。计时覆盖启动到退出。原版 fasterq-dump 3.2.1 输出未压缩 FASTQ，新程序直接输出 gzip FASTQ，因此这是两种实际工作流的耗时比较，不能视为同压缩任务比较。

RSS 取 OS 峰值及 20 ms 完整进程树采样的最大值。原版 8/16 线程参数按 16/32 CPU token 计，新程序按 8/16 计；BLAS/OpenMP 线程为 1。开发测试预估 tmpfs 峰值并检查 252 GiB 工作区预算，生产程序按需使用内存。

## 完整大样本结果

| 样本 | 线程 | 原版 s | 新程序 s | 速度比 | 新 RSS MiB | 原版 RSS MiB |
|---|---:|---:|---:|---:|---:|---:|
| SRR31783948 | 8 | 75.369 | 123.767 | 0.609× | 386.7 | 748.8 |
| SRR31783948 | 16 | 55.881 | 63.054 | 0.886× | 635.5 | 1397.4 |
| SRR30352331 | 8 | 86.798 | 163.211 | 0.532× | 1496.0 | 1801.4 |
| SRR30352331 | 16 | 58.335 | 82.308 | 0.709× | 1756.9 | 2409.0 |
| SRR9158204 | 8 | 143.038 | 308.221 | 0.464× | 353.3 | 1054.0 |
| SRR9158204 | 16 | 100.560 | 158.855 | 0.633× | 527.1 | 1948.5 |

表中耗时为三轮中位数；每轮范围、CPU 占用、输出字节数和 tmpfs 使用增量见 [CSV](large-samples-results.csv)，逐次测量及完整比较见 [JSONL](large-level6.jsonl)。

共 36 次转换、18 次完整比较、36 个输出流，逐字节一致并验证全部 gzip 成员 CRC/ISIZE；累计比较 1.350 TB。新程序观测最大 RSS 为 1756.9 MiB。

## 结果解释

8 线程下，3/3 个大样本相对未压缩基线回退；三样本中位耗时合计的速度比为 0.513×。
16 线程下，3/3 个大样本相对未压缩基线回退；三样本中位耗时合计的速度比为 0.706×。

原 20 个约 0.027–1.20 GB 输入的 16 线程结果属于该测试矩阵；本次大样本结果应独立报告。新程序计时包含默认 6 级压缩，源文件大小与质量分布、索引结构、解码量和压缩工作量同时变化，本测试不能单独量化每个因素的因果贡献。

| 样本 | SRA GB | 解压后 FASTQ GB | gzip GB |
|---|---:|---:|---:|
| SRR31783948 | 6.056 | 65.934 | 8.667 |
| SRR30352331 | 9.996 | 49.718 | 12.833 |
| SRR9158204 | 19.925 | 109.324 | 23.458 |

## 运行时内存行为

生产程序通过固定数量的工作槽位、16384 spot 分块、有序背压、缓冲复用和只读索引共享控制内存增长。缓冲按当前块需求扩容，实际占用取决于线程数、读长、解码数据块和输入索引。实际分配失败仍报告错误并清理临时输出。ISA-L 的单次输入/输出使用其接口规定的 32 位长度范围。

本次移除了 `RLIMIT_AS`、`--memory-mib` 和每流 64 MiB 固定上限；开发脚本独立记录 RSS 是否达到 2 GiB 优化目标，完整运行及比对保留超出目标的测量。实际运行的 `/proc/PID/limits` 证据见 [运行限制](large-samples-logs/runtime-limits.json)。GCC/AOCC 边界测试和超过 64 MiB 的完整 gzip 成员测试均通过。

10 GB 样本 16 线程的一次运行快照中，虚拟地址空间为 2.725 GiB，而同一时刻 RSS 为 604.3 MiB（这是中途快照，完整运行峰值见结果表）。其地址空间已超过旧的 2048 MiB 最大设置；地址空间上限与实际驻留内存并不等价。证据见 [大索引快照](large-samples-logs/large-index-t16-memory.json)。

10 GB 样本的 `tbl/SEQUENCE/idx/skey` 大小为 1,165,766,820 字节（约 1111.8 MiB）；20 GB 样本没有对应的 `skey` 索引。这与两者约 1.1 GiB 的 RSS 差异相符。线程共享只读索引映射，驻留的原始索引页仍计入 RSS。归档目录证据见 [10 GB 归档](large-samples-logs/SRR30352331-archive.txt) 和 [20 GB 归档](large-samples-logs/SRR9158204-archive.txt)。

## 复现

```sh
python3 scripts/benchmark.py --metadata reports/large-samples-verification.json \
  --threads 8 16 --repeats 3 --builds gcc=build/gcc/fasteztq-dump \
  --compressor libdeflate --level 6 --report reports/large-recheck.jsonl
python3 scripts/summarize_large_benchmark.py --report reports/large-recheck.jsonl --output-prefix reports/large-recheck
```

`summarize_large_benchmark.py` 默认汇总已保存的 `large-level6.jsonl`；复测时通过参数选择新 JSONL 与报告路径。来源清单、下载元数据和启动命令分别见 [样本选择](large-samples-selection.json)、[输入验证](large-samples-verification.json)、[测量命令](large-samples-command.json)。
