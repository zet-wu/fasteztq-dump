ifeq ($(origin CC),default)
CC = gcc
endif
ifeq ($(origin CXX),default)
CXX = g++
endif
BUILD ?= build/gcc
VDB_SRC ?= deps/ncbi-vdb-3.2.1
ISAL_SRC ?= deps/isa-l-2.31.0
DEFLATE_SRC ?= deps/libdeflate-1.22
CFLAGS ?= -O3 -DNDEBUG
CPPFLAGS ?=
LDFLAGS ?=
VDB_FLAGS ?=
JOBS ?= 16
VDB_LIB = $(BUILD)/vdb/lib/libncbi-vdb.a
ISAL_LIB = $(BUILD)/isal/libisal.a
DEFLATE_LIB = $(BUILD)/libdeflate/libdeflate.a
INCLUDES = -I$(VDB_SRC)/interfaces -I$(VDB_SRC)/interfaces/cc/gcc/x86_64 -I$(ISAL_SRC)/include -I$(DEFLATE_SRC) -I$(VDB_SRC)/libs/kfs/unix
INDEX_WRAP = -Wl,--wrap=KRIndexMakeRead,--wrap=KMMapMakeRead
OBJECTS = $(BUILD)/main.o $(BUILD)/reader.o $(BUILD)/gzip.o $(BUILD)/index_mmap.o

.PHONY: all deps clean check
all: $(BUILD)/fasteztq-dump
deps:
	python3 scripts/fetch_dependencies.py
$(VDB_SRC)/CMakeLists.txt $(ISAL_SRC)/Makefile.unx $(DEFLATE_SRC)/CMakeLists.txt &:
	python3 scripts/fetch_dependencies.py
$(VDB_LIB): $(VDB_SRC)/CMakeLists.txt
	cmake -S $(VDB_SRC) -B $(BUILD)/vdb -DCMAKE_BUILD_TYPE=Release -DLIBS_ONLY=ON -DCMAKE_C_COMPILER=$(CC) -DCMAKE_CXX_COMPILER=$(CXX) -DCMAKE_C_FLAGS="$(VDB_FLAGS)" -DCMAKE_CXX_FLAGS="$(VDB_FLAGS)" -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
	cmake --build $(BUILD)/vdb --target ncbi-vdb -j $(JOBS)
$(ISAL_LIB): $(ISAL_SRC)/Makefile.unx
	@mkdir -p $(BUILD)/isal
	$(MAKE) -C $(ISAL_SRC) -f Makefile.unx -j$(JOBS) CC="$(CC)" O="$(abspath $(BUILD)/isal/obj)" lib_name="$(abspath $(ISAL_LIB))" 'CFLAGS=$(CFLAGS) $$(INCLUDE) -D$$(host_cpu) $$(DEFINES)' lib
$(DEFLATE_LIB): $(DEFLATE_SRC)/CMakeLists.txt
	cmake -S $(DEFLATE_SRC) -B $(BUILD)/libdeflate -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=$(CC) -DCMAKE_C_FLAGS="$(CFLAGS)" -DLIBDEFLATE_BUILD_SHARED_LIB=OFF -DLIBDEFLATE_BUILD_GZIP=OFF -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
	cmake --build $(BUILD)/libdeflate --target libdeflate_static -j $(JOBS)
$(BUILD)/%.o: src/%.c src/reader.h src/common.h src/gzip.h src/index_mmap.h $(VDB_SRC)/CMakeLists.txt $(ISAL_SRC)/Makefile.unx $(DEFLATE_SRC)/CMakeLists.txt
	@mkdir -p $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) -std=c11 -Wall -Wextra -Wpedantic -pthread $(INCLUDES) -c $< -o $@
$(BUILD)/fasteztq-dump: $(OBJECTS) $(VDB_LIB) $(ISAL_LIB) $(DEFLATE_LIB)
	$(CC) $(LDFLAGS) $(INDEX_WRAP) -o $@ $(OBJECTS) $(VDB_LIB) $(ISAL_LIB) $(DEFLATE_LIB) -lstdc++ -lm -ldl -pthread
clean:
	rm -rf $(BUILD)

$(BUILD)/vdb/lib/libncbi-wvdb.a: $(VDB_LIB)
	cmake --build $(BUILD)/vdb --target ncbi-wvdb -j $(JOBS)
$(BUILD)/make_fixture: tests/make_fixture.c $(BUILD)/vdb/lib/libncbi-wvdb.a
	$(CC) $(CPPFLAGS) $(CFLAGS) $(INCLUDES) $< $(BUILD)/vdb/lib/libncbi-wvdb.a -lstdc++ -lm -ldl -pthread -o $@
$(BUILD)/test_mappings: tests/test_mappings.c $(BUILD)/index_mmap.o $(VDB_LIB)
	$(CC) $(CPPFLAGS) $(CFLAGS) -Isrc $(INCLUDES) $(INDEX_WRAP) $< $(BUILD)/index_mmap.o $(VDB_LIB) -lstdc++ -lm -ldl -pthread -o $@
check: all $(BUILD)/make_fixture $(BUILD)/test_mappings
	python3 -m unittest discover -s tests -p 'test_compare.py'
	python3 tests/test_conversion.py --build $(BUILD)

$(BUILD)/compression_probe: tests/compression_probe.c $(BUILD)/gzip.o $(ISAL_LIB) $(DEFLATE_LIB) $(VDB_LIB)
	$(CC) $(CPPFLAGS) $(CFLAGS) -Isrc $(INCLUDES) $< $(BUILD)/gzip.o $(ISAL_LIB) $(DEFLATE_LIB) $(VDB_LIB) -o $@
