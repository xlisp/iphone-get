import os
import struct
import ctypes
import errno
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ptp import USBFS, _enc, CLAIMINTERFACE, RELEASEINTERFACE

usb = USBFS()
libc = usb.libc
fd = usb.fd

def claim_test(iface):
    t = ctypes.create_string_buffer(struct.pack("I", iface))
    r = libc.ioctl(fd, CLAIMINTERFACE, ctypes.byref(t))
    e = ctypes.get_errno()
    if r == 0:
        libc.ioctl(fd, RELEASEINTERFACE, ctypes.byref(t))
        print(f"claim({iface}): OK - no foreign claim!")
    else:
        print(f"claim({iface}): errno={e} ({errno.errorcode.get(e)})")

print("before:", end=" ")
claim_test(0)

print("raw SET_INTERFACE(0,0)...", end=" ")
try:
    usb.control_out(0x00, 0x0B, 0, 0)
    print("ok")
except OSError as e:
    print(f"fail {e}")

print("after:", end=" ")
claim_test(0)

ep_out, ep_in = None, None
for a in (1, 2):
    try:
        n = usb.bulk_out(0x01, b"\x00" * 12, 1000)
        print(f"bulk_out ep01: sent {n} bytes")
        break
    except OSError as e:
        print(f"bulk_out ep01: {e}")
    except TimeoutError:
        print("bulk_out ep01: timeout")

try:
    data = usb.bulk_in(0x81, 512, 1500)
    print(f"bulk_in ep81: got {len(data)} bytes")
except TimeoutError:
    print("bulk_in ep81: TIMEOUT (device NAK - endpoint alive, good sign)")
except OSError as e:
    print(f"bulk_in ep81: {e}")
