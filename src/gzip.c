#include "gzip.h"
#include "common.h"
#include <igzip_lib.h>
#include <stdlib.h>

struct GzipCompressor {
    struct isal_zstream stream;
    unsigned level, level_size;
    unsigned char *level_buffer;
};
GzipCompressor *gzip_new(unsigned level) {
    static const unsigned sizes[] = {ISAL_DEF_LVL0_DEFAULT, ISAL_DEF_LVL1_DEFAULT,
                                    ISAL_DEF_LVL2_DEFAULT, ISAL_DEF_LVL3_DEFAULT};
    GzipCompressor *c = allocate(sizeof *c);
    c->level = level;
    c->level_size = sizes[level];
    c->level_buffer = c->level_size ? allocate(c->level_size) : NULL;
    return c;
}
void gzip_free(GzipCompressor *c) {
    free(c->level_buffer);
    free(c);
}
size_t gzip_bound(size_t size) {
    /* More than the maximum stored-block and gzip wrapper expansion. */
    return size + size / 8 + 1024;
}
size_t gzip_encode(GzipCompressor *c, const void *data, size_t size, void *output, size_t capacity) {
    struct isal_zstream *z = &c->stream;
    isal_deflate_stateless_init(z);
    z->level = c->level;
    z->level_buf = c->level_buffer;
    z->level_buf_size = c->level_size;
    z->gzip_flag = IGZIP_GZIP;
    z->next_in = (unsigned char *)data;
    z->avail_in = size;
    z->next_out = output;
    z->avail_out = capacity;
    z->end_of_stream = 1;
    int rc = isal_deflate_stateless(z);
    if (rc != COMP_OK) fail("ISA-L gzip compression failed (%d)", rc);
    return z->total_out;
}
