#define _GNU_SOURCE
#include "reader.h"
#include <libdeflate.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <getopt.h>
#include <limits.h>
#include <sys/stat.h>
#include <sys/resource.h>
#include <signal.h>
#include <malloc.h>

#define MIB (1024UL * 1024)
#define CHUNK_ROWS 16384
#define STREAMS 3

typedef struct { char *data; size_t len, cap; } Buffer;
typedef struct {
    Reader *reader;
    struct libdeflate_compressor *compressor;
    Buffer raw[STREAMS], compressed[STREAMS];
    unsigned index;
    bool ready;
} Worker;
static struct {
    char *accession;
    const char *outdir;
    int64_t first;
    uint64_t count, chunks;
    unsigned workers;
    pthread_mutex_t mutex;
    pthread_cond_t cond;
} state = {.mutex = PTHREAD_MUTEX_INITIALIZER, .cond = PTHREAD_COND_INITIALIZER};
static struct { char temp[PATH_MAX], final[PATH_MAX]; int fd; bool published; } output[STREAMS];
static bool complete;
static volatile sig_atomic_t interrupted;

static void cleanup(void) {
    for (int i = 0; i < STREAMS; ++i) {
        if (output[i].temp[0]) unlink(output[i].temp);
        if (!complete && output[i].published) unlink(output[i].final);
    }
}
_Noreturn void fail(const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    fputs("fasteztq-dump: ", stderr);
    vfprintf(stderr, fmt, args);
    fputc('\n', stderr);
    va_end(args);
    exit(1);
}
void *allocate(size_t n) {
    void *p = malloc(n);
    if (!p) fail("memory budget exhausted allocating %zu bytes", n);
    return p;
}
static void reserve(Buffer *b, size_t need) {
    if (need <= b->cap) return;
    if (need > 64 * MIB) fail("chunk exceeds 64 MiB per-stream buffer limit");
    size_t cap = b->cap ? b->cap : MIB;
    while (cap < need) cap *= 2;
    char *p = realloc(b->data, cap);
    if (!p) fail("memory budget exhausted growing buffer to %zu bytes", cap);
    b->data = p;
    b->cap = cap;
}
static void format(Worker *w, int64_t row, const Spot *s) {
    uint32_t offset = 0;
    for (uint32_t i = 0; i < s->nreads; ++i) {
        Buffer *b = &w->raw[s->nreads == 1 ? 0 : i + 1];
        uint32_t len = s->lengths[i];
        size_t header_cap = strlen(state.accession) + s->name_len + 100;
        reserve(b, b->len + 2 * header_cap + 2 * (size_t)len + 4);
        char *p = b->data + b->len;
        char *header = p;
        int n;
        if (reader_has_name(w->reader)) {
            if (s->name_len)
                n = snprintf(p, header_cap, "@%s.%lld %.*s length=%u\n", state.accession, (long long)row, (int)s->name_len, s->name, len);
            else n = snprintf(p, header_cap, "@%s.%lld %lld length=%u\n", state.accession, (long long)row, (long long)row, len);
        } else n = snprintf(p, header_cap, "@%s.%lld length=%u\n", state.accession, (long long)row, len);
        if (n < 0 || (size_t)n >= header_cap) fail("FASTQ header too long at row %lld", (long long)row);
        p += n;
        memcpy(p, s->bases + offset, len); p += len; *p++ = '\n';
        memcpy(p, header, n); *p = '+'; p += n;
        for (uint32_t j = 0; j < len; ++j) {
            unsigned q = s->quality[offset + j];
            p[j] = (char)(33 + (q < 93 ? q : 93));
        }
        p += len; *p++ = '\n';
        b->len = p - b->data;
        offset += len;
    }
}
static void process(Worker *w, uint64_t chunk) {
    if (interrupted) fail("interrupted");
    for (int i = 0; i < STREAMS; ++i) w->raw[i].len = w->compressed[i].len = 0;
    uint64_t start = chunk * CHUNK_ROWS, end = start + CHUNK_ROWS;
    if (end > state.count) end = state.count;
    for (uint64_t j = start; j < end; ++j) {
        Spot s;
        int64_t row = state.first + (int64_t)j;
        reader_spot(w->reader, row, &s);
        format(w, row, &s);
    }
    for (int i = 0; i < STREAMS; ++i) {
        Buffer *raw = &w->raw[i], *zip = &w->compressed[i];
        if (!raw->len) continue;
        reserve(zip, libdeflate_gzip_compress_bound(w->compressor, raw->len));
        zip->len = libdeflate_gzip_compress(w->compressor, raw->data, raw->len, zip->data, zip->cap);
        if (!zip->len) fail("gzip compression failed");
    }
}
static void *work(void *arg) {
    Worker *w = arg;
    for (uint64_t j = w->index; j < state.chunks; j += state.workers) {
        pthread_mutex_lock(&state.mutex);
        while (w->ready) pthread_cond_wait(&state.cond, &state.mutex);
        pthread_mutex_unlock(&state.mutex);
        process(w, j);
        pthread_mutex_lock(&state.mutex);
        w->ready = true;
        pthread_cond_broadcast(&state.cond);
        pthread_mutex_unlock(&state.mutex);
    }
    return NULL;
}
static void write_chunk(Worker *w) {
    for (int i = 0; i < STREAMS; ++i) {
        Buffer *b = &w->compressed[i];
        if (!b->len) continue;
        if (output[i].fd < 0) {
            int n = snprintf(output[i].temp, PATH_MAX, "%s/.%s.%d.XXXXXX", state.outdir, state.accession, i);
            if (n < 0 || n >= PATH_MAX) fail("output path too long");
            output[i].fd = mkstemp(output[i].temp);
            if (output[i].fd < 0) fail("create output: %s", strerror(errno));
        }
        size_t pos = 0;
        while (pos < b->len) {
            ssize_t n = write(output[i].fd, b->data + pos, b->len - pos);
            if (n < 0 && errno == EINTR && !interrupted) continue;
            if (n <= 0) fail("write output: %s", strerror(errno));
            pos += (size_t)n;
        }
    }
}
static unsigned number(const char *s, unsigned lo, unsigned hi, const char *label) {
    char *end;
    errno = 0;
    unsigned long n = strtoul(s, &end, 10);
    if (errno || !*s || *end || n < lo || n > hi) fail("%s must be %u..%u", label, lo, hi);
    return (unsigned)n;
}
static void on_signal(int sig) { interrupted = sig; }
static void usage(void) {
    puts("Usage: fasteztq-dump LOCAL_SRA -O OUTPUT_DIR [-e THREADS] [--memory-mib 1900] [-l LEVEL]\n"
         "Direct ordered gzip FASTQ, matching fasterq-dump 3.2.1 --split-files.\n"
         "Threads: 1..64, default 8 (includes main writer); memory: 256..2048 MiB.\n"
         "Compression: libdeflate level 1..12, default 1. Existing outputs are preserved.");
}
int main(int argc, char **argv) {
    unsigned threads = 8, memory = 1900, level = 1;
    state.outdir = ".";
    static const struct option opts[] = {{"threads",1,NULL,'e'},{"outdir",1,NULL,'O'},{"memory-mib",1,NULL,'m'},
        {"level",1,NULL,'l'},{"help",0,NULL,'h'},{"version",0,NULL,'v'},{NULL,0,NULL,0}};
    int c;
    while ((c = getopt_long(argc, argv, "e:O:l:hv", opts, NULL)) != -1) {
        switch (c) {
        case 'e': threads = number(optarg, 1, 64, "threads"); break;
        case 'O': state.outdir = optarg; break;
        case 'm': memory = number(optarg, 256, 2048, "memory-mib"); break;
        case 'l': level = number(optarg, 1, 12, "level"); break;
        case 'h': usage(); return 0;
        case 'v': puts("fasteztq-dump 0.1.0; ncbi-vdb 3.2.1; libdeflate " LIBDEFLATE_VERSION_STRING); return 0;
        default: return 2;
        }
    }
    if (optind + 1 != argc) { usage(); return 2; }
    struct stat st;
    if (stat(argv[optind], &st) || !S_ISREG(st.st_mode)) fail("input must be an existing local SRA archive");
    char *path = realpath(argv[optind], NULL);
    if (!path) fail("resolve input: %s", strerror(errno));
    struct rlimit lim = {.rlim_cur = memory * MIB, .rlim_max = memory * MIB};
    if (setrlimit(RLIMIT_AS, &lim)) fail("set memory limit: %s", strerror(errno));
    mallopt(M_ARENA_MAX, threads < 16 ? threads : 16);
    if (mkdir(state.outdir, 0777) && errno != EEXIST) fail("create output directory: %s", strerror(errno));
    state.accession = strdup(strrchr(path, '/') + 1);
    if (!state.accession) fail("out of memory");
    size_t n = strlen(state.accession);
    if (n > 8 && !strcmp(state.accession + n - 8, ".sralite")) state.accession[n - 8] = 0;
    else if (n > 4 && !strcmp(state.accession + n - 4, ".sra")) state.accession[n - 4] = 0;
    for (int i = 0; i < STREAMS; ++i) {
        output[i].fd = -1;
        char suffix[16] = "";
        if (i) snprintf(suffix, sizeof suffix, "_%d", i);
        int written = snprintf(output[i].final, PATH_MAX, "%s/%s%s.fastq.gz", state.outdir, state.accession, suffix);
        if (written < 0 || written >= PATH_MAX) fail("output path too long");
        if (lstat(output[i].final, &st) == 0) fail("output already exists: %s", output[i].final);
        if (errno != ENOENT) fail("inspect output: %s", strerror(errno));
    }
    atexit(cleanup);
    signal(SIGINT, on_signal); signal(SIGTERM, on_signal);
    state.workers = threads > 1 ? threads - 1 : 1;
    Worker *workers = calloc(state.workers, sizeof *workers);
    pthread_t *tids = allocate(state.workers * sizeof *tids);
    if (!workers) fail("out of memory");
    for (unsigned i = 0; i < state.workers; ++i) {
        workers[i].reader = reader_open(path);
        workers[i].index = i;
        workers[i].compressor = libdeflate_alloc_compressor(level);
        if (!workers[i].compressor) fail("allocate compressor");
    }
    reader_range(workers[0].reader, &state.first, &state.count);
    if (state.first < 1 || state.count > INT64_MAX - (uint64_t)state.first) fail("invalid spot range");
    state.chunks = (state.count + CHUNK_ROWS - 1) / CHUNK_ROWS;
    if (threads > 1) {
        for (unsigned i = 0; i < state.workers; ++i) {
            int rc = pthread_create(&tids[i], NULL, work, &workers[i]);
            if (rc) fail("create worker: %s", strerror(rc));
        }
    }
    for (uint64_t j = 0; j < state.chunks; ++j) {
        Worker *w = &workers[j % state.workers];
        if (threads == 1) process(w, j);
        else {
            pthread_mutex_lock(&state.mutex);
            while (!w->ready) pthread_cond_wait(&state.cond, &state.mutex);
            pthread_mutex_unlock(&state.mutex);
        }
        write_chunk(w);
        if (threads > 1) {
            pthread_mutex_lock(&state.mutex);
            w->ready = false;
            pthread_cond_broadcast(&state.cond);
            pthread_mutex_unlock(&state.mutex);
        }
    }
    for (unsigned i = 0; i < state.workers; ++i) {
        if (threads > 1) pthread_join(tids[i], NULL);
        reader_close(workers[i].reader);
        libdeflate_free_compressor(workers[i].compressor);
        for (int s = 0; s < STREAMS; ++s) { free(workers[i].raw[s].data); free(workers[i].compressed[s].data); }
    }
    if (interrupted) fail("interrupted");
    for (int i = 0; i < STREAMS; ++i) if (output[i].fd >= 0) {
        if (close(output[i].fd)) fail("close output: %s", strerror(errno));
        if (link(output[i].temp, output[i].final)) fail("publish output: %s", strerror(errno));
        output[i].published = true;
        if (unlink(output[i].temp)) fail("remove temporary link: %s", strerror(errno));
    }
    complete = true;
    fprintf(stderr, "spots=%llu threads=%u memory_limit_mib=%u\n", (unsigned long long)state.count, threads, memory);
    free(workers); free(tids); free(path); free(state.accession);
    return 0;
}
