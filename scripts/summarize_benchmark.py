#!/usr/bin/env python3
"""Validate the complete acceptance matrix and produce CSV/Markdown summaries."""
import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024**2


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('report')
    ap.add_argument('--output', default='reports/final-results')
    args = ap.parse_args()
    records = [json.loads(line) for line in (ROOT / args.report).read_text().splitlines()]
    measured, compared = {}, {}
    for record in records:
        if record['kind'] == 'failure':
            raise RuntimeError(f'Matrix contains failure: {record}')
        key = (record['test_id'], record['threads'], record['repeat'], record['tool'])
        target = measured if record['kind'] == 'measurement' else compared
        if key in target:
            raise RuntimeError(f'Duplicate result: {key}')
        target[key] = record
    expected = {(f'T{i:02}', t, r, tool) for i in range(1, 21) for t in [8, 16]
                for r in [1, 2, 3] for tool in ['baseline', 'gcc', 'aocc']}
    if measured.keys() != expected or compared.keys() != {k for k in expected if k[-1] != 'baseline'}:
        raise RuntimeError(f'Incomplete matrix: {len(measured)}/360 measurements, {len(compared)}/240 comparisons')
    commits = {v['source_commit'] for v in measured.values()}
    if len(commits) != 1 or any(v['source_dirty'] or v['returncode'] for v in measured.values()):
        raise RuntimeError('Matrix must use one clean source revision and successful processes')
    compression = {(v['compressor'], v['compression_level']) for k, v in measured.items() if k[-1] != 'baseline'}
    if len(compression) != 1:
        raise RuntimeError('Acceptance must use one explicit compression configuration')
    compressor, level = next(iter(compression))
    for key, value in compared.items():
        m = measured[key]
        if m['run_id'] != value['run_id'] or not value['byte_identical'] or not value['streams']:
            raise RuntimeError(f'Comparison does not match measurement: {key}')
        for stream in value['streams']:
            if not (stream['byte_identical'] and stream['gzip_eof_validated'] and
                    stream['baseline_sha256'] == stream['decompressed_sha256']):
                raise RuntimeError(f'Failed stream: {key}')
    groups = defaultdict(list)
    for (test_id, threads, _, tool), record in measured.items():
        groups[test_id, threads, tool].append(record)
    rows = []
    for test_id, threads, tool in sorted(groups):
        group = groups[test_id, threads, tool]
        median = statistics.median(r['elapsed_seconds'] for r in group)
        baseline = statistics.median(r['elapsed_seconds'] for r in groups[test_id, threads, 'baseline'])
        peak_rss = max(max(r['kernel_maxrss_bytes'], r['sampled_tree_peak_rss_bytes'],
                           r['sampled_process_hwm_bytes']) for r in group)
        streams = compared[test_id, threads, 1, tool]['streams'] if tool != 'baseline' else None
        rows.append(dict(test_id=test_id, run=group[0]['run'], input_format=group[0]['input_format'],
                         threads=threads, tool=tool, median_seconds=median, speedup=baseline/median,
                         peak_rss_mib=peak_rss/MIB, memory_pass=tool == 'baseline' or peak_rss <= 2*1024**3,
                         median_user_seconds=statistics.median(r['user_seconds'] for r in group),
                         median_system_seconds=statistics.median(r['system_seconds'] for r in group),
                         peak_os_threads=max(r['peak_os_threads'] for r in group),
                         peak_processes=max(r['peak_processes'] for r in group),
                         peak_tmpfs_additional_gib=max(r['tmpfs_peak_additional_bytes'] for r in group)/1024**3,
                         gzip_bytes=sum(s['gzip_bytes'] for s in streams) if streams else '',
                         fastq_bytes=sum(s['bytes'] for s in streams) if streams else ''))
    output = ROOT / args.output
    with output.with_suffix('.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    lookup = {(r['test_id'], r['threads'], r['tool']): r for r in rows}
    new = [r for r in rows if r['tool'] != 'baseline']
    if not all(r['memory_pass'] for r in new):
        raise RuntimeError('New converter exceeded 2 GiB RSS; see CSV')
    stream_count = sum(len(v['streams']) for v in compared.values())
    lines = ['# 完整验收结果', '',
        f"源码 `{next(iter(commits))}`；20 个不同 Run × 8/16 线程 × 三次重复。共 360 次完整转换，240 次新工具全文件比较，{stream_count} 个输出流全部逐字节一致并通过所有 gzip 成员 CRC/ISIZE 检查。", '',
        f'基线为 fasterq-dump 3.2.1 的未压缩 FASTQ；新工具直接输出 {compressor}、{level} 级 gzip FASTQ。表中耗时含各自完整转换、关闭文件和结束线程。每轮预读同一输入，按热页缓存比较，三轮轮换执行顺序。速度比＝基线中位耗时／新工具中位耗时。', '',
        'fastq-dump 3.2.1 的 gzip 默认是 zlib 6；各压缩库的档位与大小校准见 [压缩实验](README.md#默认压缩级别)，独立于全文件转换计时。', '',
        f"新工具最大总 RSS 为 {max(r['peak_rss_mib'] for r in new):.1f} MiB，全部低于 2048 MiB。RSS 取三轮内核峰值与完整进程树采样最大值；20 ms 采样可能遗漏瞬时线程及进程树峰值，新工具均为单进程。", '',
        '|线程|构建|速度比范围|速度比几何平均|回退样本数|最大 RSS MiB|', '|---:|---|---:|---:|---:|---:|']
    for threads in [8, 16]:
        for tool in ['gcc', 'aocc']:
            group = [r for r in new if r['threads'] == threads and r['tool'] == tool]
            speeds = [r['speedup'] for r in group]
            geo = math.exp(statistics.mean(math.log(x) for x in speeds))
            lines.append(f"|{threads}|{tool.upper()}|{min(speeds):.2f}–{max(speeds):.2f}×|{geo:.2f}×|{sum(s<1 for s in speeds)}|{max(r['peak_rss_mib'] for r in group):.1f}|")
    for threads in [8, 16]:
        lines += ['', f'## {threads} 线程', '',
                  '|输入|格式|基线秒|GCC 秒|GCC 速度比|GCC RSS MiB|AOCC 秒|AOCC 速度比|AOCC RSS MiB|',
                  '|---|---|---:|---:|---:|---:|---:|---:|---:|']
        for i in range(1, 21):
            test_id = f'T{i:02}'
            b, g, a = [lookup[test_id, threads, tool] for tool in ['baseline', 'gcc', 'aocc']]
            lines.append(f"|{test_id} {b['run']}|{b['input_format']}|{b['median_seconds']:.3f}|{g['median_seconds']:.3f}|{g['speedup']:.2f}×|{g['peak_rss_mib']:.1f}|{a['median_seconds']:.3f}|{a['speedup']:.2f}×|{a['peak_rss_mib']:.1f}|")
        regression = [f"{r['test_id']} {r['tool'].upper()} ({r['speedup']:.2f}×)" for r in new if r['threads'] == threads and r['speedup'] < 1]
        lines += ['', '速度回退：' + ('、'.join(regression) if regression else '无') + '。']
        compiler_ratio = [lookup[f'T{i:02}', threads, 'gcc']['median_seconds']/lookup[f'T{i:02}', threads, 'aocc']['median_seconds'] for i in range(1, 21)]
        geo = math.exp(statistics.mean(math.log(x) for x in compiler_ratio))
        lines += ['', f'AOCC 相对 GCC 的速度比几何平均 {geo:.3f}×，范围 {min(compiler_ratio):.3f}–{max(compiler_ratio):.3f}×；{sum(x<1 for x in compiler_ratio)} 个样本 AOCC 较慢。']
    lines += ['', '## 资源与复现', '',
              '|工具|参数线程数|实测 OS 峰值线程数|最大 RSS MiB|最大 tmpfs 增量 GiB|', '|---|---:|---:|---:|---:|']
    for threads in [8, 16]:
        for tool in ['baseline', 'gcc', 'aocc']:
            group = [r for r in rows if r['threads'] == threads and r['tool'] == tool]
            lines.append(f"|{tool}|{threads}|{max(r['peak_os_threads'] for r in group)}|{max(r['peak_rss_mib'] for r in group):.1f}|{max(r['peak_tmpfs_additional_gib'] for r in group):.2f}|")
    lines += ['', 'tmpfs 增量为计时期间整个文件系统已用空间增量，可能受其他任务影响。全部输出及基线临时文件位于 `/dev/shm`，比较后删除。逐输入 CPU 时间、RSS、线程数和字节数见 [CSV](final-results.csv)；完整命令、每轮耗时与流摘要见 [原始记录](' + Path(args.report).name + ')；编译器、依赖版本及完整编译日志见 [构建记录](builds.json)。', '',
              '```sh',
              f'python3 scripts/benchmark.py --threads 8 16 --repeats 3 --compressor {compressor} --level {level} \\',
              '  --builds gcc=build/gcc-release/fasteztq-dump aocc=build/aocc-release/fasteztq-dump \\',
              f'  --report {args.report}',
              f'python3 scripts/summarize_benchmark.py {args.report}',
              '```', '',
              '适用范围：普通 FASTQ 导入、无需参考恢复的 Normalized/Lite，单条或两条非空生物学读段。技术读段、空读段、超过两条读段、参考/比对表、超出块缓冲或进程内存预算的输入会明确失败。块顺序、默认头与加号行、质量和输出流划分以原工具为比较基准。']
    output.with_suffix('.md').write_text('\n'.join(lines) + '\n')
    print(f'{len(measured)} measurements, {len(compared)} comparisons, {stream_count} streams; all accepted')


if __name__ == '__main__':
    main()
