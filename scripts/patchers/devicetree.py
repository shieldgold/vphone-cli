"""DeviceTree patcher — inject device identity into vphone600ap DT.

The vphone600ap DeviceTree uses syscfg/ references for device identity
properties (serial, model, etc.) that resolve to nothing in a VM.
This patcher replaces those references with real values.

Apple DeviceTree property format:
  name:   32 bytes (null-padded)
  length: 4 bytes LE (bit 31 = "resolve from syscfg at boot")
  value:  (length & 0x7FFFFFFF) bytes, padded to 4-byte alignment
"""

import hashlib
import struct
import time


# ── iPhone 17 Pro Max defaults ──────────────────────────────────

DEFAULT_IDENTITY = {
    "serial-number": "F2LZM0V1HG",           # 10-char format
    "model-number": "A3257",                   # US model (iPhone 17 Pro Max)
    "regulatory-model-number": "A3257",
    "region-info": "LL/A",
    "mlb-serial-number": "F2L401602J0HG0TAD",  # 17-char MLB
    # NOTE: Do NOT patch "model" or "fdr-product-type" here.
    # DeviceTree and RestoreDeviceTree share the same .im4p file.
    # Changing model from iPhone99,11 breaks driver matching during
    # restore and normal boot. Use MobileGestalt for marketing name.
}


def _generate_serial(seed=None):
    """Generate a plausible 10-character Apple serial number."""
    if seed is None:
        seed = str(time.time()).encode()
    h = hashlib.sha256(seed if isinstance(seed, bytes) else seed.encode()).hexdigest().upper()
    # Format: 3 factory + 1 year + 1 week + 5 unique
    charset = "0123456789CFGHJKLMNPQRSTVWXYZ"
    serial = ""
    for i in range(10):
        serial += charset[int(h[i * 2:i * 2 + 2], 16) % len(charset)]
    return serial


class DeviceTreePatcher:
    """Patch device identity properties in a decompressed DeviceTree."""

    def __init__(self, data, identity=None, randomize_serial=True):
        self.data = data if isinstance(data, bytearray) else bytearray(data)
        self.identity = dict(DEFAULT_IDENTITY)
        if identity:
            self.identity.update(identity)
        if randomize_serial:
            self.identity["serial-number"] = _generate_serial()
        self.count = 0

    def apply(self):
        for prop_name, new_value in self.identity.items():
            if self._patch_property(prop_name, new_value):
                self.count += 1
        return self.count

    def _patch_property(self, name, value):
        """Find and patch a single DT property by name."""
        name_bytes = name.encode("ascii")
        idx = 0

        while idx < len(self.data):
            pos = self.data.find(name_bytes, idx)
            if pos == -1:
                self._log(f"  [-] {name}: not found")
                return False

            # Verify exact match (not substring of longer property name)
            name_end = pos + len(name_bytes)
            if name_end < len(self.data) and self.data[name_end] != 0:
                idx = pos + 1
                continue

            # Check preceding byte — must be null (start of 32-byte field)
            if pos > 0 and self.data[pos - 1] != 0:
                idx = pos + 1
                continue

            # Parse property header
            length_offset = pos + 32
            if length_offset + 4 > len(self.data):
                idx = pos + 1
                continue

            length_raw = struct.unpack("<I", self.data[length_offset:length_offset + 4])[0]
            old_length = length_raw & 0x7FFFFFFF
            is_syscfg = (length_raw >> 31) & 1
            padded = (old_length + 3) & ~3

            if old_length > 512:  # sanity check
                idx = pos + 1
                continue

            # Read old value for logging
            value_offset = length_offset + 4
            old_value = self.data[value_offset:value_offset + old_length]
            old_str = old_value.rstrip(b"\x00").decode("ascii", errors="replace")

            # Prepare new value (null-terminated, padded to fill allocated space)
            new_bytes = value.encode("ascii") + b"\x00"
            if len(new_bytes) > padded:
                self._log(f"  [-] {name}: value too long ({len(new_bytes)} > {padded})")
                return False

            # Pad to fill entire allocated space
            new_bytes = new_bytes.ljust(padded, b"\x00")

            # Clear syscfg flag but KEEP original length to preserve DT layout.
            # The DT parser computes padding as (length+3)&~3 to find the next
            # property.  Changing length would shift all subsequent properties.
            struct.pack_into("<I", self.data, length_offset, old_length)

            # Write new value
            self.data[value_offset:value_offset + padded] = new_bytes

            flag_str = " (was syscfg)" if is_syscfg else ""
            self._log(f"  0x{pos:X}: {name}: '{old_str}' -> '{value}'{flag_str}")
            return True

        self._log(f"  [-] {name}: not found")
        return False

    @staticmethod
    def _log(msg):
        print(msg)
