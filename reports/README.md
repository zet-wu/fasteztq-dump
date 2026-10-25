# 开发测量

`prototype.jsonl` 保存最小实现的代表样本全量转换和比较结果。每行 `measurement` 为一轮真实执行；`comparison` 为计时结束后的全流字节比较。日志位于对应 `*-logs/` 子目录。

计时程序串行执行转换，原工具的 FASTQ 与新工具的 gzip FASTQ 直接比较耗时。输入每轮预读形成热页缓存。OS `wait4` 峰值和 20 ms 完整进程树采样一起记录；采样可能遗漏瞬时线程或进程树 RSS 峰值。tmpfs 峰值为该轮运行期间整个 `/dev/shm` 已用空间的增量，其他任务的 tmpfs 变化可能影响此值。

`full-correctness.jsonl` 是一次中途停止的开发批次：首个输入之后，校验器曾与计时驱动共用进程，父进程历史 RSS 被后续 fork 子进程继承，导致 `kernel_maxrss_bytes` 偏高。该批次只用于保留已完成的字节比较证据，不用于内存验收或最终速度表。当前驱动将校验器放入独立短生命周期进程。

`blob.jsonl` 记录一次失败的缓存实验。`blob-forward.jsonl` 对应保留当前列 blob 的顺序扫描实现。`compression.jsonl` 是 libdeflate/ISA-L 的完整文件探索性比较，每个配置一次测量；最终结论使用完整矩阵的三次中位数。

`levels.jsonl` 与 `static-column-check.jsonl` 属于已撤回的静态列实验。ncbi-vdb 3.2.1 的 `VCursorIsStaticColumn` 对组合生成的 NAME 会给出不适合跨行复用值的结果，T02 在偏移 330 检出头部差异；诊断见 `static-column-diagnostic.log`。转换器按每行对应的 blob cell 取值。压缩级别比较使用修正后的 `levels-valid.jsonl`。

`early-isal-matrix.jsonl` 是切换压缩默认值前中止的批次，采用 ISA-L 1，仅保留探索证据；日志在 `final-matrix-logs/`。正式验收采用与 `fastq-dump --gzip` 默认 zlib 6 接近的 libdeflate 6，命令显式记录压缩库和级别。

## 默认压缩级别

`fastq-dump 3.2.1` 的 `tools/external/sra-dump/factory.c` 调用 `KFileMakeGzipForWrite`；ncbi-vdb 3.2.1 的 `libs/kfs/gzip.c` 使用 `Z_DEFAULT_COMPRESSION`，内置 zlib 1.2.13 将其解释为 6。libdeflate 1.22 的 API 与 README 将 6 定义为相同 zlib 风格的默认档位。

`compression-calibration.jsonl` 保存 T02/T08/T12/T20 每个 FASTQ 流首、中、尾各 8 MiB 的同内容校准，两种压缩结果均解压逐字节检查。各输入上 libdeflate 6 / zlib 6 的压缩大小比为 99.87%、104.14%、98.93%、97.26%，因此采用 libdeflate 6 为默认与正式验收配置。压缩算法不同，具体字节和压缩率可有差异。此抽样只用于级别校准，全文件一致性由正式矩阵验证。复现：`python3 scripts/calibrate_compression.py`。
