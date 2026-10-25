#ifndef FASTEZTQ_GZIP_H
#define FASTEZTQ_GZIP_H
#include <stddef.h>
typedef struct GzipCompressor GzipCompressor;
GzipCompressor *gzip_new(unsigned level);
void gzip_free(GzipCompressor *c);
size_t gzip_bound(size_t size);
size_t gzip_encode(GzipCompressor *c, const void *data, size_t size, void *output, size_t capacity);
#endif
