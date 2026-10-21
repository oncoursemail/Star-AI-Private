"""Bounded, original ELF load-map preflight; this module performs no I/O.

Format references (retrieved 2026-10-19):
https://gabi.xinuos.com/elf/02-eheader.html
https://gabi.xinuos.com/elf/03-sheader.html
https://gabi.xinuos.com/elf/04-strtab.html
https://gabi.xinuos.com/elf/07-pheader.html

The PS3 candidate profiles (PPU effective addresses and SPU local store) are
scoped to the inspected project's documented runtime, not a complete PS3 ABI:
https://github.com/sp00nznet/ps3recomp/blob/
749182eebb936f086a007f63e1c7d853f3cf708a/docs/RUNTIME.md
No project parser code is imported. In particular, a generic Linux PPC64
function-descriptor layout is not assumed for PS3 .opd metadata.
"""

from __future__ import annotations

import hashlib
import json
import struct

MAX_ELF_BYTES = 64 * 1024 * 1024
MAX_PROGRAM_HEADERS = 1024
MAX_SECTION_HEADERS = 4096
MAX_DETAILS = 24
MAX_REPORT_CHARACTERS = 16000
_KNOWN_NAMES = (b".opd", b".text", b".data", b".bss", b".rodata")
_LEVEL_ORDER = {"error": 0, "blocker": 1, "unsupported": 2, "warning": 3}


class _Report:
    def __init__(self, data: bytes, digest: str, label: str):
        self.data = data
        self.issues: list[dict] = []
        self.result: dict = {
            "evidence_scope": "structural_preflight",
            "runtime_verified": False,
            "source": {"label": label, "sha256": digest, "size_bytes": len(data)},
            "header": None,
            "segments": [],
            "opd": {"present": None, "sections": [], "omitted": 0},
            "entry": None,
        }

    def issue(self, code: str, severity: str, message: str, index: int | None = None):
        item = {"code": code, "severity": severity, "message": message}
        if index is not None:
            item["index"] = index
        self.issues.append(item)

    def finish(self, candidate: bool | None, status: str | None = None) -> dict:
        counts = {level: 0 for level in _LEVEL_ORDER}
        for item in self.issues:
            counts[item["severity"]] += 1
        ordered = sorted(self.issues, key=lambda item: _LEVEL_ORDER[item["severity"]])
        blockers = list(dict.fromkeys(i["code"] for i in ordered if i["severity"] != "warning"))
        valid = False if counts["error"] else None if counts["unsupported"] else True
        self.result.update({
            "status": status or (
                "malformed" if counts["error"] else
                "not_ps3_candidate" if candidate is False else
                "unsupported" if counts["unsupported"] else
                "blocked" if counts["blocker"] else "ready_for_review"
            ),
            "issues": ordered[:MAX_DETAILS],
            "issue_counts": counts,
            "issues_omitted": max(0, len(ordered) - MAX_DETAILS),
            "readiness": {
                "structurally_valid": valid,
                "ps3_candidate": candidate,
                "blockers": blockers[:MAX_DETAILS],
                "blockers_omitted": max(0, len(blockers) - MAX_DETAILS),
                "unknowns": [
                    "Instruction, relocation, import and ABI semantics are not validated.",
                    "An entry value or .opd section is not proof of a callable function.",
                    "Runtime services, graphics, gameplay and portability remain unverified.",
                    "No file was loaded into guest memory or executed.",
                ],
            },
        })
        # Bound the complete response, including pretty JSON and escaped labels.
        # Aggregate counts survive removal of individual records.
        while len(json.dumps(self.result, indent=2)) > MAX_REPORT_CHARACTERS:
            if self.result["segments"]:
                self.result["segments"].pop()
                self.result["segment_summary"]["details_omitted"] += 1
            elif self.result["opd"]["sections"]:
                self.result["opd"]["sections"].pop()
                self.result["opd"]["omitted"] += 1
            elif self.result["entry"] and self.result["entry"]["mapped_to"]:
                self.result["entry"]["mapped_to"].pop()
                self.result["entry"]["mappings_omitted"] += 1
            else:
                self.result["issues"].pop()
                self.result["issues_omitted"] += 1
        return self.result

    def table(self, name: str, offset: int, count: int, stride: int,
              expected: int, maximum: int, header_size: int, address_space: int) -> bool:
        if count > maximum:
            self.issue(name + "_count_limit", "unsupported", "Table count exceeds the bounded parser limit.")
            return False
        if count == 0:
            return True
        if stride != expected:
            self.issue(name + "_entry_size", "error", "Table entry size does not match this ELF class.")
            return False
        if offset < header_size or offset + count * stride > min(len(self.data), address_space):
            self.issue(name + "_table_range", "error", "Table overlaps the ELF header or extends beyond the file/address field.")
            return False
        return True


def _programs(report: _Report, header: dict, endian: str, address_space: int) -> list[dict]:
    bits = header["class_bits"]
    stride = 56 if bits == 64 else 32
    count = header["program_header_count"]
    if count == 0xFFFF:
        report.issue("extended_program_count", "unsupported", "Extended ELF program counts are not interpreted.")
        return []
    if not report.table("program", header["program_header_offset"], count,
                        header["program_header_entry_size"], stride, MAX_PROGRAM_HEADERS,
                        header["header_size"], address_space):
        return []
    loads = []
    for index in range(count):
        fields = struct.unpack_from(endian + ("IIQQQQQQ" if bits == 64 else "IIIIIIII"),
                                    report.data, header["program_header_offset"] + index * stride)
        if bits == 64:
            kind, flags, offset, vaddr, _paddr, filesz, memsz, align = fields
        else:
            kind, offset, vaddr, _paddr, filesz, memsz, flags, align = fields
        if kind == 0:  # PT_NULL members other than p_type are undefined.
            continue
        if filesz and offset + filesz > min(len(report.data), address_space):
            report.issue("segment_file_range", "error", "Segment file bytes extend beyond the input/address field.", index)
        if kind != 1:
            continue
        if filesz > memsz:
            report.issue("load_filesz_exceeds_memsz", "error", "PT_LOAD file size exceeds its memory size.", index)
        end = vaddr + memsz
        if end > address_space:
            report.issue("load_address_overflow", "error", "PT_LOAD memory range overflows its ELF address width.", index)
        if align > 1 and (align & (align - 1)):
            report.issue("load_alignment_power", "error", "PT_LOAD alignment is not zero, one or a power of two.", index)
        elif align > 1 and vaddr % align != offset % align:
            report.issue("load_alignment_congruence", "error", "PT_LOAD guest address and file offset are not congruent.", index)
        if memsz and header["profile"] == "spu_local_store" and end > 256 * 1024:
            report.issue("spu_local_store_overflow", "blocker", "Load region exceeds the 256 KiB SPU local-store profile.", index)
        if memsz and header["profile"] == "ppu_32bit_effective_address" and end > 2**32:
            report.issue("ppu_effective_address_overflow", "blocker", "Load region exceeds the project's 32-bit effective-address profile.", index)
        if flags & 3 == 3:
            report.issue("writable_executable_region", "warning", "Load region requests both write and execute permissions.", index)
        loads.append({
            "index": index, "file_range": [offset, offset + filesz],
            "memory_range": [vaddr, end],
            "file_backed_memory_range": [vaddr, vaddr + filesz] if filesz <= memsz else None,
            "zero_fill_range": [vaddr + filesz, end] if memsz > filesz else None,
            "permissions": "".join(letter for bit, letter in ((4, "R"), (2, "W"), (1, "X")) if flags & bit),
            "region": "executable" if flags & 1 else "data" if flags & 6 else "unspecified",
            "alignment": align,
        })
    previous_end = -1
    overlaps = 0
    for segment in sorted(loads, key=lambda row: row["memory_range"][0]):
        start, end = segment["memory_range"]
        if start == end:
            continue
        if start < previous_end:
            overlaps += 1
            report.issue("load_regions_overlap", "warning", "Load memory regions overlap; page-aligned sharing may be legitimate and requires loader review.", segment["index"])
        if end > previous_end:
            previous_end = end
    # The overlap sweep is O(n log n); it does not emit every overlapping pair.
    report.result["segments"] = loads[:MAX_DETAILS]
    report.result["segment_summary"] = {
        "program_headers_checked": count, "load_regions": len(loads),
        "details_omitted": max(0, len(loads) - MAX_DETAILS),
        "overlapping_regions": overlaps,
    }
    return loads


def _sections(report: _Report, header: dict, endian: str, address_space: int) -> list[dict]:
    count, offset = header["section_header_count"], header["section_header_offset"]
    string_index = header["section_name_table_index"]
    if (count == 0 and offset != 0) or string_index == 0xFFFF:
        report.issue("extended_section_numbering", "unsupported", "Extended ELF section numbering is not interpreted.")
        return []
    if count == 0:
        if string_index != 0:
            report.issue("section_name_table_index", "error", "A section-name table is referenced without a section table.")
        report.result["opd"]["present"] = None  # Stripped files cannot establish absence.
        report.result["section_summary"] = {"headers_checked": 0, "names_available": False}
        return []
    bits = header["class_bits"]
    stride = 64 if bits == 64 else 40
    if not report.table("section", offset, count, header["section_header_entry_size"],
                        stride, MAX_SECTION_HEADERS, header["header_size"], address_space):
        return []
    sections = []
    for index in range(count):
        values = struct.unpack_from(endian + ("IIQQQQIIQQ" if bits == 64 else "IIIIIIIIII"),
                                    report.data, offset + index * stride)
        name, kind, flags, addr, file_offset, size, _link, _info, align, _entsize = values
        sections.append((name, kind, addr, file_offset, size))
        if index == 0 and kind != 0:
            report.issue("section_zero_type", "error", "The first section header must be SHT_NULL.", index)
        if kind == 0:
            continue
        if kind != 8 and size and file_offset + size > min(len(report.data), address_space):
            report.issue("section_file_range", "error", "File-backed section extends beyond the input/address field.", index)
        if flags & 2 and addr + size > address_space:
            report.issue("section_address_overflow", "error", "Allocated section overflows its ELF address width.", index)
        if align > 1 and align & (align - 1):
            report.issue("section_alignment_power", "error", "Section alignment is not zero, one or a power of two.", index)
        elif align > 1 and addr % align:
            report.issue("section_alignment_address", "error", "Section address does not satisfy its declared alignment.", index)
    if string_index >= count:
        report.issue("section_name_table_index", "error", "Section-name string table index is out of range.")
        return []
    named = {name.decode("ascii"): 0 for name in _KNOWN_NAMES}
    opd = []
    names_available = False
    if string_index:
        _, kind, _, start, size = sections[string_index]
        if kind != 3 or (size and start + size > len(report.data)):
            report.issue("section_name_table_invalid", "error", "Section-name table is not a bounded SHT_STRTAB.")
        else:
            names_available = True
            if size and (report.data[start] != 0 or report.data[start + size - 1] != 0):
                report.issue("section_name_table_termination", "error", "ELF string table must begin and end with a null byte.")
            for index, (name, kind, addr, file_offset, section_size) in enumerate(sections):
                if kind == 0 or name == 0:
                    continue
                if name >= size:
                    report.issue("section_name_offset", "error", "Section name offset is outside its string table.", index)
                    continue
                # Only compare fixed, recognized names. Never echo arbitrary input text
                # or scan unbounded strings for every section.
                prefix = report.data[start + name:min(start + name + 9, start + size)]
                for known in _KNOWN_NAMES:
                    if prefix.startswith(known + b"\0"):
                        named[known.decode("ascii")] += 1
                        if known == b".opd":
                            opd.append({"index": index, "memory_range": [addr, addr + section_size],
                                        "file_range": [file_offset, file_offset + section_size] if kind != 8 else None})
    report.result["section_summary"] = {
        "headers_checked": count, "names_available": names_available,
        "recognized_name_counts": named,
        "name_scope": "Only fixed recognized names are reported; arbitrary strings are not decoded.",
    }
    report.result["opd"] = {
        "present": bool(opd) if names_available else None,
        "sections": opd[:MAX_DETAILS], "omitted": max(0, len(opd) - MAX_DETAILS),
        "interpretation": "Metadata only; descriptor layout, target and TOC are not inferred.",
    }
    return opd


def inspect_ps3_elf(data: bytes, *, source_sha256: str, label: str) -> dict:
    """Inspect supplied bytes only; SHA-256 binds this report to exactly those bytes.

    Invalid API arguments raise ValueError. Malformed/unsupported file contents
    produce a bounded report. A ready_for_review result is a structural result,
    not a loadability, ABI, translation, safety, or gameplay certification.
    """
    if type(data) is not bytes or len(data) > MAX_ELF_BYTES:
        raise ValueError("data must be bytes no larger than 64 MiB")
    if (type(source_sha256) is not str or len(source_sha256) != 64
            or any(c not in "0123456789abcdefABCDEF" for c in source_sha256)):
        raise ValueError("source_sha256 must contain exactly 64 hexadecimal characters")
    if type(label) is not str or not 1 <= len(label) <= 500 or not label.isprintable():
        raise ValueError("label must be 1 to 500 printable characters")
    digest = hashlib.sha256(data).hexdigest()
    if digest != source_sha256.lower():
        raise ValueError("source_sha256 does not match the supplied bytes")
    report = _Report(data, digest, label)
    if data[:4] == b"SCE\0":
        report.issue("sce_container", "unsupported", (
            "Encrypted SCE container (SELF/EBOOT.BIN/SPRX): STAR has no keys and does not decrypt, so only the "
            "signature is reported. Point the tool at the decrypted ELF (e.g. EBOOT.ELF) if you have one."))
        return report.finish(None, "encrypted_container")
    if len(data) < 16:
        report.issue("truncated_identifier", "error", "Input is shorter than an ELF identification block.")
        return report.finish(None)
    if data[:4] != b"\x7fELF":
        report.issue("unrecognized_format", "unsupported", "Input is not a recognized ELF or SCE container.")
        return report.finish(False, "unsupported")
    elf_class, encoding, version = data[4:7]
    if elf_class not in (1, 2) or encoding not in (1, 2):
        report.issue("unsupported_elf_encoding", "unsupported", "ELF class or byte encoding is not supported.")
        return report.finish(None)
    bits, endian = (32 if elf_class == 1 else 64), ("<" if encoding == 1 else ">")
    size = 52 if bits == 32 else 64
    if len(data) < size:
        report.issue("truncated_header", "error", "ELF header is truncated for its declared class.")
        return report.finish(None)
    values = struct.unpack_from(endian + ("HHIIIIIHHHHHH" if bits == 32 else "HHIQQQIHHHHHH"), data, 16)
    kind, machine, hversion, entry, phoff, shoff, flags, ehsize, phsize, phnum, shsize, shnum, shstr = values
    candidate = encoding == 2 and (bits, machine) in ((32, 23), (64, 21))
    profile = ("spu_local_store" if machine == 23 else "ppu_32bit_effective_address") if candidate else None
    header = {
        "class_bits": bits, "byte_order": "little" if encoding == 1 else "big",
        "machine": machine, "type": kind, "osabi": data[7], "flags": flags,
        "raw_entry": entry, "header_size": ehsize, "profile": profile,
        "program_header_offset": phoff, "program_header_entry_size": phsize,
        "program_header_count": phnum, "section_header_offset": shoff,
        "section_header_entry_size": shsize, "section_header_count": shnum,
        "section_name_table_index": shstr,
    }
    report.result["header"] = header
    if not candidate:
        report.issue("not_ps3_profile", "blocker", "PS3 candidate profiles require big-endian ELF32/SPU or ELF64/PPC64.")
    if version != 1 or hversion != 1:
        report.issue("elf_version", "error", "Both ELF version fields must identify version 1.")
    if ehsize != size:
        report.issue("elf_header_size", "error", "ELF header size does not match the declared class.")
        return report.finish(candidate)
    if kind not in (2, 3, 0xFFA4):
        report.issue("object_type_scope", "unsupported", "Loader preflight supports executable, shared-object and SCE PPU relocatable-executable metadata only.")
    loads = _programs(report, header, endian, 2**bits)
    opd = _sections(report, header, endian, 2**bits)
    if not loads and kind in (2, 3, 0xFFA4):
        report.issue("no_load_regions", "blocker", "No load region was available for executable-image review.")
    matches = []
    for segment in loads:
        start, end = segment["memory_range"]
        if start <= entry < end:
            backed = segment["file_backed_memory_range"]
            matches.append({"segment_index": segment["index"], "permissions": segment["permissions"],
                            "backing": "file" if backed and entry < backed[1] else "zero_fill"})
    report.result["entry"] = {
        "raw": entry, "mapped_to": matches[:MAX_DETAILS],
        "mappings_omitted": max(0, len(matches) - MAX_DETAILS),
        "inside_opd_metadata": any(s["memory_range"][0] <= entry < s["memory_range"][1] for s in opd)
        if report.result["opd"]["present"] is not None else None,
        "callable": None,
        "interpretation": "Raw guest value and declared mappings only; platform entry convention is unresolved.",
    }
    if loads and not matches:
        report.issue("entry_unmapped", "warning", "Raw entry is outside the declared load regions; entry semantics require review.")
    return report.finish(candidate)
