ifeq ($(origin CC),default)
CC = gcc
endif
ifeq ($(origin CXX),default)
CXX = g++
endif
BUILD ?= build/gcc
VDB_SRC ?= deps/ncbi-vdb-3.2.1
CFLAGS ?= -O3 -DNDEBUG
CPPFLAGS ?=
LDFLAGS ?=
VDB_FLAGS ?=
JOBS ?= 16
VDB_LIB = $(BUILD)/vdb/lib/libncbi-vdb.a
INCLUDES = -I$(VDB_SRC)/interfaces -I$(VDB_SRC)/interfaces/cc/gcc/x86_64
OBJECTS = $(BUILD)/main.o $(BUILD)/reader.o

.PHONY: all deps clean
all: $(BUILD)/fasteztq-dump
deps:
	python3 scripts/fetch_dependencies.py
$(VDB_SRC)/CMakeLists.txt:
	python3 scripts/fetch_dependencies.py
$(VDB_LIB): $(VDB_SRC)/CMakeLists.txt
	cmake -S $(VDB_SRC) -B $(BUILD)/vdb -DCMAKE_BUILD_TYPE=Release -DLIBS_ONLY=ON -DCMAKE_C_COMPILER=$(CC) -DCMAKE_CXX_COMPILER=$(CXX) -DCMAKE_C_FLAGS="$(VDB_FLAGS)" -DCMAKE_CXX_FLAGS="$(VDB_FLAGS)"
	cmake --build $(BUILD)/vdb --target ncbi-vdb -j $(JOBS)
$(BUILD)/%.o: src/%.c src/reader.h $(VDB_SRC)/CMakeLists.txt
	@mkdir -p $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) -std=c11 -Wall -Wextra -Wpedantic -pthread $(INCLUDES) -c $< -o $@
$(BUILD)/fasteztq-dump: $(OBJECTS) $(VDB_LIB)
	$(CC) $(LDFLAGS) -o $@ $(OBJECTS) $(VDB_LIB) -ldeflate -lstdc++ -lm -ldl -pthread
clean:
	rm -rf $(BUILD)

$(BUILD)/vdb/lib/libncbi-wvdb.a: $(VDB_LIB)
	cmake --build $(BUILD)/vdb --target ncbi-wvdb -j $(JOBS)
$(BUILD)/make_fixture: tests/make_fixture.c $(BUILD)/vdb/lib/libncbi-wvdb.a
	$(CC) $(CPPFLAGS) $(CFLAGS) $(INCLUDES) $< $(BUILD)/vdb/lib/libncbi-wvdb.a -lstdc++ -lm -ldl -pthread -o $@
.PHONY: check
check: all $(BUILD)/make_fixture
	python3 -m unittest discover -s tests -p 'test_compare.py'
	python3 tests/test_conversion.py --build $(BUILD)
