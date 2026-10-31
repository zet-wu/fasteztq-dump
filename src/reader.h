/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef FASTEZTQ_READER_H
#define FASTEZTQ_READER_H
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

typedef struct {
    const char *bases, *name;
    const uint8_t *quality, *types;
    const uint32_t *lengths;
    uint32_t bases_len, name_len, nreads;
} Spot;

typedef struct Reader Reader;
/* model carries the input structure already inspected by the first reader. */
Reader *reader_open(const char *path, const Reader *model);
void reader_close(Reader *r);
void reader_range(Reader *r, int64_t *first, uint64_t *count);
bool reader_has_name(Reader *r);
void reader_spot(Reader *r, int64_t row, Spot *spot);
#endif
