/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef FASTEZTQ_GZIP_H
#define FASTEZTQ_GZIP_H
#include <stddef.h>
typedef struct GzipCompressor GzipCompressor;
typedef enum { GZIP_LIBDEFLATE, GZIP_ISAL } GzipBackend;
GzipCompressor *gzip_new(GzipBackend backend, unsigned level);
void gzip_free(GzipCompressor *c);
size_t gzip_bound(size_t size);
size_t gzip_encode(GzipCompressor *c, const void *data, size_t size, void *output, size_t capacity);
#endif
