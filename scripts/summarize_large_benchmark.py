#!/usr/bin/env python3
"""Summarize the three full large-file experiments and the original size trend."""
import csv
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]


def main():
    records = [json.loads(line) for line in (ROOT / 'reports/large-level6.jsonl').read_text().splitlines()]
    measurements = [r for r in records if r['kind'] == 'measurement']
    comparisons = [r for r in records if r['kind'] == 'comparison']
    expected = {(case, threads, repeat, tool) for case in ['L01', 'L02', 'L03']
                for threads in [8, 16] for repeat in [1, 2, 3] for tool in ['baseline', 'gcc']}
    key = lambda r: (r['test_id'], r['threads'], r['repeat'], r['tool'])
    if len(measurements) != len(expected) or {key(r) for r in measurements} != expected:
        raise ValueError('Incomplete or duplicate measurement matrix')
    if len(comparisons) != 18 or {key(r) for r in comparisons} != {k for k in expected if k[-1] == 'gcc'}:
        raise ValueError('Incomplete or duplicate comparison matrix')
    if any(r['kind'] == 'failure' for r in records) or any(r['returncode'] or r['source_dirty'] for r in measurements):
        raise ValueError('Failed or dirty-source measurement')
    for r in measurements:
        if r['tool'] == 'gcc' and (r['compressor'], r['compression_level']) != ('libdeflate', 6):
            raise ValueError('Unexpected compression configuration')
    streams = [s for r in comparisons for s in r['streams']]
    if not all(s['byte_identical'] and s['gzip_eof_validated'] and
               s['baseline_sha256'] == s['decompressed_sha256'] for s in streams):
        raise ValueError('Output verification failed')
    selection = {r['test_id']: r for r in json.loads((ROOT / 'reports/large-samples-selection.json').read_text())}
    verified = {r['test_id']: r for r in json.loads((ROOT / 'reports/large-samples-verification.json').read_text())['files']}
    output = []
    for case in selection:
        for threads in [8, 16]:
            groups = {tool: [r for r in measurements if (r['test_id'], r['threads'], r['tool']) == (case, threads, tool)]
                      for tool in ['baseline', 'gcc']}
            base = statistics.median(r['elapsed_seconds'] for r in groups['baseline'])
            new = statistics.median(r['elapsed_seconds'] for r in groups['gcc'])
            checked = next(r['streams'] for r in comparisons if r['test_id'] == case and r['threads'] == threads)
            output.append(dict(test_id=case, run=selection[case]['run'], threads=threads,
                input_gb=selection[case]['bytes'] / 1e9, spots=verified[case]['spots'],
                baseline_seconds=base, new_seconds=new, speedup=base / new,
                baseline_min_seconds=min(r['elapsed_seconds'] for r in groups['baseline']),
                baseline_max_seconds=max(r['elapsed_seconds'] for r in groups['baseline']),
                new_min_seconds=min(r['elapsed_seconds'] for r in groups['gcc']),
                new_max_seconds=max(r['elapsed_seconds'] for r in groups['gcc']),
                baseline_rss_mib=max(max(r['kernel_maxrss_bytes'], r['sampled_tree_peak_rss_bytes']) for r in groups['baseline']) / 1024**2,
                new_rss_mib=max(max(r['kernel_maxrss_bytes'], r['sampled_tree_peak_rss_bytes']) for r in groups['gcc']) / 1024**2,
                new_cpu_cores=statistics.median((r['user_seconds'] + r['system_seconds']) / r['elapsed_seconds'] for r in groups['gcc']),
                baseline_cpu_cores=statistics.median((r['user_seconds'] + r['system_seconds']) / r['elapsed_seconds'] for r in groups['baseline']),
                fastq_gb=sum(s['bytes'] for s in checked) / 1e9,
                gzip_gb=sum(s['gzip_bytes'] for s in checked) / 1e9,
                peak_tmpfs_gib=max(r['tmpfs_peak_additional_bytes'] for r in groups['baseline']) / 1024**3))
    destination = ROOT / 'reports/large-samples-results.csv'
    with destination.open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(output[0])); writer.writeheader(); writer.writerows(output)
    old_records = [json.loads(line) for line in (ROOT / 'reports/final-level6.jsonl').read_text().splitlines()]
    old_meta = {r['test_id']: {'bytes': r['input_bytes']} for r in old_records if r['kind'] == 'measurement'}
    old = [r for r in csv.DictReader((ROOT / 'reports/final-results.csv').open()) if r['tool'] == 'gcc' and r['threads'] == '8']
    old.sort(key=lambda r: old_meta[r['test_id']]['bytes'])
    ranks = lambda xs: [sorted(xs).index(x) + 1 for x in xs]
    rho = statistics.correlation(ranks([old_meta[r['test_id']]['bytes'] for r in old]), ranks([float(r['speedup']) for r in old]))
    regressions = [r for r in old if float(r['speedup']) < 1]
    lines = ['# 大样本转换与内存限制移除', '',
        '## 原有 8 线程回退与大小', '',
        f'原 20 输入矩阵中，GCC 在 8 线程的 6 个回退输入恰为 SRA 最大的 6 个。SRA 字节数与速度比的 Spearman 相关系数为 {rho:.3f}。速度比定义为原版耗时 / 新程序耗时，大于 1 表示新程序更快。', '',
        '| 输入 | 格式 | SRA GB | 速度比 |', '|---|---|---:|---:|']
    lines += [f"| {r['test_id']} / {r['run']} | {r['input_format']} | {old_meta[r['test_id']]['bytes']/1e9:.3f} | {float(r['speedup']):.3f}× |" for r in regressions]
    lines += ['', '这是所选输入中的相关性。输入格式、质量值、读长、NAME 索引及输出量也同时变化，不能仅凭相关性断定 SRA 大小是原因。小文件的速度比受到启动开销影响；完整大文件测试用于检查持续吞吐。', '',
        '## 样品与方法', '',
        '从 `/home/wangzeyu/wangzeyu-nvme1/coexpress-evolution/rnaseq/cohorts/` 样品清单选取三个较大 Normalized SRA，保留原始质量值。6 GB 样本复用既有缓存；10/20 GB 样本下载至当前项目 `tests/data/large/`，原始文件均保留。', '',
        '| 输入 | 物种 | SRA GB | spot 数 | 抽样读长 |', '|---|---|---:|---:|---|']
    for case, r in selection.items():
        lines.append(f"| {r['run']} | {r['organism']} | {r['bytes']/1e9:.3f} | {verified[case]['spots']:,} | {', '.join(verified[case]['sampled_read_lengths'])} |")
    lines += ['', '下载使用 `sra-pub-run-odp.s3.dualstack.us-east-1.amazonaws.com`，aria2 每文件 16 连接；AAAA-only 局部解析器与 `--interface=::` 保证 IPv6，实际 IPv6 TCP 连接已记录。下载后按来源元数据校验大小、MD5，并对全部输入执行 VDB 完整验证及布局抽样。下载日志、命令及连接证据见 [下载记录](large-samples-logs/)。', '',
        '使用 GCC 12.2.0、`-O3 -DNDEBUG`，默认 libdeflate 6。每个样本在 8/16 线程各重复三轮，串行运行并交替原版/新程序顺序。每次计时前预读完整输入；输出和临时文件均写入 `/dev/shm`，逐组比较后清理。计时覆盖启动到退出。原版 fasterq-dump 3.2.1 输出未压缩 FASTQ，新程序直接输出 gzip FASTQ，因此这是两种实际工作流的耗时比较，不能视为同压缩任务比较。', '',
        'RSS 取 OS 峰值及 20 ms 完整进程树采样的最大值。原版 8/16 线程参数按 16/32 CPU token 计，新程序按 8/16 计；BLAS/OpenMP 线程为 1。开发测试预估 tmpfs 峰值并检查 252 GiB 工作区预算，生产程序按需使用内存。', '',
        '## 完整大样本结果', '',
        '| 样本 | 线程 | 原版 s | 新程序 s | 速度比 | 新 RSS MiB | 原版 RSS MiB |', '|---|---:|---:|---:|---:|---:|---:|']
    lines += [f"| {r['run']} | {r['threads']} | {r['baseline_seconds']:.3f} | {r['new_seconds']:.3f} | {r['speedup']:.3f}× | {r['new_rss_mib']:.1f} | {r['baseline_rss_mib']:.1f} |" for r in output]
    lines += ['', '表中耗时为三轮中位数；每轮范围、CPU 占用、输出字节数和 tmpfs 使用量见 [CSV](large-samples-results.csv)，逐次测量及完整比较见 [JSONL](large-level6.jsonl)。', '',
        f"共 {len(measurements)} 次转换、{len(comparisons)} 次完整比较、{len(streams)} 个输出流，逐字节一致并验证全部 gzip 成员 CRC/ISIZE；累计比较 {sum(s['bytes'] for s in streams)/1e12:.3f} TB。新程序观测最大 RSS 为 {max(r['new_rss_mib'] for r in output):.1f} MiB。", '',
        '## 运行时内存行为', '',
        '生产程序通过固定数量的工作槽位、16384 spot 分块、有序背压、缓冲复用和只读索引共享控制内存增长。缓冲按当前块需求扩容，实际占用取决于线程数、读长、解码数据块和输入索引。实际分配失败仍报告错误并清理临时输出。ISA-L 的单次输入/输出使用其接口规定的 32 位长度范围。', '',
        '本次移除了 `RLIMIT_AS`、`--memory-mib` 和每流 64 MiB 固定上限；开发脚本独立记录 RSS 是否达到 2 GiB 优化目标，完整运行及比对保留超出目标的测量。实际运行的 `/proc/PID/limits` 证据见 [运行限制](large-samples-logs/runtime-limits.json)。GCC/AOCC 边界测试和超过 64 MiB 的完整 gzip 成员测试均通过。', '',
        '## 复现', '', '```sh',
        'python3 scripts/benchmark.py --metadata reports/large-samples-verification.json \\\n  --threads 8 16 --repeats 3 --builds gcc=build/gcc/fasteztq-dump \\\n  --compressor libdeflate --level 6 --report reports/large-recheck.jsonl',
        'python3 scripts/summarize_large_benchmark.py', '```', '',
        '`summarize_large_benchmark.py` 汇总已保存的 `large-level6.jsonl`；复测请选择新 JSONL 路径。来源清单、下载元数据和启动命令分别见 [样本选择](large-samples-selection.json)、[输入验证](large-samples-verification.json)、[测量命令](large-samples-command.json)。', '']
    conclusions = []
    for threads in [8, 16]:
        group = [r for r in output if r['threads'] == threads]
        slower = sum(r['speedup'] < 1 for r in group)
        ratio = sum(r['baseline_seconds'] for r in group) / sum(r['new_seconds'] for r in group)
        conclusions.append(f'{threads} 线程下，{slower}/3 个大样本相对未压缩基线回退；三样本中位耗时合计的速度比为 {ratio:.3f}×。')
    conclusions += ['', '旧 20 输入的 16 线程加速结论适用于其约 0.027–1.20 GB 输入范围；本次大样本结果应独立报告。新程序计时包含默认 6 级压缩，源文件大小与质量分布、索引结构、解码量和压缩工作量同时变化，本测试不能单独量化每个因素的因果贡献。', '',
        '| 样本 | SRA GB | 解压后 FASTQ GB | gzip GB |', '|---|---:|---:|---:|']
    conclusions += [f"| {r['run']} | {r['input_gb']:.3f} | {r['fastq_gb']:.3f} | {r['gzip_gb']:.3f} |" for r in output if r['threads'] == 8]
    at = lines.index('## 运行时内存行为')
    lines[at:at] = ['## 结果解释', '', *conclusions, '']
    snapshot = json.loads((ROOT / 'reports/large-samples-logs/large-index-t16-memory.json').read_text())
    status = dict(line.split(':', 1) for line in snapshot['status'].splitlines())
    virtual = int(status['VmSize'].split()[0]) / 1024**2
    resident = int(status['VmRSS'].split()[0]) / 1024
    at = lines.index('## 复现')
    lines[at:at] = [f'10 GB 样本 16 线程的一次运行快照中，虚拟地址空间为 {virtual:.3f} GiB，而同一时刻 RSS 为 {resident:.1f} MiB（这是中途快照，完整运行峰值见结果表）。其地址空间已超过旧的 2048 MiB 最大设置；地址空间上限与实际驻留内存并不等价。证据见 [大索引快照](large-samples-logs/large-index-t16-memory.json)。', '']
    (ROOT / 'reports/large-samples.md').write_text('\n'.join(lines))
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
