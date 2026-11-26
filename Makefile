CC ?= gcc
CFLAGS = -O1 -Wall -pthread
all: bin/cpu_prog bin/mem_prog bin/io_prog
bin/%: src/%.c src/common.h
	@mkdir -p bin
	$(CC) $(CFLAGS) -o $@ $<
clean:
	rm -rf bin
