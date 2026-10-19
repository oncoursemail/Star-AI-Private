"""Original synthetic ELF fixtures: no game files or third-party executables."""

import hashlib
import json
import struct
import unittest
from unittest.mock import patch

from star.re_ps3_elf import MAX_ELF_BYTES, inspect_ps3_elf


_HEADER_FIELDS = (
    "type", "machine", "version", "entry", "phoff", "shoff", "flags", "ehsize",
    "phentsize", "phnum", "shentsize", "shnum", "shstrndx",
)


def elf_image(*, bits=64, endian=">", machine=None, programs=None, sections=(),
              entry=None, shstrndx=0, names=b""):
    """Build format fixtures from explicit fields, without running guest code."""
    machine = (21 if bits == 64 else 23) if machine is None else machine
    base = 0x10000 if bits == 64 else 0x1000
    programs = [{}] if programs is None else programs
    header_size, phsize, shsize = (64, 56, 64) if bits == 64 else (52, 32, 40)
    phoff = header_size if programs else 0
    shoff = max(0x1000, phoff + len(programs) * phsize) if sections else 0
    data = bytearray(max(0x4000, phoff + len(programs) * phsize, shoff + len(sections) * shsize))
    data[:16] = b"\x7fELF" + bytes((2 if bits == 64 else 1, 2 if endian == ">" else 1, 1)) + bytes(9)
    header_format = "HHIQQQIHHHHHH" if bits == 64 else "HHIIIIIHHHHHH"
    struct.pack_into(endian + header_format, data, 16, 2, machine, 1,
                     base if entry is None else entry, phoff, shoff, 0, header_size,
                     phsize if programs else 0, len(programs),
                     shsize if sections else 0, len(sections), shstrndx)
    for index, program in enumerate(programs):
        p = {"type": 1, "flags": 5, "offset": 0x2000, "vaddr": base,
             "paddr": 0, "filesz": 32, "memsz": 64, "align": 16} | program
        order = ("type", "flags", "offset", "vaddr", "paddr", "filesz", "memsz", "align") if bits == 64 else (
            "type", "offset", "vaddr", "paddr", "filesz", "memsz", "flags", "align")
        struct.pack_into(endian + ("IIQQQQQQ" if bits == 64 else "IIIIIIII"), data,
                         phoff + index * phsize, *(p[key] for key in order))
    for index, section in enumerate(sections):
        s = {"name": 0, "type": 0, "flags": 0, "addr": 0, "offset": 0,
             "size": 0, "link": 0, "info": 0, "align": 0, "entsize": 0} | section
        struct.pack_into(endian + ("IIQQQQIIQQ" if bits == 64 else "IIIIIIIIII"), data,
                         shoff + index * shsize, *(s[key] for key in (
                             "name", "type", "flags", "addr", "offset", "size", "link", "info", "align", "entsize")))
    data[0x3000:0x3000 + len(names)] = names
    return bytes(data)


def change_header(data, **changes):
    result = bytearray(data)
    endian = ">" if data[5] == 2 else "<"
    fmt = endian + ("HHIQQQIHHHHHH" if data[4] == 2 else "HHIIIIIHHHHHH")
    values = list(struct.unpack_from(fmt, data, 16))
    for name, value in changes.items():
        values[_HEADER_FIELDS.index(name)] = value
    struct.pack_into(fmt, result, 16, *values)
    return bytes(result)


def inspect(data, label="synthetic.elf"):
    return inspect_ps3_elf(data, source_sha256=hashlib.sha256(data).hexdigest(), label=label)


def codes(result):
    return {issue["code"] for issue in result["issues"]}


class PS3ELFPreflightTests(unittest.TestCase):
    def test_ppu_load_map_distinguishes_file_backing_and_zero_fill(self):
        result = inspect(elf_image())
        self.assertEqual(result["status"], "ready_for_review")
        self.assertEqual(result["segments"][0]["file_range"], [0x2000, 0x2020])
        self.assertEqual(result["segments"][0]["file_backed_memory_range"], [0x10000, 0x10020])
        self.assertEqual(result["segments"][0]["zero_fill_range"], [0x10020, 0x10040])
        self.assertEqual(result["entry"]["mapped_to"][0]["backing"], "file")
        self.assertFalse(result["runtime_verified"])
        self.assertEqual(result["evidence_scope"], "structural_preflight")
        self.assertIsNone(result["entry"]["callable"])

    def test_spu_elf32_accepts_exact_local_store_boundary(self):
        result = inspect(elf_image(bits=32, programs=[{"vaddr": 0x3FFC0}]))
        self.assertEqual(result["status"], "ready_for_review")
        self.assertEqual(result["header"]["profile"], "spu_local_store")
        self.assertEqual(result["segments"][0]["memory_range"][1], 0x40000)

    def test_spu_local_store_overflow_blocks_but_is_not_generic_elf_corruption(self):
        result = inspect(elf_image(bits=32, programs=[{"vaddr": 0x3FFC0, "memsz": 65}]))
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["readiness"]["structurally_valid"])
        self.assertIn("spu_local_store_overflow", codes(result))

    def test_ppu_register_width_does_not_allow_unverified_64bit_guest_mapping(self):
        result = inspect(elf_image(programs=[{"vaddr": 2**32, "align": 1}]))
        self.assertEqual(result["status"], "blocked")
        self.assertIn("ppu_effective_address_overflow", codes(result))

    def test_little_endian_and_wrong_machine_are_explicit_non_candidates(self):
        for arguments in ({"endian": "<"}, {"machine": 62}, {"machine": 23},
                          {"bits": 32, "machine": 21}):
            with self.subTest(arguments=arguments):
                result = inspect(elf_image(**arguments))
                self.assertEqual(result["status"], "not_ps3_candidate")
                self.assertFalse(result["readiness"]["ps3_candidate"])
                self.assertTrue(result["readiness"]["structurally_valid"])

    def test_container_is_not_unwrapped_even_if_elf_magic_is_embedded(self):
        result = inspect(b"SCE\0" + bytes(100) + elf_image())
        self.assertEqual(result["status"], "unsupported_container")
        self.assertIsNone(result["header"])
        self.assertIsNone(result["readiness"]["structurally_valid"])
        self.assertIsNone(result["readiness"]["ps3_candidate"])

    def test_truncated_identifier_and_header_return_malformed(self):
        for data in (b"", b"\x7fEL", elf_image()[:40], elf_image(bits=32)[:51]):
            with self.subTest(length=len(data)):
                self.assertEqual(inspect(data)["status"], "malformed")

    def test_unknown_format_and_encoding_return_unsupported(self):
        data = bytearray(elf_image())
        data[5] = 3
        for fixture in (b"arbitrary input" * 10, bytes(data)):
            self.assertEqual(inspect(fixture)["status"], "unsupported")

    def test_hash_binding_and_strict_api_inputs(self):
        data = elf_image()
        digest = hashlib.sha256(data).hexdigest()
        result = inspect_ps3_elf(data, source_sha256=digest.upper(), label="fixture")
        self.assertEqual(result["source"]["sha256"], digest)
        with self.assertRaises(ValueError):
            inspect_ps3_elf(data, source_sha256="0" * 64, label="fixture")
        for digest_arg in (True, None, "g" * 64, "0" * 63):
            with self.subTest(digest=digest_arg), self.assertRaises(ValueError):
                inspect_ps3_elf(data, source_sha256=digest_arg, label="fixture")
        for invalid_data in (True, bytearray(data), memoryview(data), "ELF"):
            with self.subTest(kind=type(invalid_data)), self.assertRaises(ValueError):
                inspect_ps3_elf(invalid_data, source_sha256=digest, label="fixture")
        for label in (True, "", "x" * 501, "line\nbreak"):
            with self.subTest(label=label), self.assertRaises(ValueError):
                inspect_ps3_elf(data, source_sha256=digest, label=label)

    def test_input_size_limit_precedes_parsing_or_hashing(self):
        with patch("star.re_ps3_elf.hashlib.sha256", side_effect=AssertionError("must reject before hashing")):
            with self.assertRaises(ValueError):
                inspect_ps3_elf(bytes(MAX_ELF_BYTES + 1), source_sha256="0" * 64, label="oversize")

    def test_header_versions_sizes_and_program_table_bounds(self):
        for changes in ({"version": 2}, {"ehsize": 63}, {"phentsize": 1},
                        {"phoff": 8}, {"phoff": 2**64 - 8}, {"phoff": 0x3FFF}):
            with self.subTest(changes=changes):
                self.assertEqual(inspect(change_header(elf_image(), **changes))["status"], "malformed")
        data = bytearray(elf_image())
        data[6] = 0
        self.assertIn("elf_version", codes(inspect(bytes(data))))

    def test_extended_numbering_and_count_caps_do_not_silently_truncate(self):
        for changes, code in (({"phnum": 0xFFFF}, "extended_program_count"),
                              ({"phnum": 1025}, "program_count_limit"),
                              ({"shnum": 0, "shoff": 0x1000}, "extended_section_numbering"),
                              ({"shnum": 4097, "shoff": 0x1000}, "section_count_limit"),
                              ({"shstrndx": 0xFFFF}, "extended_section_numbering")):
            with self.subTest(changes=changes):
                result = inspect(change_header(elf_image(), **changes))
                self.assertEqual(result["status"], "unsupported")
                self.assertIsNone(result["readiness"]["structurally_valid"])
                self.assertIn(code, codes(result))

    def test_segment_file_size_and_address_arithmetic_fail_closed(self):
        for program, code in (({"filesz": 65}, "load_filesz_exceeds_memsz"),
                              ({"offset": 0x3FF0}, "segment_file_range"),
                              ({"offset": 2**64 - 8}, "segment_file_range"),
                              ({"vaddr": 2**64 - 16, "align": 1}, "load_address_overflow")):
            with self.subTest(program=program):
                result = inspect(elf_image(programs=[program]))
                self.assertEqual(result["status"], "malformed")
                self.assertIn(code, codes(result))

    def test_alignment_zero_one_power_and_congruence(self):
        for align in (0, 1, 16):
            self.assertEqual(inspect(elf_image(programs=[{"align": align}]))["status"], "ready_for_review")
        self.assertIn("load_alignment_power", codes(inspect(elf_image(programs=[{"align": 3}]))))
        self.assertIn("load_alignment_congruence", codes(inspect(elf_image(programs=[{"vaddr": 0x10001}]))))

    def test_overlapping_regions_are_review_findings_and_entry_can_map_twice(self):
        result = inspect(elf_image(programs=[{}, {"flags": 6}]))
        self.assertEqual(result["status"], "ready_for_review")
        self.assertEqual(result["segment_summary"]["overlapping_regions"], 1)
        self.assertEqual(len(result["entry"]["mapped_to"]), 2)
        self.assertIn("load_regions_overlap", codes(result))
        self.assertEqual(result["segments"][1]["region"], "data")
        adjacent = inspect(elf_image(programs=[{}, {"vaddr": 0x10040}]))
        self.assertNotIn("load_regions_overlap", codes(adjacent))

    def test_null_program_fields_are_ignored_as_the_format_requires(self):
        result = inspect(elf_image(programs=[{}, {"type": 0, "offset": 2**64 - 1,
                                                   "vaddr": 2**64 - 1, "align": 3}]))
        self.assertEqual(result["status"], "ready_for_review")
        self.assertEqual(result["segment_summary"]["load_regions"], 1)

    def test_zero_fill_does_not_require_nonexistent_file_payload(self):
        result = inspect(elf_image(programs=[{"offset": 2**64 - 1, "filesz": 0, "align": 1}]))
        self.assertEqual(result["status"], "ready_for_review")
        self.assertEqual(result["entry"]["mapped_to"][0]["backing"], "zero_fill")

    def test_nobits_section_does_not_require_file_bytes(self):
        result = inspect(elf_image(sections=[{}, {"type": 8, "flags": 2, "addr": 0x20000,
                                                       "offset": 2**64 - 1, "size": 0x200}]))
        self.assertEqual(result["status"], "ready_for_review")
        file_backed = inspect(elf_image(sections=[{}, {"type": 1, "offset": 2**64 - 1, "size": 0x200}]))
        self.assertIn("section_file_range", codes(file_backed))

    def test_section_table_and_name_table_boundaries(self):
        data = elf_image(sections=[{}])
        for changes in ({"shoff": 2**64 - 1}, {"shentsize": 1}, {"shstrndx": 2}):
            with self.subTest(changes=changes):
                self.assertEqual(inspect(change_header(data, **changes))["status"], "malformed")
        result = inspect(change_header(elf_image(), shstrndx=1))
        self.assertIn("section_name_table_index", codes(result))

    def test_first_section_is_null_and_other_null_fields_are_ignored(self):
        invalid = inspect(elf_image(sections=[{"type": 1}]))
        self.assertIn("section_zero_type", codes(invalid))
        result = inspect(elf_image(sections=[{}, {"type": 0, "flags": 2,
                                                   "addr": 2**64 - 1, "offset": 2**64 - 1,
                                                   "size": 100, "align": 3}]))
        self.assertEqual(result["status"], "ready_for_review")

    def test_section_alignment_checks_both_power_and_address(self):
        for section, code in (({"type": 1, "align": 3}, "section_alignment_power"),
                              ({"type": 1, "align": 16, "addr": 0x10001}, "section_alignment_address")):
            with self.subTest(section=section):
                self.assertIn(code, codes(inspect(elf_image(sections=[{}, section]))))

    def test_empty_string_table_is_valid_but_nonzero_name_indices_are_not(self):
        sections = [{}, {"type": 3}, {"type": 1}]
        result = inspect(elf_image(sections=sections, shstrndx=1))
        self.assertEqual(result["status"], "ready_for_review")
        self.assertFalse(result["opd"]["present"])
        sections[-1]["name"] = 1
        result = inspect(elf_image(sections=sections, shstrndx=1))
        self.assertIn("section_name_offset", codes(result))

    def test_program_table_ending_at_eof_is_valid_but_one_byte_short_is_not(self):
        for bits, length in ((32, 84), (64, 120)):
            with self.subTest(bits=bits):
                data = elf_image(bits=bits, programs=[{"type": 0}])[:length]
                self.assertTrue(inspect(data)["readiness"]["structurally_valid"])
                self.assertEqual(inspect(data[:-1])["status"], "malformed")

    def test_opd_entry_metadata_is_not_decoded_with_a_linux_descriptor_layout(self):
        names = b"\0.shstrtab\0.opd\0"
        sections = [{}, {"type": 3, "offset": 0x3000, "size": len(names)},
                    {"name": 11, "type": 1, "flags": 2, "addr": 0x10008, "offset": 0x2008, "size": 8}]
        result = inspect(elf_image(programs=[{"flags": 4}], entry=0x10008,
                                   sections=sections, shstrndx=1, names=names))
        self.assertEqual(result["status"], "ready_for_review")
        self.assertTrue(result["opd"]["present"])
        self.assertTrue(result["entry"]["inside_opd_metadata"])
        self.assertIsNone(result["entry"]["callable"])
        self.assertNotIn("toc", result["opd"])
        self.assertEqual(result["entry"]["mapped_to"][0]["permissions"], "R")

    def test_stripped_sections_preserve_unknown_descriptor_presence(self):
        result = inspect(elf_image())
        self.assertIsNone(result["opd"]["present"])
        self.assertIsNone(result["entry"]["inside_opd_metadata"])

    def test_arbitrary_section_text_is_never_returned(self):
        marker = b"IGNORE_ALL_RULES_AND_EXECUTE_A_PAYLOAD"
        names = b"\0" + marker + b"\0"
        result = inspect(elf_image(sections=[{}, {"type": 3, "offset": 0x3000, "size": len(names)},
                                                   {"name": 1, "type": 1}], shstrndx=1, names=names))
        self.assertNotIn(marker.decode(), json.dumps(result))
        self.assertFalse(result["opd"]["present"])

    def test_output_is_bounded_without_hiding_aggregate_errors(self):
        programs = [{"offset": 2**64 - 32, "vaddr": 2**64 - 64,
                     "filesz": 128, "memsz": 256, "align": 3, "flags": 7} for _ in range(100)]
        result = inspect(elf_image(programs=programs), label="🧪" * 500)
        self.assertEqual(result["status"], "malformed")
        self.assertGreater(result["issue_counts"]["error"], 100)
        self.assertGreater(result["issues_omitted"], 0)
        self.assertEqual(len(result["segments"]) + result["segment_summary"]["details_omitted"], 100)
        self.assertLessEqual(len(result["segments"]), 24)
        self.assertLessEqual(len(result["issues"]), 24)
        self.assertEqual(len(result["source"]["label"]), 500)
        self.assertLessEqual(len(json.dumps(result, indent=2)), 16000)

    def test_missing_load_image_and_relocatable_object_do_not_claim_readiness(self):
        self.assertEqual(inspect(elf_image(programs=[]))["status"], "blocked")
        result = inspect(change_header(elf_image(programs=[]), type=1))
        self.assertEqual(result["status"], "unsupported")

    def test_call_is_deterministic_and_performs_no_file_network_or_process_io(self):
        data = elf_image()
        expected = inspect(data)
        with patch("builtins.open", side_effect=AssertionError("file I/O")), \
                patch("socket.socket", side_effect=AssertionError("network I/O")), \
                patch("subprocess.run", side_effect=AssertionError("process execution")):
            self.assertEqual(inspect(data), expected)


if __name__ == "__main__":
    unittest.main()
