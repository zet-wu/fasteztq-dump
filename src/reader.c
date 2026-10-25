#include "reader.h"
#include <stdlib.h>
#include <string.h>
#include <vdb/manager.h>
#include <vdb/database.h>
#include <vdb/table.h>
#include <vdb/cursor.h>
#include <vdb/vdb-priv.h>
#include <kdb/manager.h>
#include <klib/namelist.h>

enum { READ, QUALITY, LENGTH, TYPE, NAME, NCOLS };
struct Reader {
    const VDBManager *manager;
    const VDatabase *db;
    const VTable *table;
    const VCursor *cursor;
    uint32_t col[NCOLS];
    bool has_name;
};
static void check(rc_t rc, const char *op) {
    if (rc) fail("VDB %s: rc=0x%08x", op, rc);
}
static bool contains(const KNamelist *list, const char *s) {
    uint32_t n;
    check(KNamelistCount(list, &n), "column count");
    for (uint32_t i = 0; i < n; ++i) {
        const char *name;
        check(KNamelistGet(list, i, &name), "column name");
        if (!strcmp(name, s)) return true;
    }
    return false;
}
Reader *reader_open(const char *path) {
    Reader *r = calloc(1, sizeof *r);
    if (!r) fail("out of memory opening reader");
    check(VDBManagerMakeRead(&r->manager, NULL), "manager");
    check(VDBManagerDisablePagemapThread(r->manager), "disable pagemap thread");
    int type = VDBManagerPathType(r->manager, "%s", path) & ~kptAlias;
    if (type == kptDatabase) {
        check(VDBManagerOpenDBRead(r->manager, &r->db, NULL, "%s", path), "open database");
        KNamelist *tables;
        check(VDatabaseListTbl(r->db, &tables), "list tables");
        uint32_t n;
        check(KNamelistCount(tables, &n), "table count");
        for (uint32_t i = 0; i < n; ++i) {
            const char *name;
            check(KNamelistGet(tables, i, &name), "table name");
            if (strcmp(name, "SEQUENCE") && strcmp(name, "QUAL_STAT"))
                fail("unsupported table %s: reference/alignment inputs are outside the supported scope", name);
        }
        KNamelistRelease(tables);
        check(VDatabaseOpenTableRead(r->db, &r->table, "SEQUENCE"), "open SEQUENCE");
    } else if (type == kptTable || type == kptPrereleaseTbl) {
        check(VDBManagerOpenTableRead(r->manager, &r->table, NULL, "%s", path), "open table");
    } else fail("input is not a readable local SRA table/database (type %d)", type);
    KNamelist *columns;
    check(VTableListReadableColumns(r->table, &columns), "list readable columns");
    r->has_name = contains(columns, "NAME");
    KNamelistRelease(columns);
    check(VTableCreateCachedCursorRead(r->table, &r->cursor, 8 * 1024 * 1024), "cursor");
    static const char *names[] = {"(INSDC:dna:text)READ", "(INSDC:quality:phred)QUALITY", "READ_LEN", "READ_TYPE", "NAME"};
    for (int i = 0; i < NCOLS; ++i)
        if (i != NAME || r->has_name) check(VCursorAddColumn(r->cursor, &r->col[i], "%s", names[i]), names[i]);
    check(VCursorOpen(r->cursor), "open cursor");
    return r;
}
void reader_close(Reader *r) {
    VCursorRelease(r->cursor);
    VTableRelease(r->table);
    VDatabaseRelease(r->db);
    VDBManagerRelease(r->manager);
    free(r);
}
void reader_range(Reader *r, int64_t *first, uint64_t *count) {
    check(VCursorIdRange(r->cursor, r->col[READ], first, count), "row range");
}
bool reader_has_name(Reader *r) { return r->has_name; }
static const void *cell(Reader *r, int col, int64_t row, uint32_t bits, uint32_t *len) {
    const void *base;
    uint32_t actual_bits, offset;
    rc_t rc = VCursorCellDataDirect(r->cursor, row, r->col[col], &actual_bits, &base, &offset, len);
    if (rc) fail("row %lld column %d: decode error 0x%08x", (long long)row, col, rc);
    if (bits != actual_bits || offset) fail("row %lld column %d: unexpected cell representation", (long long)row, col);
    return base;
}
void reader_spot(Reader *r, int64_t row, Spot *s) {
    uint32_t nq, nt;
    s->bases = cell(r, READ, row, 8, &s->bases_len);
    s->quality = cell(r, QUALITY, row, 8, &nq);
    s->lengths = cell(r, LENGTH, row, 32, &s->nreads);
    s->types = cell(r, TYPE, row, 8, &nt);
    if (s->nreads < 1 || s->nreads > 2 || nt != s->nreads)
        fail("row %lld: supported layout is one or two biological reads", (long long)row);
    uint64_t total = 0;
    for (uint32_t i = 0; i < s->nreads; ++i) {
        if (!(s->types[i] & 1) || !s->lengths[i])
            fail("row %lld read %u: technical/empty reads are unsupported", (long long)row, i + 1);
        total += s->lengths[i];
    }
    if (total != s->bases_len || nq != s->bases_len)
        fail("row %lld: READ_LEN, READ and QUALITY lengths disagree", (long long)row);
    s->name = NULL;
    s->name_len = 0;
    if (r->has_name) s->name = cell(r, NAME, row, 8, &s->name_len);
}
