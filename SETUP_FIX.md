# Làm cho `observathon-sim.exe` chạy được trên Windows

Binary lab (PyInstaller onefile) **không chạy được nguyên trạng** trên máy này — báo:

```
Failed to load Python DLL '...\_MEI...\python312.dll'.
LoadLibrary: Invalid access to memory location.
```

## Nguyên nhân (đã xác minh)
1. **Các DLL phụ thuộc đi kèm bị hỏng** (`vcruntime140*.dll`, `_ssl.pyd`, `libssl-3.dll`,
   `libcrypto-3.dll`, `ucrtbase.dll`, và ~18 `.pyd` khác). Chúng nạp lỗi "Invalid access to
   memory location". Bản thân file tải về **nguyên vẹn**; máy **không** bị AV/WDAC chặn
   (PyInstaller onefile tự build chạy tốt). → đây là lỗi **build/đóng gói phía binary**.
2. Binary **không đóng gói `openai` lẫn stdlib đầy đủ** (chỉ đủ cho `observathon_sim`; provider
   mặc định là `mock`). Provider `openai` import SDK **lazy** → cần `openai` + stdlib khi chạy.
   Onefile **bỏ qua `PYTHONPATH`**, nhưng **thư mục hiện hành (cwd) nằm trong `sys.path`**.

## Cách sửa đã áp dụng
- `tools/fix_lab_binary.py`: viết lại archive PyInstaller, **thay mọi `.dll/.pyd` đi kèm bằng bản
  chuẩn** từ CPython 3.12.x + System32 → sinh `*-fixed.exe`. (Interpreter sau khi thay là ABI
  3.12.x, tương thích .pyc của lab.)
- `_libs/`: chứa `openai` + toàn bộ deps + **stdlib 3.12.10 đầy đủ** (lấp các module binary
  không đóng gói: `asyncio`, `_ssl`, …). `solution/wrapper.py` tự thêm `<repo>/_libs` vào
  `sys.path` lúc chạy (vô hại nếu `_libs` không tồn tại).
- `bin/practice/observathon-sim.exe` hiện là bản đã sửa; bản gốc lưu ở `*.exe.broken`.

Kết quả: chạy thật với `gpt-4o-mini`, 6/6 request `status: ok`.

## Hai kiểu binary — cách sửa khác nhau

| Phase | Kiểu PyInstaller | Triệu chứng | Cách sửa |
|---|---|---|---|
| **practice** | onefile (tự chứa) | `Invalid access to memory location` | `tools/fix_lab_binary.py` (thay DLL hỏng trong gói) |
| **public / private** | onedir (cần `_internal/`) | `module could not be found` (thiếu `_internal\python312.dll`) | dựng/tái dùng thư mục `_internal/` cạnh exe |

### (Một lần) tạo `_libs` = openai + stdlib 3.12.10 đầy đủ
```powershell
$ref = "$env:USERPROFILE\.pyenv\pyenv-win\versions\3.12.10"   # pyenv install 3.12.10
& "$ref\python.exe" -m pip install --target _libs openai
robocopy "$ref\Lib" _libs /E /XD __pycache__ test tests idlelib tkinter | Out-Null
Copy-Item "$ref\DLLs\*.pyd" _libs\ -Force; Copy-Item "$ref\DLLs\*.dll" _libs\ -Force
```

### practice (onefile)
```powershell
python tools/fix_lab_binary.py bin/practice/observathon-sim.exe
Move-Item bin/practice/observathon-sim.exe       bin/practice/observathon-sim.exe.broken -Force
Move-Item bin/practice/observathon-sim-fixed.exe bin/practice/observathon-sim.exe        -Force
bin\practice\observathon-sim.exe --practice --config solution/config.json --wrapper solution/wrapper.py --out run_output.json
```

### public / private (onedir) — exe nhúng code app, chỉ thiếu thư mục runtime `_internal/`
Thư mục `_internal/` chỉ chứa **runtime** (python312.dll, base_library.zip, .pyd, DLL, certifi cacert)
— **không phụ thuộc phase** — nên dựng một lần rồi **tái dùng** cho mọi binary onedir
(`bin/public`, `bin/private`, kể cả `observathon-score.exe`).

Đã dựng sẵn `bin/public/_internal/`. Khi có binary phase mới, chỉ cần **copy lại**:
```powershell
Copy-Item bin/public/_internal bin/private/_internal -Recurse   # tái dùng runtime
bin\private\observathon-sim.exe --config solution/config.json --wrapper solution/wrapper.py --out run_output.json
```

Nếu cần dựng `_internal/` từ đầu (máy mới):
```powershell
# a) build 1 onedir probe 3.12.10 de lay runtime chuan
'import ssl,asyncio,ctypes,hashlib,sqlite3,lzma,bz2,socket' | Set-Content _p.py
& "$ref\python.exe" -m PyInstaller --onedir --distpath _od -n probeod _p.py
Copy-Item _od\probeod\_internal bin\public\_internal -Recurse -Force
# b) bo sung cac extension bien dich (.pyd) cua openai-stack vao dung package
Get-ChildItem _libs -Recurse -Filter *.pyd | ForEach-Object {
  $rel=$_.FullName.Substring((Resolve-Path _libs).Path.Length+1)
  $t="bin\public\_internal\$rel"; New-Item -ItemType Directory -Force (Split-Path $t)|Out-Null; Copy-Item $_.FullName $t -Force }
# c) certifi cacert.pem (httpx/openai can CA certs)
robocopy _libs\certifi bin\public\_internal\certifi /E | Out-Null
```

> Cần Python 3.12.x qua pyenv làm nguồn runtime/DLL chuẩn.
> `_libs/` và `bin/` bị `.gitignore` — dựng lại sau khi clone.
> Nên **báo giảng viên/TA**: binary Windows build lỗi (DLL hỏng ở practice; thiếu `_internal/` ở public) — nhiều bạn sẽ gặp.
