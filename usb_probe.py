import os
import sys

n = os.environ.get("TERMUX_USB_FD") or (sys.argv[1] if len(sys.argv) > 1 else "?")
print(f"TERMUX_USB_FD={n}")
print(f"argv={sys.argv}")
print("cwd:", os.getcwd())
for e in os.listdir("/proc/self/fd"):
    try:
        t = os.readlink(f"/proc/self/fd/{e}")
        print(f"fd {e} -> {t}")
    except OSError as ex:
        print(f"fd {e}: {ex}")
