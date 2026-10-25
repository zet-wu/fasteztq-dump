"""The acceptance checker must reject corruption beyond the first gzip member."""
import gzip
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from compare_gzip import compare_stream


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='fasteztq-compare-')
        self.addCleanup(self.tmp.cleanup)
        self.raw = Path(self.tmp.name) / 'sample.fastq'
        self.gz = Path(self.tmp.name) / 'sample.fastq.gz'
        self.a, self.b = b'@a\nACN\n+\n!I~\n', b'@b\nGT\n+\n??\n'
        self.raw.write_bytes(self.a + self.b)
        self.good = gzip.compress(self.a) + gzip.compress(self.b)
        self.gz.write_bytes(self.good)

    def test_every_member(self):
        result = compare_stream(self.raw, self.gz)
        self.assertEqual(result['gzip_members'], 2)
        self.assertEqual(result['records'], 2)
        self.assertEqual(result['baseline_sha256'], result['decompressed_sha256'])

    def test_empty_member_between_records(self):
        self.gz.write_bytes(gzip.compress(self.a) + gzip.compress(b'') + gzip.compress(self.b))
        self.assertEqual(compare_stream(self.raw, self.gz)['gzip_members'], 3)

    def test_member_larger_than_initial_buffer(self):
        count = 64 * 1024**2 // len(self.a) + 1
        data = self.a * count
        self.raw.write_bytes(data)
        self.gz.write_bytes(gzip.compress(data, compresslevel=1))
        result = compare_stream(self.raw, self.gz)
        self.assertEqual(result['bytes'], len(data))
        self.assertEqual(result['records'], count)
        self.assertEqual(result['gzip_members'], 1)

    def test_damaged_second_member_crc(self):
        data = bytearray(self.good)
        data[-8] ^= 1
        self.gz.write_bytes(data)
        with self.assertRaisesRegex(RuntimeError, 'failed validation'):
            compare_stream(self.raw, self.gz)

    def test_truncated_second_member(self):
        self.gz.write_bytes(self.good[:-3])
        with self.assertRaisesRegex(RuntimeError, 'failed validation'):
            compare_stream(self.raw, self.gz)

    def test_trailing_junk(self):
        self.gz.write_bytes(self.good + b'bad')
        with self.assertRaisesRegex(RuntimeError, 'failed validation'):
            compare_stream(self.raw, self.gz)

    def test_content_mismatch(self):
        self.raw.write_bytes(self.a + self.b.replace(b'GT', b'GG'))
        with self.assertRaisesRegex(RuntimeError, 'byte mismatch'):
            compare_stream(self.raw, self.gz)

    def test_missing_member(self):
        self.gz.write_bytes(gzip.compress(self.a))
        with self.assertRaisesRegex(RuntimeError, 'ended before baseline'):
            compare_stream(self.raw, self.gz)

    def test_extra_member(self):
        self.gz.write_bytes(self.good + gzip.compress(self.a))
        with self.assertRaisesRegex(RuntimeError, 'byte mismatch'):
            compare_stream(self.raw, self.gz)


if __name__ == '__main__':
    unittest.main()
