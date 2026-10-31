/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "reader.h"
#include "common.h"
#include <stdlib.h>
#include <string.h>
#include <vdb/manager.h>
#include <vdb/database.h>
#include <vdb/table.h>
#include <vdb/cursor.h>
#include <vdb/blob.h>
#include <vdb/blob-priv.h>
#include <kdb/page-map.h>
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
    const VBlob *blob[NCOLS];
    int64_t begin[NCOLS], end[NCOLS];
    bool repeated[NCOLS], array[NCOLS];
    bool has_name;
    int path_type;
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
Reader *reader_open(const char *path, const Reader *model) {
    Reader *r = calloc(1, sizeof *r);
    if (!r) fail("out of memory opening reader");
    check(VDBManagerMakeRead(&r->manager, NULL), "manager");
    check(VDBManagerDisablePagemapThread(r->manager), "disable pagemap thread");
    int type = model ? model->path_type : VDBManagerPathType(r->manager, "%s", path) & ~kptAlias;
    r->path_type = type;
    if (type == kptDatabase) {
        check(VDBManagerOpenDBRead(r->manager, &r->db, NULL, "%s", path), "open database");
        if (!model) {
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
        }
        check(VDatabaseOpenTableRead(r->db, &r->table, "SEQUENCE"), "open SEQUENCE");
    } else if (type == kptTable || type == kptPrereleaseTbl) {
        check(VDBManagerOpenTableRead(r->manager, &r->table, NULL, "%s", path), "open table");
    } else fail("input is not a readable local SRA table/database (type %d)", type);
    if (model) r->has_name = model->has_name;
    else {
        KNamelist *columns;
        check(VTableListReadableColumns(r->table, &columns), "list readable columns");
        r->has_name = contains(columns, "NAME");
        KNamelistRelease(columns);
    }
    /* One retained blob per column is sufficient for forward scans. */
    check(VTableCreateCursorRead(r->table, &r->cursor), "cursor");
    static const char *names[] = {"(INSDC:dna:text)READ", "(INSDC:quality:phred)QUALITY", "READ_LEN", "READ_TYPE", "NAME"};
    for (int i = 0; i < NCOLS; ++i)
        if (i != NAME || r->has_name) check(VCursorAddColumn(r->cursor, &r->col[i], "%s", names[i]), names[i]);
    check(VCursorOpen(r->cursor), "open cursor");
    return r;
}
void reader_close(Reader *r) {
    for (int i = 0; i < NCOLS; ++i) VBlobRelease(r->blob[i]);
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
    if (!r->blob[col] || row < r->begin[col] || row > r->end[col]) {
        VBlobRelease(r->blob[col]);
        r->blob[col] = NULL;
        rc_t rc = VCursorGetBlobDirect(r->cursor, &r->blob[col], row, r->col[col]);
        if (rc) fail("row %lld column %d: decode error 0x%08x", (long long)row, col, rc);
        uint64_t count;
        check(VBlobIdRange(r->blob[col], &r->begin[col], &count), "blob range");
        r->end[col] = r->begin[col] + (int64_t)(count - 1);
        const VBlob *blob = r->blob[col];
        if (blob->data.elem_bits != bits || !blob->pm)
            fail("row %lld column %d: unexpected decoded blob representation", (long long)row, col);
        /* These are properties of the decoded page map, not predictions about
           a schema expression. A repeated data record is identical by format. */
        r->repeated[col] = blob->pm->data_recs == 1;
        r->array[col] = !blob->pm->random_access && blob->pm->leng_recs == 1 &&
                        blob->pm->data_recs == blob->pm->row_count;
        if (!r->repeated[col] && count != blob->pm->row_count)
            fail("row %lld column %d: blob/page-map range mismatch", (long long)row, col);
    }
    const VBlob *blob = r->blob[col];
    uint64_t offset;
    if (r->repeated[col] || r->array[col]) {
        *len = blob->pm->length[0];
        offset = r->repeated[col] ? 0 : (uint64_t)(row - r->begin[col]) * *len;
    } else {
        uint32_t off;
        *len = PageMapGetIdxRowInfo(blob->pm, row - r->begin[col], &off, NULL);
        offset = off;
    }
    if (offset + *len > blob->data.elem_count)
        fail("row %lld column %d: cell exceeds decoded blob bounds", (long long)row, col);
    return (const char *)blob->data.base + offset * (bits / 8);
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
