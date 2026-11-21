import subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "ultralytics==8.4.216", "pyyaml"], check=True)
from pathlib import Path
import time, zipfile, shutil, hashlib
archive = Path("/content/drive/MyDrive/EDGEFIRE/edgefire_colab_dataset.zip")
expected_bytes = 1407549284
expected_sha256 = "6fa25b325bd2b8f7373cb2abb2deca4101212ed93d8651a89cbdba6456ebe582"
deadline = time.monotonic() + 7200
while not archive.is_file() or archive.stat().st_size != expected_bytes:
    if time.monotonic() > deadline:
        raise TimeoutError("Drive upload not complete; rerun after checking upload")
    print("Waiting for Drive upload...", flush=True)
    time.sleep(30)
local = Path("/content/edgefire_colab_dataset.zip")
shutil.copy2(archive, local)
with local.open("rb") as stream:
    actual = hashlib.file_digest(stream, "sha256").hexdigest()
assert actual == expected_sha256, "Package hash mismatch; do not train"
root = Path("/content/edgefire_colab")
root.mkdir(exist_ok=True)
with zipfile.ZipFile(local) as z:
    for member in z.infolist():
        if not (root/member.filename).resolve().is_relative_to(root.resolve()):
            raise ValueError("Unsafe ZIP member")
    z.extractall(root)
print("Package verified and extracted. Ready for GPU training.")
run_dir = Path("/content/drive/MyDrive/EDGEFIRE/runs/pilot_3564_yolo26n_gpu_autorun")
command = [sys.executable, "-u", "/content/edgefire_colab/code/train_colab.py", "--dataset", str(root/"dataset"), "--save-dir", str(run_dir), "--model", "yolo26n-seg.pt", "--epochs", "30"]
if (run_dir/"last.pt").is_file():
    command.append("--resume")
print("Starting GPU training; checkpoints persist to", run_dir, flush=True)
subprocess.run(command, check=True)
print("GPU run completed. Do not run the older training cell below for the same experiment.")
