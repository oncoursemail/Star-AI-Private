"""Read a PS3 game the user has on disk -- an ISO 9660 image or an extracted game folder -- in place.

Nothing is copied, extracted, written or downloaded: the ISO reader seeks to the
directory records and file extents it needs. Encrypted contents (SELF/EBOOT.BIN,
encrypted disc regions) are reported as such; STAR has no keys and decrypts nothing.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

SECTOR = 2048
MAX_ENTRIES = 20_000
MAX_DEPTH = 32
MAX_DIR_BYTES = 4 * 1024 * 1024
MAX_LISTED = 60
_EXEC_SUFFIXES = (".self", ".sprx", ".elf", ".prx")
_SFO_KEYS = ("TITLE", "TITLE_ID", "CATEGORY", "APP_VER", "VERSION", "PS3_SYSTEM_VER")


class IsoImage:
    """Minimal read-only ISO 9660 reader (primary volume descriptor, directory records)."""

    def __init__(self, path: Path):
        self.path = path
        self.size = path.stat().st_size
        pvd = self._read(16 * SECTOR, SECTOR)
        if len(pvd) < 190 or pvd[0] != 1 or pvd[1:6] != b"CD001":
            raise ValueError("Not an ISO 9660 image (no primary volume descriptor at sector 16)")
        self.volume_id = pvd[40:72].decode("ascii", "replace").strip()
        self._root = self._record(pvd[156:190])

    def _read(self, offset: int, length: int) -> bytes:
        if offset < 0 or offset + length > self.size:
            raise ValueError("ISO extent lies outside the image")
        with self.path.open("rb") as handle:
            handle.seek(offset)
            return handle.read(length)

    @staticmethod
    def _record(raw: bytes) -> tuple[str, int, int, bool]:
        lba = int.from_bytes(raw[2:6], "little")
        size = int.from_bytes(raw[10:14], "little")
        name = raw[33:33 + raw[32]]
        text = "" if name in (b"\0", b"\1") else name.decode("ascii", "replace").split(";")[0].rstrip(".")
        return text, lba, size, bool(raw[25] & 2)

    def _children(self, lba: int, size: int):
        data = self._read(lba * SECTOR, min(size, MAX_DIR_BYTES))
        pos = 0
        while pos < len(data):
            length = data[pos]
            if length == 0:                       # records never cross sectors; skip padding
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            if length < 34 or pos + length > len(data):
                raise ValueError("Malformed ISO directory record")
            name, child_lba, child_size, is_dir = self._record(data[pos:pos + length])
            pos += length
            if name:
                yield name, child_lba, child_size, is_dir

    def files(self) -> list[tuple[str, int]]:
        """All file paths and sizes, breadth-first, bounded."""
        out: list[tuple[str, int]] = []
        queue = [("", self._root[1], self._root[2], 0)]
        seen = set()
        while queue:
            prefix, lba, size, depth = queue.pop(0)
            if lba in seen or depth > MAX_DEPTH:
                continue
            seen.add(lba)
            for name, child_lba, child_size, is_dir in self._children(lba, size):
                path = f"{prefix}{name}"
                if is_dir:
                    queue.append((path + "/", child_lba, child_size, depth + 1))
                else:
                    out.append((path, child_size))
                if len(out) + len(queue) > MAX_ENTRIES:
                    raise ValueError(f"ISO has more than {MAX_ENTRIES} entries")
        return out

    def read_member(self, member: str, max_bytes: int, head: int | None = None) -> bytes:
        lba, size = self._root[1], self._root[2]
        parts = [p for p in member.replace("\\", "/").split("/") if p]
        if not parts:
            raise ValueError("Name a file inside the ISO")
        for index, part in enumerate(parts):
            for name, child_lba, child_size, is_dir in self._children(lba, size):
                if name.lower() == part.lower() and is_dir == (index < len(parts) - 1):
                    lba, size = child_lba, child_size
                    break
            else:
                raise ValueError(f"{member!r} is not in the ISO")
        if head is None and size > max_bytes:
            raise ValueError(f"ISO member exceeds the {max_bytes}-byte analysis budget")
        return self._read(lba * SECTOR, size if head is None else min(size, head))


def folder_files(root: Path) -> list[tuple[str, int]]:
    """Regular files under an extracted game folder, without following links."""
    out: list[tuple[str, int]] = []
    for current, dirs, names in os.walk(root, followlinks=False):
        base = Path(current)
        dirs[:] = sorted(d for d in dirs if not (base / d).is_symlink())
        for name in sorted(names):
            info = (base / name).lstat()
            if stat.S_ISREG(info.st_mode):
                out.append(((base / name).relative_to(root).as_posix(), info.st_size))
            if len(out) > MAX_ENTRIES:
                raise ValueError(f"Game folder has more than {MAX_ENTRIES} files")
    return out


def classify(head: bytes) -> str:
    if head[:4] == b"SCE\0":
        return "sce_encrypted"
    if head[:4] == b"\x7fELF" and len(head) >= 20:
        machine = int.from_bytes(head[18:20], "big" if head[5] == 2 else "little")
        return {21: "elf_ppu", 23: "elf_spu"}.get(machine, "elf_other")
    return "unknown"


def parse_sfo(data: bytes) -> dict:
    """PARAM.SFO key/value table (title, title ID, versions)."""
    if data[:4] != b"\0PSF" or len(data) < 20:
        raise ValueError("Not a PARAM.SFO file")
    key_table, data_table, count = (int.from_bytes(data[i:i + 4], "little") for i in (8, 12, 16))
    values: dict = {}
    for index in range(min(count, 256)):
        entry = 20 + index * 16
        if entry + 16 > len(data):
            break
        key_off = int.from_bytes(data[entry:entry + 2], "little")
        fmt = int.from_bytes(data[entry + 2:entry + 4], "little")
        length = int.from_bytes(data[entry + 4:entry + 8], "little")
        data_off = int.from_bytes(data[entry + 12:entry + 16], "little")
        start = key_table + key_off
        key = data[start:data.find(b"\0", start)].decode("ascii", "replace")
        if key not in _SFO_KEYS:
            continue
        raw = data[data_table + data_off:data_table + data_off + length]
        values[key] = (int.from_bytes(raw[:4], "little") if fmt == 0x0404
                       else raw.split(b"\0", 1)[0].decode("utf-8", "replace")[:128])
    return values


def scan(files: list[tuple[str, int]], read_head) -> dict:
    """Summarise a game tree: PARAM.SFO fields and every executable with its container kind."""
    executables = []
    sfo: dict | None = None
    for path, size in files:
        leaf = path.rsplit("/", 1)[-1].lower()
        if leaf == "param.sfo" and sfo is None and path.count("/") <= 2:
            try:
                sfo = {"path": path, **parse_sfo(read_head(path, 64 * 1024))}
            except ValueError as exc:
                sfo = {"path": path, "error": str(exc)}
        elif leaf == "eboot.bin" or leaf.endswith(_EXEC_SUFFIXES):
            executables.append({"path": path, "size": size, "kind": classify(read_head(path, 64))})
    kinds: dict[str, int] = {}
    for item in executables:
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    return {
        "file_count": len(files), "param_sfo": sfo, "executable_kinds": kinds,
        "executables": executables[:MAX_LISTED], "executables_omitted": max(0, len(executables) - MAX_LISTED),
        "notes": ("elf_ppu/elf_spu files can go to re_ps3_elf_preflight. sce_encrypted files are SELF containers "
                  "whose contents STAR cannot decrypt; 'unknown' inside an ISO usually means an encrypted disc "
                  "region. Files are read in place; nothing is copied."),
        "read_only": True, "executed": False,
    }
