#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Correctness tests using synthetic SRA records and explicit FASTQ expectations."""
import argparse
import gzip
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/release'


def expected(mode, accession, rows):
    streams = {}
    for row in range(1, rows + 1):
        count = 1 if mode == 'single' else 1 + row % 2 if mode == 'mixed' else 2
        lengths = ([4, 4] if mode == 'fixed' else [row % 3 + 1, row % 5 + 1])[:count]
        bases = b'ACGTNACGTN'
        quality = bytes(min(q, 93) + 33 for q in [0, 3, 30, 40, 93, 94, 255, 20, 2, 1])
        offset = 0
        for i, length in enumerate(lengths):
            suffix = '' if count == 1 else f'_{i + 1}'
            dest = streams.setdefault(accession + suffix + '.fastq.gz', bytearray())
            name = '' if mode == 'no-name' else (f' instrument:{row}' if row % 7 else f' {row}')
            header = f'{accession}.{row}{name} length={length}\n'.encode()
            read_quality = bytes([36 if (row + i) % 2 else 63]) * length if mode == 'lite' else quality[offset:offset + length]
            dest.extend(b'@' + header + bases[offset:offset + length] + b'\n+' + header + read_quality + b'\n')
            offset += length
    return streams


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='fasteztq-tests-')
        self.addCleanup(self.directory.cleanup)
        self.tmp = Path(self.directory.name)
        self.binary = BUILD / 'fasteztq-dump'

    def fixture(self, mode='paired', rows=17):
        source = self.tmp / (mode + '.sra')
        subprocess.run([BUILD / 'make_fixture', self.tmp / (mode + '-table'), source,
                        mode, str(rows), ROOT / 'third_party/ncbi-vdb/interfaces'],
                       check=True, capture_output=True, timeout=30)
        return source

    def convert(self, source, destination, *options, env=None):
        return subprocess.run([self.binary, source, '-O', destination, *map(str, options)],
                              capture_output=True, timeout=30, env=env)

    def check_output(self, directory, truth):
        self.assertEqual({p.name for p in directory.iterdir()}, truth.keys())
        for name, content in truth.items():
            with gzip.open(directory / name, 'rb') as stream:
                self.assertEqual(stream.read(), content, name)

    def test_layouts_and_quality(self):
        for mode in ['single', 'paired', 'mixed', 'fixed', 'no-name', 'database', 'lite']:
            source = self.fixture(mode)
            for threads in [1, 2, 9]:
                with self.subTest(mode=mode, threads=threads):
                    dest = self.tmp / f'{mode}-{threads}'
                    result = self.convert(source, dest, '-e', threads)
                    self.assertEqual(result.returncode, 0, result.stderr.decode())
                    self.check_output(dest, expected(mode, mode, 17))

    def test_chunk_order_and_gzip_members(self):
        rows = 2 * 16384 + 3
        source = self.fixture('mixed', rows)
        for backend in ['libdeflate', 'isal']:
            for threads in [1, 2, 9]:
                with self.subTest(backend=backend, threads=threads):
                    dest = self.tmp / f'{backend}-{threads}'
                    result = self.convert(source, dest, '-e', threads, '--compressor', backend, '--level', 1)
                    self.assertEqual(result.returncode, 0, result.stderr.decode())
                    self.check_output(dest, expected('mixed', 'mixed', rows))
                    for path in dest.iterdir():
                        remaining, members = path.read_bytes(), 0
                        while remaining:
                            decoder = zlib.decompressobj(wbits=31)
                            decoder.decompress(remaining)
                            self.assertTrue(decoder.eof)
                            remaining = decoder.unused_data
                            members += 1
                        self.assertEqual(members, 3)

    def test_compression_levels(self):
        source = self.fixture()
        for backend, levels in [('libdeflate', [0, 1, 6, 12]), ('isal', [0, 1, 2, 3])]:
            for level in levels:
                with self.subTest(backend=backend, level=level):
                    dest = self.tmp / f'{backend}-{level}'
                    result = self.convert(source, dest, '-e', 1, '--compressor', backend, '--level', level)
                    self.assertEqual(result.returncode, 0, result.stderr.decode())
                    self.check_output(dest, expected('paired', 'paired', 17))

    def test_existing_output(self):
        source = self.fixture()
        dest = self.tmp / 'out'
        dest.mkdir()
        existing = dest / 'paired_2.fastq.gz'
        existing.write_bytes(b'previous result')
        result = self.convert(source, dest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'already exists', result.stderr)
        self.assertEqual(list(dest.iterdir()), [existing])
        self.assertEqual(existing.read_bytes(), b'previous result')

    def test_invalid_layout_cleanup(self):
        for mode, message in [('technical', b'unsupported'), ('empty', b'unsupported'),
                              ('three', b'supported layout'), ('bad-quality', b'lengths disagree'),
                              ('reference', b'unsupported table')]:
            source = self.fixture(mode, 16385)
            for threads in [1, 2, 9]:
                with self.subTest(mode=mode, threads=threads):
                    dest = self.tmp / f'{mode}-{threads}'
                    result = self.convert(source, dest, '-e', threads)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(message, result.stderr)
                    self.assertEqual(list(dest.iterdir()), [])

    def test_archive_errors(self):
        source = self.fixture()
        data = source.read_bytes()
        for name, content in [('truncated.sra', data[:len(data) // 2]), ('invalid.sra', b'invalid archive')]:
            with self.subTest(name=name):
                bad = self.tmp / name
                bad.write_bytes(content)
                dest = self.tmp / (name + '-out')
                result = self.convert(bad, dest, '-e', 1)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(dest.iterdir()), [])

    def test_write_failure_cleanup(self):
        source = self.fixture()
        dest = self.tmp / 'out'
        env = dict(os.environ, LD_PRELOAD=str(BUILD / 'fail_write.so'))
        result = self.convert(source, dest, '-e', 1, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'write output', result.stderr)
        self.assertEqual(list(dest.iterdir()), [])

    def test_suffix_and_symlink_naming(self):
        source = self.fixture()
        renamed = self.tmp / 'renamed.sralite'
        shutil.copyfile(source, renamed)
        alias = self.tmp / 'alias.sra'
        alias.symlink_to(source)
        for path, accession in [(renamed, 'renamed'), (alias, 'alias')]:
            dest = self.tmp / (accession + '-out')
            result = self.convert(path, dest, '-e', 1)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.check_output(dest, expected('paired', accession, 17))

    def test_invalid_options(self):
        source = self.fixture()
        for options in [('--level', 13), ('--level', -1), ('--compressor', 'unknown'),
                        ('--compressor', 'isal'), ('--compressor', 'isal', '--level', 4),
                        ('-e', 0), ('-e', -1), ('-e', 'abc'), ('-e', 2**32)]:
            with self.subTest(options=options):
                dest = self.tmp / 'out'
                result = self.convert(source, dest, *options)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(dest.exists())

    def test_missing_input_and_output_directory(self):
        result = self.convert(self.tmp / 'missing.sra', self.tmp / 'out')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.tmp / 'out').exists())
        source = self.fixture()
        dest = self.tmp / 'file'
        dest.write_bytes(b'existing file')
        result = self.convert(source, dest)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(dest.read_bytes(), b'existing file')

    def test_index_mappings(self):
        subprocess.run([BUILD / 'test_mappings', self.tmp], check=True, capture_output=True, timeout=30)

    def test_help_and_version(self):
        for option, text in [('--help', b'Usage:'), ('--version', b'fasteztq-dump')]:
            result = subprocess.run([self.binary, option], capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0)
            self.assertIn(text, result.stdout)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', default='build/release')
    args, remaining = parser.parse_known_args()
    BUILD = (ROOT / args.build).resolve()
    unittest.main(argv=[__file__, *remaining], verbosity=2)
