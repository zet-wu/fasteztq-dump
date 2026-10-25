#ifndef FASTEZTQ_INDEX_MMAP_H
#define FASTEZTQ_INDEX_MMAP_H
#include <kfs/file.h>
#include <kfs/mmap.h>
rc_t index_mmap_read(const KMMap **map, const KFile *file);
void index_mmap_release_all(void);
#endif
