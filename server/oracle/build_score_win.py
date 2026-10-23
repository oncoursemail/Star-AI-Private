"""Build llama-score.exe on Windows with zig against a llama.cpp release's DLLs (no MSVC needed).

    python server/oracle/build_score_win.py --zig <zig.exe> --bin <release dir with llama.dll> --src <llama.cpp source
        of the SAME build (headers)> --out <release dir>/llama-score.exe

Import libraries are made from the DLLs' export tables (zig dlltool); the tool links only the C API, so mixing the
zig (mingw) runtime with the release's MSVC-ABI DLLs is safe. The exe must sit next to the DLLs it was built for.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import struct
import subprocess
import tempfile

DLLS = ("llama", "ggml", "ggml-base")


def exports(dll: Path) -> list[str]:
    """Names in a PE32+ DLL's export table."""
    data = dll.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError(f"{dll} is not a PE file")
    n_sections = struct.unpack_from("<H", data, pe + 6)[0]
    opt = pe + 24
    if struct.unpack_from("<H", data, opt)[0] != 0x20B:
        raise ValueError(f"{dll} is not 64-bit")
    export_rva = struct.unpack_from("<I", data, opt + 112)[0]
    sections = []
    for i in range(n_sections):
        off = opt + struct.unpack_from("<H", data, pe + 20)[0] + 40 * i
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", data, off + 8)
        sections.append((vaddr, max(vsize, rsize), raddr))

    def at(rva: int) -> int:
        for vaddr, size, raddr in sections:
            if vaddr <= rva < vaddr + size:
                return rva - vaddr + raddr
        raise ValueError("RVA outside every section")

    if not export_rva:
        return []
    base = at(export_rva)
    n_names = struct.unpack_from("<I", data, base + 24)[0]
    names_rva = struct.unpack_from("<I", data, base + 32)[0]
    out = []
    for i in range(n_names):
        name_off = at(struct.unpack_from("<I", data, at(names_rva) + 4 * i)[0])
        out.append(data[name_off:data.index(b"\0", name_off)].decode("ascii"))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zig", required=True)
    ap.add_argument("--bin", required=True, type=Path)
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    here = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory() as tmp:
        libs = []
        for name in DLLS:
            dll = args.bin / f"{name}.dll"
            names = exports(dll)
            defs = Path(tmp) / f"{name}.def"
            defs.write_text(f"LIBRARY {name}.dll\nEXPORTS\n" + "".join(f"  {n}\n" for n in names), encoding="ascii")
            lib = Path(tmp) / f"{name}.lib"
            subprocess.run([args.zig, "dlltool", "-d", str(defs), "-l", str(lib), "-m", "i386:x86-64"], check=True)
            libs.append(str(lib))
        cmd = [args.zig, "c++", "-target", "x86_64-windows-gnu", "-O2", "-std=c++17",
               "-I", str(args.src / "include"), "-I", str(args.src / "ggml" / "include"),
               "-I", str(args.src / "vendor"),
               str(here / "llama_score.cpp"), *libs, "-o", str(args.out)]
        subprocess.run(cmd, check=True)
    print(f"built {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
