ifeq ($(origin CC),default)
CC = gcc
endif
ifeq ($(origin CXX),default)
CXX = g++
endif
BUILD ?= build/gcc
VDB_SRC ?= deps/ncbi-vdb-3.2.1
ISAL_SRC ?= deps/isa-l-2.31.0
CFLAGS ?= -O3 -DNDEBUG
CPPFLAGS ?=
LDFLAGS ?=
VDB_FLAGS ?=
JOBS ?= 16
VDB_LIB = $(BUILD)/vdb/lib/libncbi-vdb.a
ISAL_LIB = $(BUILD)/isal/libisal.a
INCLUDES = -I$(VDB_SRC)/interfaces -I$(VDB_SRC)/interfaces/cc/gcc/x86_64 -I$(ISAL_SRC)/include
OBJECTS = $(BUILD)/main.o $(BUILD)/reader.o $(BUILD)/gzip.o

.PHONY: all deps clean check
all: $(BUILD)/fasteztq-dump
deps:
	python3 scripts/fetch_dependencies.py
$(VDB_SRC)/CMakeLists.txt $(ISAL_SRC)/Makefile.unx &:
	python3 scripts/fetch_dependencies.py
$(VDB_LIB): $(VDB_SRC)/CMakeLists.txt
	cmake -S $(VDB_SRC) -B $(BUILD)/vdb -DCMAKE_BUILD_TYPE=Release -DLIBS_ONLY=ON -DCMAKE_C_COMPILER=$(CC) -DCMAKE_CXX_COMPILER=$(CXX) -DCMAKE_C_FLAGS="$(VDB_FLAGS)" -DCMAKE_CXX_FLAGS="$(VDB_FLAGS)" -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
	cmake --build $(BUILD)/vdb --target ncbi-vdb -j $(JOBS)
$(ISAL_LIB): $(ISAL_SRC)/Makefile.unx
	@mkdir -p $(BUILD)/isal
	$(MAKE) -C $(ISAL_SRC) -f Makefile.unx -j$(JOBS) CC="$(CC)" O="$(abspath $(BUILD)/isal/obj)" lib_name="$(abspath $(ISAL_LIB))" 'CFLAGS=$(CFLAGS) $$(INCLUDE) -D$$(host_cpu) $$(DEFINES)' lib
$(BUILD)/%.o: src/%.c src/reader.h src/common.h src/gzip.h $(VDB_SRC)/CMakeLists.txt $(ISAL_SRC)/Makefile.unx
	@mkdir -p $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) -std=c11 -Wall -Wextra -Wpedantic -pthread $(INCLUDES) -c $< -o $@
$(BUILD)/fasteztq-dump: $(OBJECTS) $(VDB_LIB) $(ISAL_LIB)
	$(CC) $(LDFLAGS) -o $@ $(OBJECTS) $(VDB_LIB) $(ISAL_LIB) -lstdc++ -lm -ldl -pthread
clean:
	rm -rf $(BUILD)

$(BUILD)/vdb/lib/libncbi-wvdb.a: $(VDB_LIB)
	cmake --build $(BUILD)/vdb --target ncbi-wvdb -j $(JOBS)
$(BUILD)/make_fixture: tests/make_fixture.c $(BUILD)/vdb/lib/libncbi-wvdb.a
	$(CC) $(CPPFLAGS) $(CFLAGS) $(INCLUDES) $< $(BUILD)/vdb/lib/libncbi-wvdb.a -lstdc++ -lm -ldl -pthread -o $@
check: all $(BUILD)/make_fixture
	python3 -m unittest discover -s tests -p 'test_compare.py'
	python3 tests/test_conversion.py --build $(BUILD)
