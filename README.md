# fasteztq-dump

当前为开发准备阶段，尚无转换器实现。

- [开发计划](DEVELOPMENT_PLAN.md)：支持范围、8/16 线程速度对照、2 GiB 内存上限、gzip 解压后逐字节一致性与 /dev/shm 测试要求；允许重写 ncbi-vdb。
- [测试数据](tests/TEST_DATA.md)：20 个已下载并校验的 SRA 文件，Normalized/Lite、单/双读段与不同读长。
- [来源清单](tests/metadata/selection.json) 与 [验证结果](tests/metadata/verification.json)。

在本目录运行 `python scripts/download_test_data.py` 可通过 IPv6 下载缺失数据；已有文件校验通过后跳过。需要 Python 3 和 curl，下载前检查至少 9 GB 可用空间。结构验证另需 SRA Toolkit，脚本中记录了当前安装路径。

`sha256sum -c tests/SHA256SUMS` 可复核全部本地输入。转换输出和临时文件必须放在 /dev/shm，不能将大体积 FASTQ 留在开发盘。
