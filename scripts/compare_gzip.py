"""Development-only, bounded-output gzip member comparison using libdeflate.

The archive is mapped read-only to the process (private writable mapping is
needed by ctypes); decompressed data stays in a fixed 64 MiB buffer. No output
copy is written to disk. libdeflate validates each member's CRC and ISIZE.
"""
import ctypes as C
import ctypes.util
import hashlib
import mmap
import json
from pathlib import Path
import sys


def compare_stream(original, compressed):
    lib = C.CDLL(ctypes.util.find_library('deflate'))
    lib.libdeflate_alloc_decompressor.restype = C.c_void_p
    lib.libdeflate_free_decompressor.argtypes = [C.c_void_p]
    decompress = lib.libdeflate_gzip_decompress_ex
    decompress.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t,
                           C.POINTER(C.c_size_t), C.POINTER(C.c_size_t)]
    decompress.restype = C.c_int
    memcmp = C.CDLL(None).memcmp
    memcmp.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
    memcmp.restype = C.c_int
    decoder = lib.libdeflate_alloc_decompressor()
    if not decoder:
        raise MemoryError('libdeflate decompressor')
    capacity = 64 * 1024**2
    output = C.create_string_buffer(capacity)
    view = memoryview(output).cast('B')
    digest_a, digest_b = hashlib.sha256(), hashlib.sha256()
    total = lines = members = 0
    try:
        with compressed.open('rb') as source, original.open('rb') as baseline:
            with mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_COPY) as archive:
                address = C.addressof(C.c_char.from_buffer(archive))
                offset = 0
                while offset < len(archive):
                    consumed, produced = C.c_size_t(), C.c_size_t()
                    rc = decompress(decoder, address + offset, len(archive) - offset,
                                    output, capacity, C.byref(consumed), C.byref(produced))
                    if rc:
                        raise RuntimeError(f'{compressed.name}: gzip member {members} failed validation (libdeflate={rc})')
                    count = produced.value
                    expected = baseline.read(count)
                    if len(expected) != count or memcmp(output, expected, count):
                        actual = bytes(view[:count])
                        index = next((i for i, (a, b) in enumerate(zip(expected, actual)) if a != b), min(len(expected), count))
                        raise RuntimeError(f'{compressed.name}: byte mismatch in member {members} at stream offset {total + index}: '
                                           f'baseline={expected[index:index+80]!r}, actual={actual[index:index+80]!r}')
                    digest_a.update(expected)
                    digest_b.update(view[:count])
                    lines += expected.count(b'\n')
                    total += count
                    offset += consumed.value
                    members += 1
                if baseline.read(1):
                    raise RuntimeError(f'{compressed.name}: gzip ended before baseline')
    finally:
        view.release()
        lib.libdeflate_free_decompressor(decoder)
    if lines % 4:
        raise RuntimeError(f'{compressed.name}: incomplete FASTQ record')
    return dict(baseline_stream=original.name, gzip_stream=compressed.name, bytes=total,
                baseline_sha256=digest_a.hexdigest(), decompressed_sha256=digest_b.hexdigest(),
                records=lines // 4, gzip_bytes=compressed.stat().st_size, gzip_members=members,
                byte_identical=True, gzip_eof_validated=True)


if __name__ == '__main__':
    print(json.dumps(compare_stream(Path(sys.argv[1]), Path(sys.argv[2]))))
