#!/usr/bin/env python3
"""Compare compression ratios on 8 MiB samples at the start/middle/end of FASTQ.

Reference zlib 1.2.13 uses the same default 6 as fastq-dump 3.2.1. This is
compression-ratio calibration, separate from full conversion performance tests.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '/public/bio-informatic-software/sratoolkit.3.2.1-ubuntu64/bin/fasterq-dump'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build', default='build/gcc')
    ap.add_argument('--report', default='reports/compression-levels.jsonl')
    ap.add_argument('--match-levels', action='store_true', help='probe libdeflate levels 1..6 for size-matched comparisons')
    args = ap.parse_args()
    build = ROOT / args.build
    subprocess.run(['make', f'BUILD={args.build}', str(Path(args.build) / 'compression_probe')], check=True)
    probe = build / 'compression_probe'
    size = 8 * 1024**2
    manifest = json.loads((ROOT / 'tests/metadata/verification.json').read_text())['files']
    env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    with (ROOT / args.report).open('w', buffering=1) as report:
        for row in manifest:
            if row['test_id'] not in ['T02', 'T08', 'T12', 'T20']:
                continue
            mem = int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))) * 1024
            if min(mem, shutil.disk_usage('/dev/shm').free) < 64 * 1024**3:
                raise RuntimeError('need 64 GiB free memory/tmpfs for calibration')
            with tempfile.TemporaryDirectory(prefix='fasteztq-compression-', dir='/dev/shm') as directory:
                folder = Path(directory)
                subprocess.run([BASELINE, ROOT / row['relative_path'], '--split-files', '-e', '8',
                                '-O', folder, '-t', folder / 'tmp'], check=True, env=env, capture_output=True)
                for source in sorted(folder.glob('*.fastq')):
                    length = source.stat().st_size
                    with source.open('rb') as f:
                        for offset in sorted({0, max(0, (length-size)//2), max(0, length-size)}):
                            f.seek(offset)
                            data = f.read(size)
                            results = json.loads(subprocess.check_output([probe, *(['--match-levels'] if args.match_levels else [])], input=data, env=env))
                            result = dict(test_id=row['test_id'], input_format=row['format'], stream=source.name,
                                          offset=offset, input_bytes=len(data), zlib_version='1.2.13',
                                          libdeflate_version='1.22', isal_version='2.31.0', results=results)
                            report.write(json.dumps(result) + '\n')
                    print(row['test_id'], source.name, 'calibrated', flush=True)



if __name__ == '__main__':
    main()
