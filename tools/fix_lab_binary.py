"""Fix a broken Observathon PyInstaller binary so it runs on this machine.

The shipped Windows binaries bundle CORRUPT support DLLs (VCRUNTIME140, _ssl,
libssl/libcrypto, ucrtbase, several .pyd ...) that fail to load with
"LoadLibrary: Invalid access to memory location". The Python bytecode + the
agent code are fine. This rewrites the PyInstaller archive, replacing every
bundled .dll/.pyd that has a known-good copy in a reference CPython 3.12.x
install (+ System32) with that good copy, and writes <name>-fixed.exe.

Usage (run with ANY Python 3.x):
    python tools/fix_lab_binary.py bin/<phase>/observathon-sim.exe [path-to-python3.12-dir]

If the reference dir is omitted it is auto-detected from pyenv (~/.pyenv/.../3.12.*).
Then: copy <name>-fixed.exe over <name>.exe (keep a .broken backup).

For the REAL-LLM path you also need openai + a full stdlib that the binary does
NOT bundle; install them next to the repo (see SETUP_FIX.md), the wrapper adds
<repo>/_libs to sys.path at runtime.
"""
from __future__ import annotations
import os, sys, struct, zlib, glob

MAGIC = b'MEI\014\013\012\013\016'

def find_ref_dir(explicit):
    if explicit and os.path.isdir(explicit):
        return explicit
    pats = [os.path.expanduser("~/.pyenv/pyenv-win/versions/3.12.*"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312")]
    for pat in pats:
        for d in sorted(glob.glob(pat), reverse=True):
            if os.path.exists(os.path.join(d, "python312.dll")):
                return d
    raise SystemExit("No reference Python 3.12 dir found; pass it as the 2nd argument.")

def parse(path):
    d = open(path, "rb").read()
    pos = d.rfind(MAGIC)
    _, pkglen, tocoff, toclen, pyver, pylib = struct.unpack("!8sIIII64s", d[pos:pos+88])
    astart = (pos + 88) - pkglen
    toc = d[astart+tocoff: astart+tocoff+toclen]
    entries, ptr = [], 0
    while ptr < len(toc):
        (elen,) = struct.unpack("!I", toc[ptr:ptr+4])
        if elen <= 0 or ptr+elen > len(toc): break
        dpos, dlen, ulen = struct.unpack("!III", toc[ptr+4:ptr+16])
        flag = toc[ptr+16]; typcd = toc[ptr+17:ptr+18]
        namefield = toc[ptr+18: ptr+elen]
        entries.append(dict(elen=elen, dpos=dpos, dlen=dlen, ulen=ulen, flag=flag,
                            typcd=typcd, namefield=namefield,
                            name=namefield.rstrip(b"\0").decode("latin1","replace")))
        ptr += elen
    return d, astart, tocoff, toclen, pyver, pylib, entries

def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "bin/practice/observathon-sim.exe"
    ref = find_ref_dir(sys.argv[2] if len(sys.argv) > 2 else None)
    sys32 = os.path.expandvars(r"%WINDIR%\System32")
    good = {}
    for base in (ref, os.path.join(ref, "DLLs"), sys32):
        if os.path.isdir(base):
            for fn in os.listdir(base):
                low = fn.lower()
                if low.endswith((".dll", ".pyd")) and low not in good:
                    good[low] = os.path.join(base, fn)

    d, astart, tocoff, toclen, pyver, pylib, entries = parse(target)
    ordered = sorted(entries, key=lambda e: e["dpos"]); run = 0
    for e in ordered:
        assert e["dpos"] == run, "archive not contiguous"; run += e["dlen"]

    swapped = []
    for e in entries:
        key = e["name"].lower().split("/")[-1].split("\\")[-1]
        if key in good:
            b = open(good[key], "rb").read()
            e["raw"] = zlib.compress(b, 9); e["ul"] = len(b); e["fl"] = 1; swapped.append(key)
        else:
            e["raw"] = d[astart+e["dpos"]: astart+e["dpos"]+e["dlen"]]; e["ul"] = e["ulen"]; e["fl"] = e["flag"]

    data = bytearray(); npos = {}
    for e in sorted(entries, key=lambda x: x["dpos"]):
        npos[id(e)] = len(data); data += e["raw"]
    toc = bytearray()
    for e in entries:
        toc += struct.pack("!IIII", e["elen"], npos[id(e)], len(e["raw"]), e["ul"]) + bytes([e["fl"]]) + e["typcd"] + e["namefield"]
    assert len(toc) == toclen
    pkglen = len(data) + len(toc) + 88
    plib = pylib if isinstance(pylib, bytes) else pylib.encode()
    cookie = struct.pack("!8sIIII64s", MAGIC, pkglen, len(data), len(toc), pyver, plib)
    stub = d[:astart]                                  # the target's OWN bootloader stub
    out = os.path.splitext(target)[0] + "-fixed.exe"
    open(out, "wb").write(stub + bytes(data) + bytes(toc) + cookie)
    print(f"ref={ref}\nswapped {len(swapped)} binaries: {', '.join(sorted(swapped))}")
    print(f"wrote {out}")

if __name__ == "__main__":
    main()
