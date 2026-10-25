#define _POSIX_C_SOURCE 200809L
#include "gzip.h"
#include "common.h"
#include <libdeflate.h>
#include <zlib.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

_Noreturn void fail(const char *fmt, ...) {
    va_list args;
    va_start(args, fmt); vfprintf(stderr, fmt, args); va_end(args);
    fputc('\n', stderr); exit(1);
}
void *allocate(size_t n) {
    void *p = malloc(n);
    if (!p) fail("out of memory");
    return p;
}
static double seconds(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &t)) fail("clock_gettime");
    return t.tv_sec + t.tv_nsec * 1e-9;
}
int main(int argc, char **argv) {
    int match = argc == 2 && !strcmp(argv[1], "--match-levels");
    if (argc != 1 && !match) fail("usage: compression_probe [--match-levels]");
    size_t capacity = 8UL * 1024 * 1024;
    char *input = allocate(capacity), *decoded = allocate(capacity);
    size_t count = fread(input, 1, capacity, stdin);
    if (ferror(stdin) || !count || fgetc(stdin) != EOF) fail("expected 1..8 MiB input");
    size_t bound = gzip_bound(count);
    void *output = allocate(bound);
    struct libdeflate_decompressor *d = libdeflate_alloc_decompressor();
    if (!d) fail("decoder allocation");
    puts("[");
    for (int config = 0; config < 6; ++config) {
        const char *name = match ? "libdeflate" : config == 0 ? "zlib" : config == 1 ? "libdeflate" : "isal";
        unsigned level = match ? config + 1 : config < 2 ? 6 : config - 2;
        GzipCompressor *c = (match || config) ? gzip_new((match || config == 1) ? GZIP_LIBDEFLATE : GZIP_ISAL, level) : NULL;
        size_t n = 0;
        double times[3];
        for (int repeat = 0; repeat < 3; ++repeat) {
            double begin = seconds();
            if (c) n = gzip_encode(c, input, count, output, bound);
            else {
                z_stream z = {0};
                if (deflateInit2(&z, Z_DEFAULT_COMPRESSION, Z_DEFLATED, 31, 8, Z_DEFAULT_STRATEGY) != Z_OK)
                    fail("zlib init");
                z.next_in = (unsigned char *)input; z.avail_in = count;
                z.next_out = output; z.avail_out = bound;
                if (deflate(&z, Z_FINISH) != Z_STREAM_END) fail("zlib encode");
                n = z.total_out;
                if (deflateEnd(&z) != Z_OK) fail("zlib finish");
            }
            times[repeat] = seconds() - begin;
            size_t produced;
            if (libdeflate_gzip_decompress(d, output, n, decoded, capacity, &produced) != LIBDEFLATE_SUCCESS ||
                produced != count || memcmp(input, decoded, count)) fail("decompression mismatch");
        }
        printf("%s{\"compressor\":\"%s\",\"level\":%u,\"gzip_bytes\":%zu,\"cpu_seconds\":[%.9f,%.9f,%.9f],\"byte_identical\":true}\n",
               config ? "," : "", name, level, n, times[0], times[1], times[2]);
        if (c) gzip_free(c);
    }
    puts("]");
    libdeflate_free_decompressor(d);
    free(input); free(decoded); free(output);
}
