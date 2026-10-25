# 开发测量

新增大样本结果见 [大样本报告](large-samples.md) 和 [CSV](large-samples-results.csv)，原始数据为 [large-level6.jsonl](large-level6.jsonl)。6.06、10.00、19.92 GB 三个 Normalized SRA 在 GCC、默认 libdeflate 6 下各测 8/16 线程三轮；36 次转换、18 次完整比较、36 个输出流全部通过，累计比对 1.35 TB。最高 RSS 1756.9 MiB。三个样本在两档线程数下均慢于未压缩基线，累计速度比分别为 0.513× / 0.706×。生产程序按实际需求分配内存，开发测试独立记录 RSS。样本清单、IPv6 aria2 下载记录及超过旧地址空间限制的运行证据见报告链接。

20 个约 0.027–1.20 GB 输入的结果见 [完整验收表](final-results.md) 和 [CSV](final-results.csv)，原始数据为 [final-level6.jsonl](final-level6.jsonl)。固定配置为 libdeflate 1.22、6 级，20 输入 × 8/16 线程 × GCC/AOCC，每项三次。360 次转换及 240 次全文件比较全部通过，涉及 360 个输出流、174,972 个 gzip 成员和累计 912.21 GB 的解压内容；峰值总 RSS 812.9 MiB。

该 20 输入矩阵的速度目标在 16 线程下对全部输入达成，累计耗时比约 1.71×。8 线程累计耗时基本持平，GCC 有 6 个输入回退、AOCC 有 8 个，逐项列在结果表中。所有性能对照均为基线 FASTQ 与新工具 gzip FASTQ。

`prototype.jsonl` 保存最小实现的代表样本全量转换和比较结果。每行 `measurement` 为一轮真实执行；`comparison` 为计时结束后的全流字节比较。日志位于对应 `*-logs/` 子目录。

计时程序串行执行转换，原工具的 FASTQ 与新工具的 gzip FASTQ 直接比较耗时。输入每轮预读形成热页缓存。OS `wait4` 峰值和 20 ms 完整进程树采样一起记录；采样可能遗漏瞬时线程或进程树 RSS 峰值。tmpfs 峰值为该轮运行期间整个 `/dev/shm` 已用空间的增量，其他任务的 tmpfs 变化可能影响此值。

`full-correctness.jsonl` 是一次中途停止的开发批次：首个输入之后，校验器曾与计时驱动共用进程，父进程历史 RSS 被后续 fork 子进程继承，导致 `kernel_maxrss_bytes` 偏高。该批次只用于保留已完成的字节比较证据，不用于内存验收或最终速度表。当前驱动将校验器放入独立短生命周期进程。

`blob.jsonl` 记录一次失败的缓存实验。`blob-forward.jsonl` 对应保留当前列 blob 的顺序扫描实现。`compression.jsonl` 是 libdeflate/ISA-L 的完整文件探索性比较，每个配置一次测量；最终结论使用完整矩阵的三次中位数。

`levels.jsonl` 与 `static-column-check.jsonl` 属于已撤回的静态列实验。ncbi-vdb 3.2.1 的 `VCursorIsStaticColumn` 对组合生成的 NAME 会给出不适合跨行复用值的结果，T02 在偏移 330 检出头部差异；诊断见 `static-column-diagnostic.log`。转换器按每行对应的 blob cell 取值。压缩级别比较使用修正后的 `levels-valid.jsonl`。

`early-isal-matrix.jsonl` 是切换压缩默认值前中止的批次，采用 ISA-L 1，仅保留探索证据；日志在 `final-matrix-logs/`。正式验收采用与 `fastq-dump --gzip` 默认 zlib 6 接近的 libdeflate 6，命令显式记录压缩库和级别。

## 默认压缩级别

`fastq-dump 3.2.1` 的 `tools/external/sra-dump/factory.c` 调用 `KFileMakeGzipForWrite`；ncbi-vdb 3.2.1 的 `libs/kfs/gzip.c` 使用 `Z_DEFAULT_COMPRESSION`，内置 zlib 1.2.13 将其解释为 6。libdeflate 1.22 的 API 与 README 将 6 定义为相同 zlib 风格的默认档位。

`compression-calibration.jsonl` 保存 T02/T08/T12/T20 每个 FASTQ 流首、中、尾各 8 MiB 的同内容校准，两种压缩结果均解压逐字节检查。各输入上 libdeflate 6 / zlib 6 的压缩大小比为 99.87%、104.14%、98.93%、97.26%，因此采用 libdeflate 6 为默认与正式验收配置。压缩算法不同，具体字节和压缩率可有差异。此抽样只用于级别校准，全文件一致性由正式矩阵验证。复现：`python3 scripts/calibrate_compression.py`。

`chunk-level6.jsonl` 比较 libdeflate 6 下的 16,384 与 32,768 spot 块，四个代表输入各测 8/16 线程。32,768 块在八组中六组更慢，并提高 RSS，保留 16,384 默认块。变体以同一 GCC 构建的对象/静态依赖链接，仅将 `src/main.c` 的 `CHUNK_ROWS` 改为 32,768；全部比较通过。

ISA-L 各级及接近输出大小下的性能见 [压缩器对照](compression-comparison.md)。`worker-compression.jsonl` 同时记录主线程参与计算的原型：8 线程四个样本均加速约 3%–8%，16 线程均回退约 5%–10%。各构建以同一套 GCC 对象/依赖链接，仅替换主线程任务分配，全部输出一致。

`index-memory-failure.jsonl` 保存正式矩阵首次暴露的 T03 索引映射问题：独立 reader 将111.8 MiB 的只读名称索引重复映射，16 线程创建时耗尽 1900 MiB 地址空间。日志在 `final-level6-logs/20261025-150346-f25248ae/`。`shared-index.jsonl` 为修复后的完整 T03 对照：8 线程 RSS 393.6 MiB，16 线程 571.6 MiB，均逐字节一致。复用原始只读索引映射后，各线程仍有独立解码游标和工作缓冲。
