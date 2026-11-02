"""Reads the ABI-6 descriptor a MaiCord plugin DLL exports, without loading it.

A plugin is a PE with no entry point, no TLS directory and exactly one export,
`maicord_plugin_v6`: a const `mc_descriptor` (include/maicord/sdk/plugin_abi.h).
The catalog takes everything it publishes about a plugin build (name, version,
api level, permissions, network hosts) from that descriptor, so the index never
disagrees with the binary. The SDK bakes the permissions the hooks imply into
`permissions` at compile time, so the value read here is the full effective set.

The checks mirror the client's plugin_pe_check and plugin_descriptor_check for
what CI can see statically; the client repeats all of them when it loads the DLL.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

EXPORT_NAME = b"maicord_plugin_v6"
ABI = 6
DESCRIPTOR_SIZE_MIN = 128
MC_STR = struct.Struct("<QII")  # data pointer, bytes, reserved
HOSTS_MAX = 8
# MC_PERM_* in bit order (plugin_abi.h), as the catalog names them.
PERMISSIONS = ("message_send", "read_messages", "message_history", "read_activity", "network", "composer",
               "act_messages", "act_presence", "clipboard", "automated_actions", "persistent_log")
PERMISSIONS_KNOWN = (1 << len(PERMISSIONS)) - 1


class DescriptorError(Exception):
    pass


@dataclass
class Descriptor:
    owner_id: int
    api_level: int
    name: str
    version: str
    summary: str
    author: str
    homepage: str
    permissions: list[str]
    network: list[str]


class _Image:
    def __init__(self, data: bytes):
        self.data = data
        if len(data) < 0x40 or data[:2] != b"MZ":
            raise DescriptorError("not a PE file")
        self.pe = struct.unpack_from("<I", data, 0x3C)[0]
        if self.pe + 24 > len(data) or data[self.pe:self.pe + 4] != b"PE\0\0":
            raise DescriptorError("not a PE file")
        machine, count, _, _, _, optional_size, _ = struct.unpack_from("<HHIIIHH", data, self.pe + 4)
        if machine != 0x8664:
            raise DescriptorError("not an x64 image")
        self.opt = self.pe + 24
        if optional_size < 112 + 16 * 8 or struct.unpack_from("<H", data, self.opt)[0] != 0x20B:
            raise DescriptorError("not a PE32+ image")
        self.entry = struct.unpack_from("<I", data, self.opt + 16)[0]
        self.base = struct.unpack_from("<Q", data, self.opt + 24)[0]
        self.directories = [struct.unpack_from("<II", data, self.opt + 112 + 8 * i) for i in range(16)]
        table = self.opt + optional_size
        if table + 40 * count > len(data):
            raise DescriptorError("section table out of bounds")
        self.sections = []
        for i in range(count):
            virtual_size, rva, raw_size, raw = struct.unpack_from("<IIII", data, table + 40 * i + 8)
            flags = struct.unpack_from("<I", data, table + 40 * i + 36)[0]
            self.sections.append((rva, max(virtual_size, 0), raw, raw_size, flags))

    def offset(self, rva: int, size: int = 1) -> int:
        for start, virtual_size, raw, raw_size, _ in self.sections:
            if start <= rva and rva + size <= start + min(virtual_size or raw_size, raw_size):
                return raw + rva - start
        raise DescriptorError(f"RVA {rva:#x} is not backed by the file")

    def read(self, rva: int, size: int) -> bytes:
        offset = self.offset(rva, size)
        return self.data[offset:offset + size]

    def pointer(self, value: int, size: int) -> bytes:
        if value < self.base:
            raise DescriptorError("a descriptor pointer leaves the image")
        return self.read(value - self.base, size)

    def text(self, raw: bytes, maximum: int, required: bool) -> str:
        pointer, size, reserved = MC_STR.unpack(raw)
        if reserved or size > maximum or (required and not size):
            raise DescriptorError("a descriptor string is empty, too long or has reserved bits")
        try:
            value = self.pointer(pointer, size).decode("utf-8") if size else ""
        except UnicodeDecodeError:
            raise DescriptorError("a descriptor string is not UTF-8") from None
        if any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
            raise DescriptorError("a descriptor string has control characters")
        return value


def _descriptor_rva(image: _Image) -> int:
    export_rva, export_size = image.directories[0]
    if not export_rva or not export_size:
        raise DescriptorError("no export")
    function_count, name_count, address_functions, address_names = struct.unpack_from(
        "<IIII", image.read(export_rva + 20, 16))
    if function_count != 1 or name_count != 1:
        raise DescriptorError("a plugin exports exactly one named symbol")
    name_rva = struct.unpack("<I", image.read(address_names, 4))[0]
    name = image.read(name_rva, len(EXPORT_NAME) + 1)
    if name != EXPORT_NAME + b"\0":
        raise DescriptorError(f"the export is not {EXPORT_NAME.decode()}")
    rva = struct.unpack("<I", image.read(address_functions, 4))[0]
    if export_rva <= rva < export_rva + export_size:
        raise DescriptorError("the export is forwarded")
    for start, virtual_size, _, _, flags in image.sections:
        if start <= rva < start + virtual_size:
            if flags & 0x20000000:
                raise DescriptorError("the export is code")
            return rva
    raise DescriptorError("the export is outside every section")


def read_descriptor(path) -> Descriptor:
    with open(path, "rb") as stream:
        data = stream.read()
    image = _Image(data)
    if image.entry:
        raise DescriptorError("the DLL has an entry point")
    if image.directories[9][0] or image.directories[9][1]:
        raise DescriptorError("the DLL has a TLS directory")
    # Imports (1), delay imports (13) and the bound-import table (11): a plugin reaches the host only through its API table.
    if any(image.directories[n][0] or image.directories[n][1] for n in (1, 11, 13)):
        raise DescriptorError("the DLL has imports")
    for _, _, _, _, flags in image.sections:
        if flags & 0x20000000 and flags & 0x80000000:
            raise DescriptorError("a section is writable and executable")
    rva = _descriptor_rva(image)
    size = struct.unpack("<I", image.read(rva, 4))[0]
    if size < DESCRIPTOR_SIZE_MIN:
        raise DescriptorError("the descriptor is too small")
    raw = image.read(rva, 128)
    _, abi, api_level, flags, owner_id = struct.unpack_from("<IIIIQ", raw, 0)
    if abi != ABI:
        raise DescriptorError(f"ABI {abi}, expected {ABI}")
    if flags or not owner_id:
        raise DescriptorError("the descriptor flags are not zero or the owner is missing")
    if not 1 <= api_level <= 0xFFFF:
        raise DescriptorError("the api level is out of range")
    name = image.text(raw[24:40], 64, True)
    version = image.text(raw[40:56], 32, True)
    summary = image.text(raw[56:72], 256, False)
    author = image.text(raw[72:88], 64, False)
    homepage = image.text(raw[88:104], 256, False)
    permissions, network_pointer, network_count = struct.unpack_from("<QQI", raw, 104)
    if permissions & ~PERMISSIONS_KNOWN:
        raise DescriptorError("the descriptor asks for an unknown permission")
    if network_count > HOSTS_MAX:
        raise DescriptorError("too many network hosts")
    hosts = []
    if network_count:
        table = image.pointer(network_pointer, 16 * network_count)
        hosts = [image.text(table[16 * i:16 * i + 16], 253, True) for i in range(network_count)]
    return Descriptor(owner_id, api_level, name, version, summary, author, homepage,
                      [p for i, p in enumerate(PERMISSIONS) if permissions >> i & 1], hosts)
