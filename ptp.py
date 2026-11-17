import os
import sys
import time
import struct
import ctypes
import errno

_U = 0x55


def _enc(dirbits, nr, size):
    return (dirbits << 30) | (size << 16) | (_U << 8) | nr


CONTROL = _enc(3, 0, 24)
BULK = _enc(3, 2, 24)
CLEAR_HALT = _enc(2, 21, 4)

BULK_CHUNK = 8192


class CtrlTransfer(ctypes.Structure):
    _fields_ = [
        ("bmRequestType", ctypes.c_uint8),
        ("bRequest", ctypes.c_uint8),
        ("wValue", ctypes.c_uint16),
        ("wIndex", ctypes.c_uint16),
        ("wLength", ctypes.c_uint16),
        ("timeout", ctypes.c_uint32),
        ("data", ctypes.c_void_p),
    ]


class BulkTransfer(ctypes.Structure):
    _fields_ = [
        ("ep", ctypes.c_uint32),
        ("len", ctypes.c_uint32),
        ("timeout", ctypes.c_uint32),
        ("data", ctypes.c_void_p),
    ]


class USBFS:
    def __init__(self):
        self.fd = int(os.environ["TERMUX_USB_FD"])
        self.libc = ctypes.CDLL(None, use_errno=True)

    def _ioctl(self, cmd, arg):
        r = self.libc.ioctl(self.fd, cmd, ctypes.byref(arg))
        if r < 0:
            e = ctypes.get_errno()
            raise OSError(e, errno.errorcode.get(e, str(e)))

    def control_in(self, rt, req, value, index, length, timeout=5000):
        buf = ctypes.create_string_buffer(length)
        t = CtrlTransfer(rt, req, value, index, length, timeout, ctypes.cast(buf, ctypes.c_void_p))
        n = self.libc.ioctl(self.fd, CONTROL, ctypes.byref(t))
        if n < 0:
            e = ctypes.get_errno()
            raise OSError(e, errno.errorcode.get(e, str(e)))
        return buf.raw[:n]

    def control_out(self, rt, req, value, index, timeout=5000):
        t = CtrlTransfer(rt, req, value, index, 0, timeout, None)
        n = self.libc.ioctl(self.fd, CONTROL, ctypes.byref(t))
        if n < 0:
            e = ctypes.get_errno()
            raise OSError(e, errno.errorcode.get(e, str(e)))
        return n

    def set_configuration(self, n):
        return self.control_out(0x00, 0x09, n, 0)

    def get_config_descriptor(self, length=512):
        return self.control_in(0x80, 0x06, 0x0200, 0, length)

    def get_device_descriptor(self):
        return self.control_in(0x80, 0x06, 0x0100, 0, 18)

    def bulk_in(self, ep, length, timeout=5000):
        buf = ctypes.create_string_buffer(length)
        t = BulkTransfer(ep, length, timeout, ctypes.cast(buf, ctypes.c_void_p))
        n = self.libc.ioctl(self.fd, BULK, ctypes.byref(t))
        if n < 0:
            e = ctypes.get_errno()
            if e == errno.ETIMEDOUT:
                raise TimeoutError("bulk in timeout")
            if e == errno.EPIPE:
                self._ioctl(CLEAR_HALT, BulkTransfer(ep, 0, 0, None))
                raise OSError(e, "EPIPE")
            raise OSError(e, errno.errorcode.get(e, str(e)))
        return buf.raw[:n]

    def bulk_out(self, ep, data, timeout=5000):
        buf = ctypes.create_string_buffer(data, len(data))
        t = BulkTransfer(ep, len(data), timeout, ctypes.cast(buf, ctypes.c_void_p))
        n = self.libc.ioctl(self.fd, BULK, ctypes.byref(t))
        if n < 0:
            e = ctypes.get_errno()
            if e == errno.EPIPE:
                self._ioctl(CLEAR_HALT, BulkTransfer(ep, 0, 0, None))
            raise OSError(e, errno.errorcode.get(e, str(e)))
        return n

    def bulk_endpoints(self):
        desc = self.get_config_descriptor()
        eps = []
        i = 0
        in_iface0 = False
        while i < len(desc):
            blen = desc[i]
            if blen < 2:
                break
            btype = desc[i + 1]
            if btype == 0x04:
                in_iface0 = desc[i + 2] == 0
            elif btype == 0x05 and in_iface0:
                addr = desc[i + 2]
                attrs = desc[i + 3]
                if (attrs & 0x03) == 0x02:
                    eps.append(addr)
            i += blen
        return eps


class PTP:
    CMD, DATA, RESP, EVENT = 1, 2, 3, 4

    OP_GetDeviceInfo = 0x1001
    OP_OpenSession = 0x1002
    OP_CloseSession = 0x1003
    OP_GetStorageIDs = 0x1004
    OP_GetObjectHandles = 0x1007
    OP_GetObjectInfo = 0x1008
    OP_GetObject = 0x1009
    OP_GetPartialObject = 0x1012

    def __init__(self, usb, ep_out, ep_in, verbose=True):
        self.usb = usb
        self.ep_out = ep_out
        self.ep_in = ep_in
        self.verbose = verbose
        self.buf = b""
        self.trans_id = 0

    def log(self, *a):
        if self.verbose:
            print(*a, file=sys.stderr, flush=True)

    def _read_bulk(self, n, timeout=10000):
        while len(self.buf) < n:
            need = max(BULK_CHUNK, n - len(self.buf))
            self.buf += self.usb.bulk_in(self.ep_in, min(need, BULK_CHUNK), timeout)
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send_command(self, op, params=()):
        self.trans_id += 1
        payload = b"".join(struct.pack("<I", p) for p in params)
        body = struct.pack("<HHI", op, len(params), self.trans_id & 0xFFFFFFFF) + payload
        hdr = struct.pack("<IH", len(body) + 6, self.CMD)
        self.usb.bulk_out(self.ep_out, hdr + body, 10000)

    def _read_block(self, timeout=10000):
        hdr = self._read_bulk(12, timeout)
        length, ctype = struct.unpack("<IH", hdr[:6])
        rest = length - 12
        data = self._read_bulk(rest, timeout) if rest else b""
        return ctype, hdr[6:] + data

    def transaction(self, op, params=(), send_data=None, timeout=30000):
        self._send_command(op, params)
        if send_data is not None:
            body = send_data
            hdr = struct.pack("<IH", len(body) + 6, self.DATA)
            self.usb.bulk_out(self.ep_out, hdr + body, 30000)
        ctype, block = self._read_block(timeout)
        if ctype == self.RESP:
            return self._parse_resp(block), None
        if ctype == self.DATA:
            resp_type, resp_block = self._read_block(timeout)
            resp = self._parse_resp(resp_block)
            if resp[0] != 0x2001:
                return resp, None
            return resp, block
        raise RuntimeError(f"unexpected container type {ctype}")

    @staticmethod
    def _parse_resp(block):
        code = struct.unpack("<H", block[:2])[0]
        params = struct.unpack(f"<{len((block[2:] )) // 4}I", block[2:2 + ((len(block) - 2) // 4) * 4])
        if code != 0x2001:
            raise RuntimeError(f"PTP response 0x{code:04x} params={params}")
        return (code, *params)

    def open_session(self):
        self.transaction(self.OP_OpenSession, (1,))

    def close_session(self):
        try:
            self.transaction(self.OP_CloseSession)
        except Exception as e:
            self.log("close session:", e)

    def get_storage_ids(self):
        resp, data = self.transaction(self.OP_GetStorageIDs)
        n = struct.unpack("<I", data[:4])[0]
        return list(struct.unpack(f"<{n}I", data[4:4 + 4 * n]))

    def get_object_handles(self, storage=0xFFFFFFFF, fmt=0, parent=0xFFFFFFFF, timeout=60000):
        resp, data = self.transaction(self.OP_GetObjectHandles, (storage, fmt, parent), timeout=timeout)
        n = struct.unpack("<I", data[:4])[0]
        return list(struct.unpack(f"<{n}I", data[4:4 + 4 * n]))

    def get_object_info(self, handle):
        resp, data = self.transaction(self.OP_GetObjectInfo, (handle,))
        d = data
        sid, fmt, prot, size, parent, assoc, adesc, seq = struct.unpack("<IHHIIIHI", d[:24])
        off = 24
        def read_str(dd, o):
            n = dd[o]
            s = dd[o + 1:o + 1 + n * 2].decode("utf-16-le").rstrip("\x00")
            return s, o + 1 + n * 2
        filename, off = read_str(d, off)
        cap_date = struct.unpack("<I", d[off:off + 4])[0]
        mod_date = struct.unpack("<I", d[off + 4:off + 8])[0]
        return {
            "storage": sid, "format": fmt, "size": size, "parent": parent,
            "assoc": assoc, "name": filename,
            "cap": cap_date, "mod": mod_date,
        }

    def get_object(self, handle, out_path, progress_every=1 << 20):
        self._send_command(self.OP_GetObject, (handle,))
        ctype, block = self._read_block(60000)
        if ctype == self.RESP:
            resp = self._parse_resp(block)
            raise RuntimeError(f"GetObject no data, resp 0x{resp[0]:04x}")
        length = struct.unpack("<I", block[:4])[0]
        total = length - 12
        remaining = total
        written = 0
        next_mark = progress_every
        t0 = time.time()
        with open(out_path, "wb") as f:
            chunk = block[12:]
            take = min(len(chunk), remaining)
            f.write(chunk[:take])
            written += take
            remaining -= take
            while remaining > 0:
                need = min(BULK_CHUNK, remaining)
                data = self._read_bulk(need, 60000)
                f.write(data)
                written += len(data)
                remaining -= len(data)
                if written >= next_mark:
                    speed = written / max(time.time() - t0, 0.001)
                    print(f"\r  {written/1048576:.1f} MB ({speed/1048576:.1f} MB/s)", end="", file=sys.stderr, flush=True)
                    next_mark += progress_every
        if written >= progress_every:
            print(file=sys.stderr)
        resp_type, resp_block = self._read_block(30000)
        self._parse_resp(resp_block)
        return written


def ptp_date_str(v):
    if not v:
        return ""
    t = time.mktime((1980, 1, 1, 0, 0, 0, 0, 0, -1)) + v
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "probe"
    usb = USBFS()
    dev = usb.get_device_descriptor()
    vid, pid = struct.unpack("<HH", dev[8:12])
    print(f"device {vid:04x}:{pid:04x}")

    if cmd == "setcfg1":
        usb.set_configuration(1)
        print("set config 1 ok")

    eps = usb.bulk_endpoints()
    print(f"iface0 bulk endpoints: {[hex(e) for e in eps]}")
    if len(eps) < 2:
        print("ERROR: expected 2 bulk endpoints (OUT, IN)")
        return
    ep_out = next(e for e in eps if not (e & 0x80))
    ep_in = next(e for e in eps if e & 0x80)

    ptp = PTP(usb, ep_out, ep_in)

    if cmd == "probe":
        resp, data = ptp.transaction(PTP.OP_GetDeviceInfo)
        stdver, vendor, pver = struct.unpack("<HHH", data[:6])
        print(f"PTP standard version {stdver}, vendor ext id 0x{struct.unpack('<I', data[6:10])[0]:08x}")
        return

    ptp.open_session()
    print("session opened")
    storages = ptp.get_storage_ids()
    print(f"storages: {[hex(s) for s in storages]}")

    if cmd == "list":
        handles = ptp.get_object_handles(timeout=120000)
        print(f"total objects: {len(handles)}")
        t0 = time.time()
        infos = []
        for i, h in enumerate(handles):
            try:
                info = ptp.get_object_info(h)
                info["handle"] = h
                infos.append(info)
            except Exception as e:
                print(f"handle {h}: {e}", file=sys.stderr)
            if (i + 1) % 200 == 0:
                el = time.time() - t0
                print(f"\r{i+1}/{len(handles)} ({el:.0f}s, {i+1/el:.0f}/s)", end="", file=sys.stderr, flush=True)
        print(file=sys.stderr)
        import json
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "objects.json"), "w") as f:
            json.dump(infos, f, ensure_ascii=False, indent=1)
        imgs = [x for x in infos if x["format"] != 0x3001]
        print(f"files: {len(imgs)} (associations: {len(infos) - len(imgs)})")
        for x in infos[:50]:
            kind = "DIR " if x["format"] == 0x3001 else "file"
            print(f"  {kind} {ptp_date_str(x['cap'])} {x['size']:>12} {x['name']}")

    ptp.close_session()


if __name__ == "__main__":
    main()
