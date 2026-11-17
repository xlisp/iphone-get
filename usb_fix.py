import os
import sys
import ctypes
import fcntl
import errno

fd = int(os.environ["TERMUX_USB_FD"])

_U = 0x55


def _IOW(nr, size):
    return (1 << 30) | (size << 16) | (_U << 8) | nr


def _IOR(nr, size):
    return (2 << 30) | (size << 16) | (_U << 8) | nr


SETCONFIGURATION = _IOW(5, 4)
GETCONFIGURATION = _IOR(8, 4)
CLAIMINTERFACE = _IOW(15, 4)
RELEASEINTERFACE = _IOW(16, 4)
DISCONNECT = _IOW(22, 4)
DISCONNECT_CLAIM = _IOW(27, 8)

libc = ctypes.CDLL(None, use_errno=True)


def get_config():
    buf = ctypes.create_string_buffer(4)
    r = libc.ioctl(fd, GETCONFIGURATION, buf)
    if r != 0:
        e = ctypes.get_errno()
        print(f"GET_CONFIGURATION: fail errno={e} ({errno.errorcode.get(e)})")
        return None
    print(f"GET_CONFIGURATION: {struct.unpack('I', buf.raw)[0]}")
    return struct.unpack("I", buf.raw)[0]


def set_config(n):
    r = libc.ioctl(fd, SETCONFIGURATION, struct.pack("I", n))
    if r != 0:
        e = ctypes.get_errno()
        print(f"SET_CONFIGURATION({n}): fail errno={e} ({errno.errorcode.get(e)})")
        return False
    print(f"SET_CONFIGURATION({n}): ok")
    return True


def try_disconnect(iface):
    r = libc.ioctl(fd, DISCONNECT, struct.pack("I", iface))
    if r == 0:
        print(f"DISCONNECT(iface {iface}): ok - foreign claim released")
        return True
    e = ctypes.get_errno()
    print(f"DISCONNECT(iface {iface}): fail errno={e} ({errno.errorcode.get(e)})")
    return False


def try_disconnect_claim(iface):
    # struct usbdevfs_disconnect_claim { unsigned intf; unsigned flags; }
    # flags: 0 = claim only if no driver, 1 = disconnect drivers except usbfs
    buf = struct.pack("II", iface, 1)
    r = libc.ioctl(fd, DISCONNECT_CLAIM, buf)
    if r == 0:
        print(f"DISCONNECT_CLAIM(iface {iface}, flags=1): ok")
        return True
    e = ctypes.get_errno()
    print(f"DISCONNECT_CLAIM(iface {iface}, flags=1): fail errno={e} ({errno.errorcode.get(e)})")
    return False


def claim_release(iface):
    r = libc.ioctl(fd, CLAIMINTERFACE, struct.pack("I", iface))
    if r == 0:
        print(f"CLAIM({iface}): ok")
        libc.ioctl(fd, RELEASEINTERFACE, struct.pack("I", iface))
        return True
    e = ctypes.get_errno()
    print(f"CLAIM({iface}): fail errno={e} ({errno.errorcode.get(e)})")
    return False


import struct

print(f"fd={fd}")
cfg = get_config()

print("--- try to release interface 0 claim ---")
ok = try_disconnect(0)
if not ok:
    ok = try_disconnect_claim(0)
    if ok:
        libc.ioctl(fd, RELEASEINTERFACE, struct.pack("I", 0))

print("--- can we claim interface 0 now? ---")
can_claim = claim_release(0)

print("--- switch to config 4 ---")
if set_config(4):
    get_config()
else:
    print("setconfig failed")
