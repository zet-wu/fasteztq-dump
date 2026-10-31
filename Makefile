# SPDX-License-Identifier: GPL-3.0-or-later
ifeq ($(origin CC),default)
CC = gcc
endif
ifeq ($(origin CXX),default)
CXX = g++
endif
BUILD ?= build/release
VDB_SRC = third_party/ncbi-vdb
CFLAGS ?= -O3 -DNDEBUG
CPPFLAGS ?=
LDFLAGS ?=
VDB_FLAGS ?=
JOBS ?= 4
PYTHON ?= python3
PKG_CONFIG ?= pkg-config
PREFIX ?= /usr/local
BINDIR ?= $(PREFIX)/bin

VDB_LIB = $(BUILD)/vdb/lib/libncbi-vdb.a
WVDB_LIB = $(BUILD)/vdb/lib/libncbi-wvdb.a
COMPRESS_CFLAGS = $(shell $(PKG_CONFIG) --cflags libdeflate libisal)
COMPRESS_LIBS = $(shell $(PKG_CONFIG) --libs libdeflate libisal)
INCLUDES = -I$(VDB_SRC)/interfaces -I$(VDB_SRC)/interfaces/cc/gcc/x86_64 -I$(VDB_SRC)/libs/kfs/unix
INDEX_WRAP = -Wl,--wrap=KRIndexMakeRead,--wrap=KMMapMakeRead
SYSTEM_LIBS = -lstdc++ -lm -ldl -pthread
OBJECTS = $(addprefix $(BUILD)/,main.o reader.o gzip.o index_mmap.o)

.PHONY: all check clean install check-deps
all: $(BUILD)/fasteztq-dump

check-deps:
	$(PKG_CONFIG) --print-errors --exists 'libdeflate >= 1.14' 'libisal >= 2.31.0'

$(BUILD)/vdb/CMakeCache.txt: $(VDB_SRC)/CMakeLists.txt
	cmake -S $(VDB_SRC) -B $(BUILD)/vdb -DCMAKE_BUILD_TYPE=Release -DLIBS_ONLY=ON -DCMAKE_C_COMPILER=$(CC) -DCMAKE_CXX_COMPILER=$(CXX) -DCMAKE_C_FLAGS="$(VDB_FLAGS)" -DCMAKE_CXX_FLAGS="$(VDB_FLAGS)"

$(VDB_LIB): $(BUILD)/vdb/CMakeCache.txt
	+cmake --build $(BUILD)/vdb --target ncbi-vdb -j $(JOBS)

$(WVDB_LIB): $(VDB_LIB)
	+cmake --build $(BUILD)/vdb --target ncbi-wvdb -j $(JOBS)

$(BUILD)/%.o: src/%.c Makefile | check-deps
	@mkdir -p $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(COMPRESS_CFLAGS) -std=c11 -Wall -Wextra -Wpedantic -pthread $(INCLUDES) -MMD -MP -c $< -o $@

$(BUILD)/fasteztq-dump: $(OBJECTS) $(VDB_LIB)
	$(CC) $(LDFLAGS) $(INDEX_WRAP) -o $@ $(OBJECTS) $(VDB_LIB) $(COMPRESS_LIBS) $(SYSTEM_LIBS)

$(BUILD)/make_fixture: tests/make_fixture.c $(WVDB_LIB) Makefile
	$(CC) $(CPPFLAGS) $(CFLAGS) -std=c11 -Wall -Wextra $(INCLUDES) $(LDFLAGS) $< $(WVDB_LIB) $(SYSTEM_LIBS) -o $@

$(BUILD)/test_mappings: tests/test_mappings.c $(BUILD)/index_mmap.o $(VDB_LIB) Makefile
	$(CC) $(CPPFLAGS) $(CFLAGS) -std=c11 -Wall -Wextra -Isrc $(INCLUDES) $(LDFLAGS) $(INDEX_WRAP) $< $(BUILD)/index_mmap.o $(VDB_LIB) $(SYSTEM_LIBS) -o $@

$(BUILD)/fail_write.so: tests/fail_write.c Makefile
	@mkdir -p $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) -shared -fPIC -Wall -Wextra $(LDFLAGS) $< -ldl -o $@

check: all $(BUILD)/make_fixture $(BUILD)/test_mappings $(BUILD)/fail_write.so
	$(PYTHON) tests/test_conversion.py --build $(BUILD)

install: all
	install -d "$(DESTDIR)$(BINDIR)"
	install -m 755 $(BUILD)/fasteztq-dump "$(DESTDIR)$(BINDIR)/fasteztq-dump"

clean:
	rm -rf $(BUILD)

-include $(OBJECTS:.o=.d)
