"""Physical address -> (row, bank, column) mapping.

A mapping scheme is written from most- to least-significant field, e.g.
``"row-bank-col"``. The cache-line offset always occupies the lowest bits.

* ``row-bank-col``  consecutive lines stay in one row (good row-buffer locality)
* ``row-col-bank``  consecutive lines rotate across banks (good bank parallelism)
* ``bank-row-col``  each bank owns a contiguous region of memory

Add ``+xor`` (e.g. ``row-bank-col+xor``) to XOR the bank index with the low
row bits, a permutation-based interleaving that spreads row conflicts across
banks (Zhang et al., MICRO 2000).
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Organization

FIELDS = ("row", "bank", "col")


@dataclass(frozen=True)
class DecodedAddress:
    row: int
    bank: int
    col: int


def _log2(value: int) -> int:
    return value.bit_length() - 1


class AddressMapper:
    def __init__(self, org: Organization, scheme: str = "row-bank-col"):
        org.validate()
        self.org = org
        self.scheme = scheme
        order, _, suffix = scheme.lower().partition("+")
        if suffix not in ("", "xor"):
            raise ValueError(f"unknown mapping modifier {suffix!r} (only 'xor' is supported)")
        self.xor_bank = suffix == "xor"
        parts = order.split("-")
        if sorted(parts) != sorted(FIELDS):
            raise ValueError(
                f"mapping {scheme!r} must name each of {FIELDS} exactly once, e.g. 'row-bank-col'"
            )
        widths = {
            "row": _log2(org.rows),
            "bank": _log2(org.banks),
            "col": _log2(org.lines_per_row),
        }
        self.offset_bits = _log2(org.line_size_bytes)
        # Compute the shift of each field, starting from the least significant.
        self._fields: dict[str, tuple[int, int]] = {}
        shift = self.offset_bits
        for name in reversed(parts):
            self._fields[name] = (shift, widths[name])
            shift += widths[name]
        self.address_bits = shift

    def decode(self, address: int) -> DecodedAddress:
        if address < 0:
            raise ValueError("address must be non-negative")
        address %= 1 << self.address_bits  # wrap addresses beyond capacity
        values = {
            name: (address >> shift) & ((1 << width) - 1)
            for name, (shift, width) in self._fields.items()
        }
        if self.xor_bank:
            values["bank"] ^= values["row"] & (self.org.banks - 1)
        return DecodedAddress(row=values["row"], bank=values["bank"], col=values["col"])

    def encode(self, row: int, bank: int, col: int) -> int:
        """Inverse of :meth:`decode` (line-aligned address)."""
        if self.xor_bank:
            bank ^= row & (self.org.banks - 1)
        address = 0
        for name, value in (("row", row), ("bank", bank), ("col", col)):
            shift, width = self._fields[name]
            if not 0 <= value < (1 << width):
                raise ValueError(f"{name}={value} out of range for {width} bits")
            address |= value << shift
        return address
