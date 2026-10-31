/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Share immutable on-disk index mappings, not cursor/decompression state. */
#include "index_mmap.h"
#include <kfs/file-impl.h>
#include <kfs/directory.h>
#include <sysfile-priv.h>
#include <klib/rc.h>
#include <pthread.h>
#include <stdlib.h>
#include <sys/types.h>
#include <sys/stat.h>

struct KRIndex;
rc_t __real_KRIndexMakeRead(struct KRIndex **index, const KDirectory *dir, const char *path);
rc_t __real_KMMapMakeRead(const KMMap **map, const KFile *file);

typedef struct Mapping {
    struct Mapping *next;
    dev_t device;
    ino_t inode;
    uint64_t offset, size;
    const KMMap *map;
} Mapping;
static Mapping *mappings;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static _Thread_local bool opening_index;

rc_t index_mmap_read(const KMMap **map, const KFile *file) {
    uint64_t offset, size;
    KSysFile *sys = KFileGetSysFile(file, &offset);
    /* Non-native files retain VDB's own read semantics. */
    if (!sys) return __real_KMMapMakeRead(map, file);
    struct stat st;
    if (fstat(sys->fd, &st)) return RC(rcFS, rcMemMap, rcConstructing, rcFile, rcInvalid);
    rc_t rc = KFileSize(file, &size);
    if (rc) return rc;
    *map = NULL;
    pthread_mutex_lock(&mutex);
    for (Mapping *m = mappings; m; m = m->next) {
        if (m->device == st.st_dev && m->inode == st.st_ino && m->offset == offset && m->size == size) {
            rc = KMMapAddRef(m->map);
            if (!rc) *map = m->map;
            pthread_mutex_unlock(&mutex);
            return rc;
        }
    }
    rc = __real_KMMapMakeRead(map, file);
    if (!rc) {
        Mapping *m = malloc(sizeof *m);
        if (!m) rc = RC(rcFS, rcMemMap, rcConstructing, rcMemory, rcExhausted);
        else {
            rc = KMMapAddRef(*map);
            if (!rc) {
                *m = (Mapping){mappings, st.st_dev, st.st_ino, offset, size, *map};
                mappings = m;
            } else free(m);
        }
        if (rc) { KMMapRelease(*map); *map = NULL; }
    }
    pthread_mutex_unlock(&mutex);
    return rc;
}

/* GNU/LLVM linker wrapping confines reuse to immutable KDB read indexes.
   Other KMMap callers can reposition their mappings and remain independent. */
rc_t __wrap_KRIndexMakeRead(struct KRIndex **index, const KDirectory *dir, const char *path) {
    bool previous = opening_index;
    opening_index = true;
    rc_t rc = __real_KRIndexMakeRead(index, dir, path);
    opening_index = previous;
    return rc;
}
rc_t __wrap_KMMapMakeRead(const KMMap **map, const KFile *file) {
    return opening_index ? index_mmap_read(map, file) : __real_KMMapMakeRead(map, file);
}
void index_mmap_release_all(void) {
    pthread_mutex_lock(&mutex);
    while (mappings) {
        Mapping *m = mappings;
        mappings = m->next;
        KMMapRelease(m->map);
        free(m);
    }
    pthread_mutex_unlock(&mutex);
}
