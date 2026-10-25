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
Reader *reader_open(const char *path);
void reader_close(Reader *r);
void reader_range(Reader *r, int64_t *first, uint64_t *count);
bool reader_has_name(Reader *r);
void reader_spot(Reader *r, int64_t row, Spot *spot);
_Noreturn void fail(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void *allocate(size_t n);
#endif
