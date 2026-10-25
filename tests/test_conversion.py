#!/usr/bin/env python3
"""Small SRA integration cases for layout, boundaries, names, and I/O failures."""
import argparse
import gzip
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOOLKIT = Path('/public/bio-informatic-software/sratoolkit.3.2.1-ubuntu64/bin')


def expected(mode, accession):
    streams = {}
    for row in range(1, 20001):
        nr = 1 + row % 2 if mode == 'mixed' else 2
        lengths = [row % 3 + 1, row % 5 + 1][:nr]
        bases = b'ACGTNACGTN'
        quality = bytes(min(q, 93) + 33 for q in [0, 3, 30, 40, 93, 94, 255, 20, 2, 1])
        offset = 0
        for i, length in enumerate(lengths):
            suffix = '' if nr == 1 else f'_{i+1}'
            dest = streams.setdefault(accession + suffix + '.fastq.gz', bytearray())
            name = '' if mode == 'no-name' else (f' instrument:{row}' if row % 7 else f' {row}')
            header = f'{accession}.{row}{name} length={length}\n'.encode()
            dest.extend(b'@' + header + bases[offset:offset+length] + b'\n+' + header + quality[offset:offset+length] + b'\n')
            offset += length
    return streams


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='build/gcc')
    args = ap.parse_args()
    build = ROOT / args.build
    binary = build / 'fasteztq-dump'
    with tempfile.TemporaryDirectory(prefix='fasteztq-tests-', dir='/dev/shm') as directory:
        tmp = Path(directory)
        for mode in ['paired', 'mixed', 'no-name', 'technical', 'late-technical', 'empty', 'three', 'bad-quality', 'reference']:
            table = tmp / (mode + '-table')
            source = tmp / (mode + '.sra')
            subprocess.run([build / 'make_fixture', table, mode], check=True)
            subprocess.run([TOOLKIT / 'kar', '-c', source, '-d', table], check=True, capture_output=True)
            for threads in [1, 8]:
                dest = tmp / f'{mode}-{threads}'
                result = subprocess.run([binary, source, '-e', str(threads), '-O', dest], capture_output=True)
                if mode in ['paired', 'mixed', 'no-name']:
                    assert result.returncode == 0, result.stderr.decode()
                    truth = expected(mode, mode)
                    assert {p.name for p in dest.iterdir()} == truth.keys()
                    for name, content in truth.items():
                        with gzip.open(dest / name, 'rb') as f:
                            assert f.read() == content, (mode, threads, name)
                    # Refusing to overwrite must preserve all existing files.
                    again = subprocess.run([binary, source, '-O', dest], capture_output=True)
                    assert again.returncode and b'already exists' in again.stderr
                    for name, content in truth.items():
                        with gzip.open(dest / name, 'rb') as f:
                            assert f.read() == content
                else:
                    assert result.returncode != 0, mode
                    assert not list(dest.iterdir()), (mode, list(dest.iterdir()))
                    message = b'unsupported' if mode != 'bad-quality' else b'lengths disagree'
                    if mode == 'three':
                        message = b'supported layout'
                    assert message in result.stderr, result.stderr.decode()
            print(mode, 'OK', flush=True)
        source = tmp / 'paired.sra'
        # Quality decoding is based on VDB contents, even with a Lite suffix.
        renamed = tmp / 'renamed.sralite'
        shutil.copyfile(source, renamed)
        dest = tmp / 'renamed-out'
        subprocess.run([binary, renamed, '-e', '1', '-O', dest], check=True, capture_output=True)
        for name, content in expected('paired', 'renamed').items():
            with gzip.open(dest / name, 'rb') as f:
                assert f.read() == content
        alias = tmp / 'alias.sra'
        alias.symlink_to(source)
        for backend, level in [('libdeflate', 0), ('libdeflate', 1), ('libdeflate', 6), ('libdeflate', 12),
                               ('isal', 0), ('isal', 1), ('isal', 2), ('isal', 3)]:
            dest = tmp / f'level-{backend}-{level}'
            subprocess.run([binary, alias, '-e', '1', '--compressor', backend, '--level', str(level), '-O', dest], check=True, capture_output=True)
            for name, content in expected('paired', 'alias').items():
                with gzip.open(dest / name, 'rb') as f:
                    assert f.read() == content
        for options in [['--level', '13'], ['--level', '-1'], ['--compressor', 'unknown'],
                        ['--compressor', 'isal'], ['--compressor', 'isal', '--level', '4']]:
            dest = tmp / 'invalid-options'
            result = subprocess.run([binary, source, '-O', dest, *options], capture_output=True)
            assert result.returncode and not dest.exists(), (options, result.stderr)
        truncated = tmp / 'truncated.sra'
        data = source.read_bytes()
        truncated.write_bytes(data[:len(data)//2])
        dest = tmp / 'truncated-out'
        result = subprocess.run([binary, truncated, '-O', dest], capture_output=True)
        assert result.returncode and not list(dest.iterdir())
        def size_limit():
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            resource.setrlimit(resource.RLIMIT_FSIZE, (512, 512))
        dest = tmp / 'write-failure'
        result = subprocess.run([binary, source, '-e', '1', '-O', dest], preexec_fn=size_limit, capture_output=True)
        assert result.returncode and b'write output' in result.stderr, result.stderr
        assert not list(dest.iterdir())
        print('renamed format, symlink naming, gzip levels, truncated input, and write failure OK', flush=True)


if __name__ == '__main__':
    main()
