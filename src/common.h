#ifndef FASTEZTQ_COMMON_H
#define FASTEZTQ_COMMON_H
#include <stddef.h>
_Noreturn void fail(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void *allocate(size_t n);
#endif
