/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Development-only small VDB fixture generator. */
#include <vdb/manager.h>
#include <vdb/schema.h>
#include <vdb/table.h>
#include <vdb/database.h>
#include <vdb/cursor.h>
#include <vdb/vdb-priv.h>
#include <kdb/manager.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(call) do { rc_t rc = (call); if (rc) { fprintf(stderr, "%s: 0x%x\n", #call, rc); exit(1); } } while (0)
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    const char *mode = argv[2];
    int long_reads = !strcmp(mode, "long");
    unsigned rows = !strcmp(mode, "late-technical") ? 200000 : (long_reads ? 16384 : 20000);
    VDBManager *mgr;
    VSchema *schema;
    VTable *table;
    VCursor *cursor;
    CHECK(VDBManagerMakeUpdate(&mgr, NULL));
    CHECK(VDBManagerDisablePagemapThread(mgr));
    CHECK(VDBManagerDisableFlushThread(mgr));
    CHECK(VDBManagerMakeSchema(mgr, &schema));
    char text[2048];
    snprintf(text, sizeof text,
        "version 1; typedef ascii INSDC:dna:text; typedef U8 INSDC:quality:phred; "
        "table Test:Reads #1 { column INSDC:dna:text READ; column INSDC:quality:phred QUALITY; "
        "column U32 READ_LEN; column U8 READ_TYPE; %s "
        "readonly column U64 BASE_COUNT = 40000; readonly column U64 BIO_BASE_COUNT = 40000; "
        "readonly column U64 SPOT_COUNT = %u; }; "
        "database Test:DB #1 { table Test:Reads #1 SEQUENCE; table Test:Reads #1 REFERENCE; };",
        !strcmp(mode, "no-name") ? "" : "column ascii NAME;", rows);
    CHECK(VSchemaParseText(schema, "fixture", text, strlen(text)));
    VDatabase *db = NULL;
    if (!strcmp(mode, "reference")) {
        CHECK(VDBManagerCreateDB(mgr, &db, schema, "Test:DB#1", kcmCreate, "%s", argv[1]));
        VTable *ref;
        CHECK(VDatabaseCreateTable(db, &ref, "REFERENCE", kcmCreate, "REFERENCE"));
        CHECK(VTableRelease(ref));
        CHECK(VDatabaseCreateTable(db, &table, "SEQUENCE", kcmCreate, "SEQUENCE"));
    } else CHECK(VDBManagerCreateTable(mgr, &table, schema, "Test:Reads#1", kcmCreate, "%s", argv[1]));
    CHECK(VTableCreateCursorWrite(table, &cursor, kcmInsert));
    const char *cols[] = {"READ", "QUALITY", "READ_LEN", "READ_TYPE", "NAME"};
    uint32_t ids[5];
    int ncols = !strcmp(mode, "no-name") ? 4 : 5;
    for (int i = 0; i < ncols; ++i) CHECK(VCursorAddColumn(cursor, &ids[i], "%s", cols[i]));
    CHECK(VCursorOpen(cursor));
    char long_read[4096];
    uint8_t long_quality[4096];
    memset(long_read, 'A', sizeof long_read);
    memset(long_quality, 30, sizeof long_quality);
    for (unsigned row = 1; row <= rows; ++row) {
        unsigned nr = !strcmp(mode, "mixed") ? 1 + (row % 2) : 2;
        uint32_t len[] = {row % 3 + 1, row % 5 + 1, 1};
        if (long_reads) len[0] = len[1] = 2048;
        uint8_t type[] = {1, 1, 1};
        if (row == 180000 && !strcmp(mode, "late-technical")) type[1] = 0;
        /* Errors after a complete chunk exercise partial-output cleanup. */
        if (row == 18000) {
            if (!strcmp(mode, "technical")) type[1] = 0;
            if (!strcmp(mode, "empty")) len[0] = 0;
            if (!strcmp(mode, "three")) nr = 3;
        }
        unsigned total = len[0] + (nr > 1 ? len[1] : 0) + (nr > 2 ? len[2] : 0);
        const char *read = "ACGTNACGTN";
        uint8_t q[10] = {0, 3, 30, 40, 93, 94, 255, 20, 2, 1};
        unsigned nq = total - (row == 18000 && !strcmp(mode, "bad-quality"));
        CHECK(VCursorOpenRow(cursor));
        CHECK(VCursorWrite(cursor, ids[0], 8, long_reads ? long_read : read, 0, total));
        CHECK(VCursorWrite(cursor, ids[1], 8, long_reads ? long_quality : q, 0, nq));
        CHECK(VCursorWrite(cursor, ids[2], 32, len, 0, nr));
        CHECK(VCursorWrite(cursor, ids[3], 8, type, 0, nr));
        if (ncols == 5) {
            char name[40];
            int n = snprintf(name, sizeof name, "instrument:%u", row);
            CHECK(VCursorWrite(cursor, ids[4], 8, name, 0, row % 7 ? (unsigned)n : 0));
        }
        CHECK(VCursorCommitRow(cursor));
        CHECK(VCursorCloseRow(cursor));
    }
    CHECK(VCursorCommit(cursor));
    CHECK(VCursorRelease(cursor));
    CHECK(VTableRelease(table));
    CHECK(VDatabaseRelease(db));
    CHECK(VSchemaRelease(schema));
    CHECK(VDBManagerRelease(mgr));
    return 0;
}
