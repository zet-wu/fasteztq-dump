/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Inject a disk write error after the first regular-file write. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

ssize_t write(int fd, const void *buffer, size_t count) {
    static ssize_t (*real_write)(int, const void *, size_t);
    static int wrote_file;
    if (!real_write) *(void **)(&real_write) = dlsym(RTLD_NEXT, "write");
    struct stat st;
    if (count && !fstat(fd, &st) && S_ISREG(st.st_mode)) {
        if (wrote_file) { errno = ENOSPC; return -1; }
        wrote_file = 1;
    }
    return real_write(fd, buffer, count);
}
