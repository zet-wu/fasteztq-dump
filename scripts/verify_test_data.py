#!/usr/bin/env python3
"""Verify downloaded fixture identity and sample local SRA structure; no conversion benchmark."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
BIN = Path('/public/bio-informatic-software/sratoolkit.3.2.1-ubuntu64/bin')
ENV = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')


def atomic_json(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    tmp.replace(path)


def run_tool(row, label, argv, timeout=300):
    logdir = ROOT / 'tests/logs' / row['test_id']
    logdir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    result = subprocess.run(list(map(str, argv)), env=ENV, capture_output=True, text=True, timeout=timeout)
    (logdir / (label + '.stdout.txt')).write_text(result.stdout)
    (logdir / (label + '.stderr.txt')).write_text(result.stderr)
    atomic_json(logdir / (label + '.command.json'), dict(command=list(map(str, argv)),
                returncode=result.returncode, elapsed_seconds=time.monotonic()-started))
    if result.returncode:
        raise RuntimeError(f'{label}: return code {result.returncode}: {result.stderr[-600:]}')
    return result.stdout


def as_list(value):
    return value if isinstance(value, list) else [value]


def verify(row):
    result = {k: row[k] for k in ('test_id', 'run', 'format', 'relative_path', 'expected_biological_layout')}
    try:
        path = ROOT / row['relative_path']
        if path.stat().st_size != row['bytes']:
            raise ValueError('Size mismatch')
        md5, sha = hashlib.md5(), hashlib.sha256()
        with path.open('rb') as src:
            magic = src.read(8)
            src.seek(0)
            while block := src.read(8 * 1024**2):
                md5.update(block); sha.update(block)
        if magic != b'NCBI.sra':
            raise ValueError('Unexpected archive signature')
        if md5.hexdigest() != row['md5']:
            raise ValueError('Source MD5 mismatch')
        result.update(bytes=path.stat().st_size, md5=md5.hexdigest(), sha256=sha.hexdigest())
        toc = run_tool(row, 'archive', [BIN/'kar', '-t', path])
        tables = sorted(x.split('/')[1] for x in toc.splitlines() if x.startswith('tbl/') and x.count('/') == 1)
        if any(t not in ('SEQUENCE', 'QUAL_STAT') for t in tables):
            raise ValueError('Reference/alignment or unsupported extra tables: ' + str(tables))
        physical = sorted({x.split('/col/', 1)[1].split('/')[0] for x in toc.splitlines() if '/col/' in x})
        if not tables:
            physical = sorted({x.split('/')[1] for x in toc.splitlines() if x.startswith('col/')})
        quality_columns = sorted(set(physical) & {'QUALITY', 'ORIGINAL_QUALITY'})
        if row['format'] == 'Normalized' and not quality_columns:
            raise ValueError('Normalized input missing physical quality storage')
        if row['format'] == 'Lite' and quality_columns:
            raise ValueError('Lite input unexpectedly contains full quality storage')
        info = run_tool(row, 'info', [BIN/'vdb-dump', path, '--info', '--disable-multithreading'])
        fields = {}
        for line in info.splitlines():
            if ':' in line:
                k, v = line.split(':', 1); fields[k.strip()] = v.strip()
        match = re.search(r'^SEQ\s*:\s*([\d,]+)', info, re.M)
        spots = int(match.group(1).replace(',', '')) if match else row['record']['spots']
        ids = sorted(set([*range(1, min(33, spots+1)),
                          *range(max(1, spots//2-16), min(spots+1, spots//2+16)),
                          *range(max(1, spots-31), spots+1),
                          *[1 + (spots-1)*i//63 for i in range(64)]]))
        sampled = json.loads(run_tool(row, 'sample-rows', [BIN/'vdb-dump', path, '-T', 'SEQUENCE',
                         '-R', ','.join(map(str, ids)), '-C', 'READ_LEN,READ_TYPE,READ_FILTER,QUALITY',
                         '-n', '-f', 'json', '--disable-multithreading']))
        if len(sampled) != len(ids):
            raise ValueError('Requested sample rows were not all returned')
        layouts, lengths, quality_values = Counter(), Counter(), Counter()
        for cell in sampled:
            lens, types, filters = [as_list(cell[k]) for k in ('READ_LEN','READ_TYPE','READ_FILTER')]
            qual = as_list(cell['QUALITY'])
            if len(lens) != len(types) or len(lens) != len(filters) or sum(lens) != len(qual):
                raise ValueError('Inconsistent sampled read layout/quality length')
            biological = [length for length, typ in zip(lens, types) if typ & 1 and length > 0]
            layouts[len(biological)] += 1
            lengths.update(biological)
            quality_values.update(qual)
            if row['format'] == 'Lite':
                offset = 0
                for length, filt in zip(lens, filters):
                    expected = 30 if filt == 0 else 3
                    if any(q != expected for q in qual[offset:offset+length]):
                        raise ValueError('Lite quality synthesis differs from read-filter semantics')
                    offset += length
        expect = 1 if row['expected_biological_layout'] == 'SE' else 2
        if set(layouts) != {expect}:
            raise ValueError(f'Actual sampled biological read counts {dict(layouts)} differ from {expect}')
        run_tool(row, 'vdb-validate', [BIN/'vdb-validate', path], timeout=600)
        result.update(status='verified', tables=tables or ['flat SEQUENCE table'],
            schema=fields.get('SCHEMA'), format_tool=fields.get('FMT'), loader=fields.get('LDR'),
            physical_columns=physical, full_quality_columns=quality_columns, spots=spots,
            source_layout=row['record']['layout'], actual_sampled_layout=row['expected_biological_layout'],
            sampled_rows=ids, sampled_biological_read_counts=dict(layouts), sampled_read_lengths=dict(sorted(lengths.items())),
            sampled_quality_values=dict(sorted(quality_values.items())),
            sample_caveat='Read layout/length/quality checks are stratified samples, not an exhaustive scan; vdb-validate and hashes cover the complete file.')
    except Exception as exc:
        result.update(status='failed', error=str(exc))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--wait', action='store_true', help='wait for aria2 downloads to finish')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--timeout', type=int, default=3600)
    args = ap.parse_args()
    if not 1 <= args.workers <= 8:
        ap.error('workers must be in 1..8')
    rows = json.loads((ROOT/'tests/metadata/selection.json').read_text())
    output = ROOT/'tests/metadata/verification.json'
    results = {}
    if output.exists():
        for r in json.loads(output.read_text()).get('files', []):
            if r['status'] == 'verified':
                p = ROOT/r['relative_path']
                if p.exists() and p.stat().st_size == r['bytes']:
                    results[r['test_id']] = r
    pending = [r for r in rows if r['test_id'] not in results]
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        active = {}
        while pending or active:
            for future, row in list(active.items()):
                if future.done():
                    result = future.result(); results[row['test_id']] = result
                    print(row['test_id'], row['run'], result['status'], result.get('error', ''), flush=True)
                    del active[future]
                    atomic_json(output, dict(files=[results[k] for k in sorted(results)],
                        total_expected=len(rows), verified=sum(r['status']=='verified' for r in results.values())))
            for row in list(pending):
                if len(active) >= args.workers:
                    break
                p = ROOT/row['relative_path']
                if p.exists() and p.stat().st_size == row['bytes'] and not p.with_name(p.name+'.aria2').exists():
                    active[pool.submit(verify, row)] = row; pending.remove(row)
            if pending and not active and not args.wait:
                break
            if time.monotonic()-started > args.timeout:
                print('Timed out waiting for downloads', flush=True); break
            time.sleep(1)
    print('Verified', sum(r['status']=='verified' for r in results.values()), '/', len(rows), flush=True)
    return 0 if len(results)==len(rows) and all(r['status']=='verified' for r in results.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
