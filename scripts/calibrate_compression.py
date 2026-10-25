#!/usr/bin/env python3
"""Compare compression ratios on 8 MiB samples at the start/middle/end of FASTQ.

Reference zlib 1.2.13 uses the same default 6 as fastq-dump 3.2.1. This is
compression-ratio calibration, separate from full conversion performance tests.
"""
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '/public/bio-informatic-software/sratoolkit.3.2.1-ubuntu64/bin/fasterq-dump'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build', default='build/compression-probe')
    ap.add_argument('--report', default='reports/compression-calibration.jsonl')
    args = ap.parse_args()
    build = ROOT / args.build
    subprocess.run(['cmake', '-S', ROOT / 'deps/libdeflate-1.22', '-B', build,
                    '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_C_COMPILER=gcc',
                    '-DLIBDEFLATE_BUILD_STATIC_LIB=OFF', '-DLIBDEFLATE_BUILD_GZIP=OFF'], check=True)
    subprocess.run(['cmake', '--build', build, '--target', 'libdeflate_shared', '-j', '8'], check=True)
    library = build / 'libdeflate.so'
    lib = C.CDLL(str(library))
    lib.libdeflate_alloc_compressor.argtypes = [C.c_int]
    lib.libdeflate_alloc_compressor.restype = C.c_void_p
    lib.libdeflate_free_compressor.argtypes = [C.c_void_p]
    encode = lib.libdeflate_gzip_compress
    encode.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t]
    encode.restype = C.c_size_t
    compressor = lib.libdeflate_alloc_compressor(6)
    if not compressor:
        raise MemoryError('compressor allocation')
    size = 8 * 1024**2
    output = C.create_string_buffer(size + size // 8 + 1024)
    manifest = json.loads((ROOT / 'tests/metadata/verification.json').read_text())['files']
    env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    try:
        with (ROOT / args.report).open('w') as report:
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
                                z = zlib.compressobj(level=6, wbits=31)
                                reference = z.compress(data) + z.flush()
                                n = encode(compressor, data, len(data), output, len(output))
                                if not n:
                                    raise RuntimeError('compression failed')
                                encoded = output.raw[:n]
                                assert zlib.decompress(encoded, wbits=31) == data
                                assert zlib.decompress(reference, wbits=31) == data
                                result = dict(test_id=row['test_id'], input_format=row['format'], stream=source.name,
                                              offset=offset, input_bytes=len(data), zlib_version=zlib.ZLIB_RUNTIME_VERSION,
                                              zlib_level=6, zlib_gzip_bytes=len(reference), libdeflate_version='1.22',
                                              libdeflate_level=6, libdeflate_gzip_bytes=n, byte_identical=True)
                                report.write(json.dumps(result) + '\n')
                        print(row['test_id'], source.name, 'calibrated', flush=True)
    finally:
        lib.libdeflate_free_compressor(compressor)


if __name__ == '__main__':
    main()
