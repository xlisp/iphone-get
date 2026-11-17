import os
import struct
import ctypes
import errno

fd = int(os.environ["TERMUX_USB_FD"])
_U = 0x55


def enc(dirbits, nr, size):
    return (dirbits << 30) | (size << 16) | (_U << 8) | nr


IO = enc(0, 22, 0)
IOR22 = enc(2, 22, 4)
IOW22 = enc(1, 22, 4)
DISCONNECT_CANDIDATES = [("IO(22)", IO), ("IOR(22,4)", IOR22), ("IOW(22,4)", IOW22)]

DISCONNECT_CLAIM = enc(1, 27, 8)
SETCONFIGURATION = enc(2, 5, 4)
CONTROL = enc(3, 0, 24)

libc = ctypes.CDLL(None, use_errno=True)


def call_ioctl(nrcmd, name, data=None):
    buf = ctypes.create_string_buffer(data) if data is not None else None
    r = libc.ioctl(fd, nrcmd, buf)
    if r != 0:
        e = ctypes.get_errno()
        print(f"{name}: fail errno={e} ({errno.errorcode.get(e)})")
        return None
    print(f"{name}: ok")
    return buf


print("--- try DISCONNECT encodings ---")
for name, nrcmd in DISCONNECT_CANDIDATES:
    if call_ioctl(nrcmd, f"DISCONNECT {name}", struct.pack("I", 0)) is not None:
        break

print("--- try DISCONNECT_CLAIM (steal + claim iface 0) ---")
for flags in (1, 0):
    buf = call_ioctl(DISCONNECT_CLAIM, f"DISCONNECT_CLAIM flags={flags}", struct.pack("II", 0, flags))
    if buf is not None:
        call_ioctl(enc(2, 16, 4), "RELEASEINTERFACE(0)", struct.pack("I", 0))
        break

print("--- try raw control transfer SET_CONFIGURATION(4) ---")
ctrl = struct.pack("BBHHHIxxxxxxxxxxxxxxN", 0x00, 0x09, 4, 0, 0, 5000, 0)
ctrl = struct.pack("BBHHHI", 0x00, 0x09, 4, 0, 0, 5000) + b"\x00" * 8 + struct.pack("N", 0)
buf = ctypes.create_string_buffer(ctrl, len(ctrl))
r = libc.ioctl(fd, CONTROL, buf)
if r < 0:
    e = ctypes.get_errno()
    print(f"CONTROL SET_CONFIGURATION: fail errno={e} ({errno.errorcode.get(e)})")
else:
    print(f"CONTROL SET_CONFIGURATION: ok, transferred {r}")

print("--- SETCONFIGURATION ioctl after attempts ---")
call_ioctl(SETCONFIGURATION, "SET_CONFIGURATION(4)", struct.pack("I", 4))
