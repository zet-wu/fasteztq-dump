#!/usr/bin/env python3
"""Serial full-file benchmark; all conversion output stays in /dev/shm.

Each independent comparison reads every gzip member to EOF and compares bytes.
Only this development script hashes and re-reads output, outside conversion timing.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path('/public/bio-informatic-software/sratoolkit.3.2.1-ubuntu64/bin/fasterq-dump')
ENV = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
MIB = 1024**2


def proc_tree(pid):
    """Sample all descendants, including children created by non-main threads."""
    pending, seen, rss, hwm, threads = [pid], set(), 0, 0, 0
    while pending:
        p = pending.pop()
        if p in seen:
            continue
        seen.add(p)
        try:
            fields = dict(line.split(':', 1) for line in Path(f'/proc/{p}/status').read_text().splitlines())
            rss += int(fields.get('VmRSS', '0 kB').split()[0]) * 1024
            hwm = max(hwm, int(fields.get('VmHWM', '0 kB').split()[0]) * 1024)
            threads += int(fields['Threads'])
            for task in Path(f'/proc/{p}/task').iterdir():
                pending.extend(map(int, (task / 'children').read_text().split()))
        except (FileNotFoundError, ProcessLookupError):
            pass  # Process exit races are expected at the /proc boundary.
    return rss, hwm, threads, len(seen)


def measure(argv, log, tmp_root):
    before_tmp = shutil.disk_usage('/dev/shm').used
    peak_rss = peak_hwm = peak_threads = peak_processes = peak_tmp = 0
    started = time.monotonic()
    with log.open('wb') as stderr:
        p = subprocess.Popen(list(map(str, argv)), env=ENV, stdout=stderr, stderr=stderr, start_new_session=True)
        try:
            while True:
                rss, hwm, threads, processes = proc_tree(p.pid)
                peak_rss, peak_hwm = max(peak_rss, rss), max(peak_hwm, hwm)
                peak_threads, peak_processes = max(peak_threads, threads), max(peak_processes, processes)
                peak_tmp = max(peak_tmp, shutil.disk_usage('/dev/shm').used - before_tmp)
                done, status, usage = os.wait4(p.pid, os.WNOHANG)
                if done:
                    p.returncode = os.waitstatus_to_exitcode(status)
                    break
                time.sleep(0.02)
        except BaseException:
            os.killpg(p.pid, signal.SIGTERM)
            p.wait()
            raise
    elapsed = time.monotonic() - started
    return dict(command=list(map(str, argv)), returncode=p.returncode, elapsed_seconds=elapsed,
                user_seconds=usage.ru_utime, system_seconds=usage.ru_stime,
                kernel_maxrss_bytes=usage.ru_maxrss * 1024, sampled_tree_peak_rss_bytes=peak_rss,
                sampled_process_hwm_bytes=peak_hwm, peak_os_threads=peak_threads,
                peak_processes=peak_processes, tmpfs_peak_additional_bytes=peak_tmp,
                stderr=str(log.relative_to(ROOT)), sample_interval_seconds=0.02,
                sampling_caveat='Short-lived threads/children and between-sample aggregate RSS spikes may be missed; wait4 reports the OS high-water mark for the process/children, not simultaneous tree RSS.')


def compare(baseline, new):
    originals = {p.name: p for p in baseline.glob('*.fastq')}
    compressed = {p.stem: p for p in new.glob('*.fastq.gz')}
    if not originals or originals.keys() != compressed.keys():
        raise RuntimeError(f'Output stream mismatch: {sorted(originals)} vs {sorted(compressed)}')
    # Keep mmap/decompression memory in a short-lived process: the long-lived
    # parent must stay small, since fork can carry its historical RSS into a
    # subsequent child's wait4 high-water statistic.
    def one(item):
        name, src = item
        return json.loads(subprocess.check_output(
            [sys.executable, ROOT / 'scripts/compare_gzip.py', src, compressed[name]], env=ENV))
    with ThreadPoolExecutor(max_workers=min(3, len(originals))) as pool:
        return list(pool.map(one, sorted(originals.items())))


def available_memory():
    fields = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    return int(fields['MemAvailable'].split()[0]) * 1024


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ids', nargs='*')
    ap.add_argument('--metadata', default='tests/metadata/verification.json', help='verified input manifest')
    ap.add_argument('--tmpfs-budget-gib', type=float, default=252, help='development workspace memory budget')
    ap.add_argument('--threads', nargs='+', type=int, default=[8, 16])
    ap.add_argument('--repeats', type=int, default=3)
    ap.add_argument('--builds', nargs='+', default=['gcc=build/gcc/fasteztq-dump', 'aocc=build/aocc/fasteztq-dump'])
    ap.add_argument('--report', default='reports/benchmark.jsonl')
    ap.add_argument('--compressor', choices=['libdeflate', 'isal'], default='libdeflate')
    ap.add_argument('--level', type=int, default=6)
    ap.add_argument('--compression-configs', nargs='*', default=[], metavar='NAME=COMPRESSOR:LEVEL',
                    help='override compression per build for controlled comparisons')
    args = ap.parse_args()
    if not 0 <= args.level <= (12 if args.compressor == 'libdeflate' else 3):
        ap.error('level outside compressor range')
    if any(t not in (1, 8, 16) for t in args.threads) or args.repeats < 1:
        ap.error('threads must be 1, 8 or 16; repeats must be positive')
    rows = json.loads((ROOT / args.metadata).read_text())['files']
    if args.ids:
        rows = [r for r in rows if r['test_id'] in args.ids]
        if len(rows) != len(set(args.ids)):
            ap.error('unknown test id')
    builds = {name: (ROOT / binary).resolve() for name, binary in (s.split('=', 1) for s in args.builds)}
    configs = {name: (args.compressor, args.level) for name in builds}
    for spec in args.compression_configs:
        name, value = spec.split('=', 1)
        compressor, level = value.split(':', 1)
        level = int(level)
        if name not in builds or compressor not in ('libdeflate', 'isal') or not 0 <= level <= (12 if compressor == 'libdeflate' else 3):
            ap.error(f'invalid compression override {spec}')
        configs[name] = compressor, level
    for binary in [BASELINE, *builds.values()]:
        if not binary.is_file():
            ap.error(f'missing binary {binary}')
    report = ROOT / args.report
    report.parent.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    tmp_root = Path('/dev/shm/fasteztq-bench') / run_id
    tmp_root.mkdir(parents=True)
    logs = report.parent / (report.stem + '-logs') / run_id
    logs.mkdir(parents=True)
    version = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(
        ['git', 'status', '--porcelain', '--', 'src', 'Makefile', 'scripts', 'tests'], cwd=ROOT))
    with report.open('a', buffering=1) as out:
        for row in rows:
            for threads in args.threads:
                for repeat in range(args.repeats):
                    case = f"{row['test_id']}-t{threads}-r{repeat+1}"
                    maxlen = max(map(int, row['sampled_read_lengths']))
                    nr = 1 if row['actual_sampled_layout'] == 'SE' else 2
                    # Allow 160 header bytes per read and simultaneous output/scratch.
                    estimated_fastq = row['spots'] * nr * (2 * maxlen + 160)
                    estimate = estimated_fastq * max(2, 1 + len(builds)) + 8 * 1024**3
                    if min(shutil.disk_usage('/dev/shm').free, available_memory(), args.tmpfs_budget_gib * 1024**3 - shutil.disk_usage('/dev/shm').used) < estimate:
                        raise RuntimeError(f'{case}: insufficient tmpfs/memory for conservative {estimate}-byte peak estimate')
                    folder = tmp_root / case
                    folder.mkdir()
                    names = ['baseline', *builds]
                    # Alternate original/new order, also alternate compiler order.
                    if repeat % 2 == 1:
                        names.reverse()
                    if repeat % 3 == 2:
                        names = names[1:] + names[:1]
                    measurements = {}
                    try:
                        for name in names:
                            dest = folder / name
                            dest.mkdir()
                            src = (ROOT / row['relative_path']).resolve()
                            if src.stat().st_size != row['bytes']:
                                raise RuntimeError(f'{src}: input size differs from verified fixture manifest')
                            # Explicit warm-page-cache protocol, outside timed conversion.
                            with src.open('rb') as f:
                                while f.read(8 * MIB):
                                    pass
                            if name == 'baseline':
                                argv = [BASELINE, src, '--split-files', '-e', threads, '-O', dest, '-t', folder / 'baseline-tmp']
                            else:
                                compressor, level = configs[name]
                                argv = [builds[name], src, '-e', threads, '-O', dest,
                                        '--compressor', compressor, '--level', level]
                            result = measure(argv, logs / f'{case}-{name}.log', tmp_root)
                            result.update(kind='measurement', run_id=run_id, test_id=row['test_id'], run=row['run'],
                                input_format=row['format'], input_md5=row['md5'], input_sha256=row.get('sha256'),
                                input_bytes=row['bytes'], tool=name, threads=threads, repeat=repeat+1,
                                source_commit=version, source_dirty=dirty, cache='input pre-read before each timed run; warm page cache',
                                output_format='FASTQ' if name == 'baseline' else 'gzip FASTQ')
                            if name != 'baseline':
                                result.update(compressor=compressor, compression_level=level,
                                    rss_target_bytes=2 * 1024**3,
                                    rss_target_met=max(result['kernel_maxrss_bytes'], result['sampled_tree_peak_rss_bytes']) <= 2 * 1024**3)
                            out.write(json.dumps(result) + '\n')
                            print(case, name, f"{result['elapsed_seconds']:.3f}s", f"RSS={result['kernel_maxrss_bytes']/MIB:.1f}MiB", f"threads={result['peak_os_threads']}", flush=True)
                            if result['returncode']:
                                raise RuntimeError(f'{name} failed; see {result["stderr"]}')
                            measurements[name] = result
                        # Conversions above stay serial. Only untimed acceptance
                        # checks run concurrently (at most 2 builds x 3 streams).
                        with ThreadPoolExecutor(max_workers=2) as pool:
                            checks = {name: pool.submit(compare, folder / 'baseline', folder / name) for name in builds}
                            for name, future in checks.items():
                                streams = future.result()
                                out.write(json.dumps(dict(kind='comparison', run_id=run_id, test_id=row['test_id'], threads=threads,
                                    repeat=repeat+1, tool=name, streams=streams, byte_identical=True)) + '\n')
                        print(case, 'all streams identical', flush=True)
                    except BaseException as exc:
                        out.write(json.dumps(dict(kind='failure', case=case, error=str(exc))) + '\n')
                        raise
                    finally:
                        shutil.rmtree(folder)
    tmp_root.rmdir()


if __name__ == '__main__':
    main()
