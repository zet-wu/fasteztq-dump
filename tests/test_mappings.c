#define _POSIX_C_SOURCE 200809L
#include "index_mmap.h"
#include <kfs/directory.h>
#include <kfs/subfile.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <unistd.h>

#define CHECK(call) do { rc_t rc = (call); if (rc) { fprintf(stderr, "%s: 0x%x\n", #call, rc); exit(1); } } while (0)
static void require(int ok, const char *what) { if (!ok) { perror(what); exit(1); } }
static void content(const KMMap *map, char expected) {
    const void *address;
    CHECK(KMMapAddrRead(map, &address));
    require(*(const char *)address == expected, "mapping contents");
}
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    char first[4096], second[4096];
    snprintf(first, sizeof first, "%s/index-a", argv[1]);
    snprintf(second, sizeof second, "%s/index-b", argv[1]);
    int fd = open(first, O_CREAT | O_EXCL | O_RDWR, 0600);
    require(fd >= 0, "create index A");
    require(!ftruncate(fd, 128 * 1024 * 1024), "size index A");
    require(pwrite(fd, "A", 1, 0) == 1 && pwrite(fd, "B", 1, 64 * 1024 * 1024) == 1, "write index A");
    require(!close(fd), "close index A");
    fd = open(second, O_CREAT | O_EXCL | O_RDWR, 0600);
    require(fd >= 0 && !ftruncate(fd, 4096), "create index B");
    require(write(fd, "C", 1) == 1 && !close(fd), "write index B");
    struct rlimit limit = {256 * 1024 * 1024, 256 * 1024 * 1024};
    require(!setrlimit(RLIMIT_AS, &limit), "memory budget");
    KDirectory *dir;
    CHECK(KDirectoryNativeDir(&dir));
    const KMMap *maps[16];
    for (int i = 0; i < 16; ++i) {
        const KFile *file;
        CHECK(KDirectoryOpenFileRead(dir, &file, "%s", first));
        CHECK(index_mmap_read(&maps[i], file));
        CHECK(KFileRelease(file));
        content(maps[i], 'A');
    }
    const KFile *file, *part;
    const KMMap *view;
    CHECK(KDirectoryOpenFileRead(dir, &file, "%s", first));
    for (unsigned i = 0; i < 2; ++i) {
        CHECK(KFileMakeSubRead(&part, file, i * 64UL * 1024 * 1024, 4096));
        CHECK(index_mmap_read(&view, part));
        content(view, i ? 'B' : 'A');
        size_t size;
        CHECK(KMMapSize(view, &size));
        require(size == 4096, "mapping length");
        CHECK(KMMapRelease(view));
        CHECK(KFileRelease(part));
    }
    CHECK(KFileRelease(file));
    CHECK(KDirectoryOpenFileRead(dir, &file, "%s", second));
    CHECK(index_mmap_read(&view, file));
    content(view, 'C');
    CHECK(KMMapRelease(view));
    CHECK(KFileRelease(file));
    index_mmap_release_all();
    for (int i = 0; i < 16; ++i) {
        content(maps[i], 'A');
        CHECK(KMMapRelease(maps[i]));
    }
    CHECK(KDirectoryRelease(dir));
    require(!unlink(first) && !unlink(second), "remove test indexes");
    puts("shared index mappings, offsets, sizes and ownership OK");
}
