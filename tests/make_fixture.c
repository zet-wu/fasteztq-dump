/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Small synthetic tables, archived through ncbi-vdb. */
#include <vdb/manager.h>
#include <vdb/schema.h>
#include <vdb/table.h>
#include <vdb/database.h>
#include <vdb/cursor.h>
#include <vdb/vdb-priv.h>
#include <kdb/manager.h>
#include <kfs/toc.h>
#include <kfs/file.h>
#include <klib/vector.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(call) do { rc_t rc = (call); if (rc) { fprintf(stderr, "%s: 0x%x\n", #call, rc); exit(1); } } while (0)

/* Enumerate native files to supply the archive payload order. */
static const KDirectory *archive_directory;
static void CC free_path(void *path, void *data) { (void)data; free(path); }
static rc_t CC collect(const KDirectory *dir, uint32_t type, const char *name, void *data) {
    if ((type & ~kptAlias) == kptFile) {
        char resolved[4096];
        CHECK(KDirectoryResolvePath(dir, true, resolved, sizeof resolved, "%s", name));
        char *path = malloc(strlen(resolved));
        if (!path) { fputs("allocate archive path\n", stderr); exit(1); }
        strcpy(path, resolved + 1);
        CHECK(VectorAppend(data, NULL, path));
    }
    return 0;
}
static rc_t CC order(const KDirectory *dir, Vector *v) {
    (void)dir;
    VectorWhack(v, free_path, NULL);
    VectorInit(v, 0, 16);
    return KDirectoryVisit(archive_directory, true, collect, v, ".");
}
static void archive(const char *table, const char *destination) {
    KDirectory *root;
    const KDirectory *dir;
    const KFile *input;
    KFile *output;
    CHECK(KDirectoryNativeDir(&root));
    CHECK(KDirectoryOpenDirRead(root, &dir, true, "%s", table));
    archive_directory = dir;
    CHECK(KDirectoryOpenTocFileRead(dir, &input, sraAlign4Byte, NULL, NULL, order));
    CHECK(KDirectoryCreateFile(root, &output, false, 0600, kcmCreate, "%s", destination));
    char buffer[65536];
    uint64_t position = 0;
    for (;;) {
        size_t count, written;
        CHECK(KFileRead(input, position, buffer, sizeof buffer, &count));
        if (!count) break;
        CHECK(KFileWriteAll(output, position, buffer, count, &written));
        if (written != count) { fputs("short archive write\n", stderr); exit(1); }
        position += count;
    }
    CHECK(KFileRelease(output));
    CHECK(KFileRelease(input));
    CHECK(KDirectoryRelease(dir));
    CHECK(KDirectoryRelease(root));
}

int main(int argc, char **argv) {
    if (argc != 6) {
        fputs("usage: make_fixture TABLE ARCHIVE MODE ROWS SCHEMA_DIRECTORY\n", stderr);
        return 2;
    }
    const char *mode = argv[3];
    unsigned rows = (unsigned)strtoul(argv[4], NULL, 10);
    bool lite = !strcmp(mode, "lite");
    bool database = !strcmp(mode, "database") || !strcmp(mode, "reference");
    bool names = strcmp(mode, "no-name") != 0;
    VDBManager *manager;
    VSchema *schema;
    VTable *table;
    VCursor *cursor;
    CHECK(VDBManagerMakeUpdate(&manager, NULL));
    CHECK(VDBManagerDisablePagemapThread(manager));
    CHECK(VDBManagerDisableFlushThread(manager));
    CHECK(VDBManagerMakeSchema(manager, &schema));
    CHECK(VSchemaAddIncludePath(schema, "%s", argv[5]));
    char text[2048];
    snprintf(text, sizeof text,
        "version 1; include 'ncbi/seq.vschema'; "
        "table Test:Reads #1 { column INSDC:dna:text READ; "
        "column INSDC:coord:len READ_LEN; column INSDC:SRA:xread_type READ_TYPE; %s %s }; "
        "database Test:DB #1 { table Test:Reads #1 SEQUENCE; table Test:Reads #1 REFERENCE; };",
        names ? "column ascii NAME;" : "",
        lite ? "column INSDC:coord:zero READ_START; column INSDC:SRA:read_filter READ_FILTER; "
               "readonly column INSDC:quality:phred QUALITY = "
               "NCBI:SRA:syn_quality_read < 30, 3 > ( READ_START, READ_LEN, READ_TYPE, READ_FILTER );"
             : "column INSDC:quality:phred QUALITY;");
    CHECK(VSchemaParseText(schema, "fixture", text, strlen(text)));
    VDatabase *db = NULL;
    if (database) {
        CHECK(VDBManagerCreateDB(manager, &db, schema, "Test:DB#1", kcmCreate, "%s", argv[1]));
        if (!strcmp(mode, "reference")) {
            VTable *ref;
            CHECK(VDatabaseCreateTable(db, &ref, "REFERENCE", kcmCreate, "REFERENCE"));
            CHECK(VTableRelease(ref));
        }
        CHECK(VDatabaseCreateTable(db, &table, "SEQUENCE", kcmCreate, "SEQUENCE"));
    } else CHECK(VDBManagerCreateTable(manager, &table, schema, "Test:Reads#1", kcmCreate, "%s", argv[1]));
    CHECK(VTableCreateCursorWrite(table, &cursor, kcmInsert));
    uint32_t read_col, quality_col = 0, lengths_col, types_col, name_col = 0, start_col = 0, filter_col = 0;
    CHECK(VCursorAddColumn(cursor, &read_col, "READ"));
    CHECK(VCursorAddColumn(cursor, &lengths_col, "READ_LEN"));
    CHECK(VCursorAddColumn(cursor, &types_col, "READ_TYPE"));
    if (names) CHECK(VCursorAddColumn(cursor, &name_col, "NAME"));
    if (lite) {
        CHECK(VCursorAddColumn(cursor, &start_col, "READ_START"));
        CHECK(VCursorAddColumn(cursor, &filter_col, "READ_FILTER"));
    } else CHECK(VCursorAddColumn(cursor, &quality_col, "QUALITY"));
    CHECK(VCursorOpen(cursor));
    for (unsigned row = 1; row <= rows; ++row) {
        unsigned nr = !strcmp(mode, "single") ? 1 : !strcmp(mode, "mixed") ? 1 + row % 2 : 2;
        uint32_t lengths[] = {row % 3 + 1, row % 5 + 1, 1};
        if (!strcmp(mode, "fixed")) lengths[0] = lengths[1] = 4;
        uint8_t types[] = {1, 1, 1};
        if (row == rows) {
            if (!strcmp(mode, "technical")) types[1] = 0;
            if (!strcmp(mode, "empty")) lengths[0] = 0;
            if (!strcmp(mode, "three")) nr = 3;
        }
        unsigned total = lengths[0] + (nr > 1 ? lengths[1] : 0) + (nr > 2 ? lengths[2] : 0);
        const char *bases = "ACGTNACGTN";
        uint8_t quality[] = {0, 3, 30, 40, 93, 94, 255, 20, 2, 1};
        unsigned nq = total - (row == rows && !strcmp(mode, "bad-quality"));
        CHECK(VCursorOpenRow(cursor));
        CHECK(VCursorWrite(cursor, read_col, 8, bases, 0, total));
        CHECK(VCursorWrite(cursor, lengths_col, 32, lengths, 0, nr));
        CHECK(VCursorWrite(cursor, types_col, 8, types, 0, nr));
        if (lite) {
            uint32_t starts[] = {0, lengths[0]};
            uint8_t filters[] = {row % 2, (row + 1) % 2};
            CHECK(VCursorWrite(cursor, start_col, 32, starts, 0, nr));
            CHECK(VCursorWrite(cursor, filter_col, 8, filters, 0, nr));
        } else CHECK(VCursorWrite(cursor, quality_col, 8, quality, 0, nq));
        if (names) {
            char name[40];
            int n = snprintf(name, sizeof name, "instrument:%u", row);
            CHECK(VCursorWrite(cursor, name_col, 8, name, 0, row % 7 ? (unsigned)n : 0));
        }
        CHECK(VCursorCommitRow(cursor));
        CHECK(VCursorCloseRow(cursor));
    }
    CHECK(VCursorCommit(cursor));
    CHECK(VCursorRelease(cursor));
    CHECK(VTableRelease(table));
    CHECK(VDatabaseRelease(db));
    CHECK(VSchemaRelease(schema));
    CHECK(VDBManagerRelease(manager));
    archive(argv[1], argv[2]);
    return 0;
}
