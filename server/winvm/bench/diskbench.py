#!/usr/bin/env python3
"""Disk speed check without fio: sequential 1 MiB and random 4 KiB, O_DIRECT (no page cache), standard library only.

    python3 diskbench.py /data/winvm-bench.bin 16 20     # file, size in GiB, seconds per random test

Make the file bigger than any controller cache (a RAID card can hold several GB) or random reads hit the cache.
The file is deleted at the end.
"""
import mmap
import os
import random
import sys
import threading
import time

MIB = 1 << 20
BLK = 4096


def aligned(n):
    return mmap.mmap(-1, n)  # page-aligned, as O_DIRECT needs


def seq_write(path, size):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_DIRECT, 0o600)
    buf = aligned(MIB)
    buf.write(os.urandom(MIB))
    t = time.time()
    for _ in range(size // MIB):
        os.write(fd, buf)
    os.fsync(fd)
    os.close(fd)
    return size / MIB / (time.time() - t)


def seq_read(path, size):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECT)
    buf = aligned(MIB)
    t = time.time()
    done = 0
    while done < size:
        n = os.readv(fd, [buf])
        if n <= 0:
            break
        done += n
    os.close(fd)
    return done / MIB / (time.time() - t)


def rand(path, size, secs, threads, write):
    blocks = size // BLK
    counts = [0] * threads
    lat = [[] for _ in range(threads)]
    stop = time.time() + secs

    def worker(i):
        fd = os.open(path, (os.O_RDWR if write else os.O_RDONLY) | os.O_DIRECT)
        buf = aligned(BLK)
        if write:
            buf.write(os.urandom(BLK))
        r = random.Random(i)
        while time.time() < stop:
            off = r.randrange(blocks) * BLK
            t0 = time.perf_counter()
            if write:
                os.pwritev(fd, [buf], off)
            else:
                os.preadv(fd, [buf], off)
            lat[i].append(time.perf_counter() - t0)
            counts[i] += 1
        if write:
            os.fsync(fd)
        os.close(fd)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
    t = time.time()
    for x in ts:
        x.start()
    for x in ts:
        x.join()
    el = time.time() - t
    all_lat = sorted(v for l in lat for v in l)
    p50 = all_lat[len(all_lat) // 2] * 1000 if all_lat else 0
    p99 = all_lat[int(len(all_lat) * 0.99)] * 1000 if all_lat else 0
    return sum(counts) / el, p50, p99


def main():
    path, gib, secs = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    size = int(gib * 1024) * MIB
    print(f"{path}: {gib:g} GiB file, {secs:g} s per random test")
    print(f"seq write 1MiB: {seq_write(path, size):.0f} MB/s")
    print(f"seq read  1MiB: {seq_read(path, size):.0f} MB/s")
    for write in (False, True):
        for qd in (1, 16):
            iops, p50, p99 = rand(path, size, secs, qd, write)
            print(f"rand {'write' if write else 'read '} 4k QD{qd:<2}: {iops:8.0f} IOPS  p50 {p50:6.2f} ms  p99 {p99:7.2f} ms")
    os.unlink(path)


if __name__ == "__main__":
    main()
