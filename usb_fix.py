import os
import struct
import ctypes
import errno

fd = int(os.environ["TERMUX_USB_FD"])

_U = 0x55


def _IOR(nr, size):
    return (2 << 30) | (size << 16) | (_U << 8) | nr


def _IOW(nr, size):
    return (1 << 30) | (size << 16) | (_U << 8) | nr


def _IO(nr):
    return (_U << 8) | nr


# constants exactly as in linux/usbdevice_fs.h (note the "wrong-looking" direction bits)
SETCONFIGURATION = _IOR(5, 4)
GETDRIVER = _IOW(8, 272)
CLAIMINTERFACE = _IOR(15, 4)
RELEASEINTERFACE = _IOR(16, 4)
RESET = _IO(20)
DISCONNECT = _IO(22)
GET_CAPABILITIES = _IOR(26, 4)
DISCONNECT_CLAIM = _IOW(27, 8)
GETCONFIGURATION = _IOR(35, 4)

libc = ctypes.CDLL(None, use_errno=True)


def call_ioctl(nr, name, arg=None):
    buf = ctypes.create_string_buffer(arg) if arg is not None else None
    r = libc.ioctl(fd, nr, buf)
    if r != 0:
        e = ctypes.get_errno()
        print(f"{name}: fail errno={e} ({errno.errorcode.get(e)})")
        return None
    return buf


def get_config():
    buf = call_ioctl(GETCONFIGURATION, "GET_CONFIGURATION")
    if buf is not None:
        cfg = struct.unpack("I", buf.raw)[0]
        print(f"GET_CONFIGURATION: {cfg}")
        return cfg


def get_caps():
    buf = call_ioctl(GET_CAPABILITIES, "GET_CAPABILITIES")
    if buf is not None:
        print(f"GET_CAPABILITIES: 0x{struct.unpack('I', buf.raw)[0]:x}")


def get_driver(iface):
    buf = call_ioctl(GETDRIVER, f"GET_DRIVER({iface})", struct.pack("I", iface) + b"\x00" * 268)
    if buf is not None:
        name = buf.raw[4:].split(b"\x00")[0].decode()
        print(f"GET_DRIVER({iface}): '{name}'")


def disconnect(iface):
    buf = call_ioctl(DISCONNECT, f"DISCONNECT({iface})", struct.pack("I", iface))
    return buf is not None


def set_config(n):
    buf = call_ioctl(SETCONFIGURATION, f"SET_CONFIGURATION({n})", struct.pack("I", n))
    return buf is not None


def claim_release(iface):
    buf = call_ioctl(CLAIMINTERFACE, f"CLAIM({iface})", struct.pack("I", iface))
    if buf is not None:
        print(f"CLAIM({iface}): ok")
        libc.ioctl(fd, RELEASEINTERFACE, struct.pack("I", iface))
        return True
    return False


print(f"fd={fd}")
get_caps()
get_config()
get_driver(0)

print("--- release foreign claim on interface 0 ---")
disconnect(0)

print("--- claim test ---")
claim_release(0)

print("--- switch to config 4 ---")
if set_config(4):
    get_config()
