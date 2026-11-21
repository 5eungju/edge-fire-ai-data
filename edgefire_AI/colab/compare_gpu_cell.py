from pathlib import Path
import json, csv, subprocess, sys, hashlib
import torch
assert torch.cuda.is_available(), "GPU runtime required"
base = Path("/content/drive/MyDrive/EDGEFIRE/runs")
first = base/"pilot_3564_yolo26n_gpu_autorun"
assert (first/"validation_metrics.json").is_file(), "Previous run has no completed validation report; inspect before continuing"
first_report = json.loads((first/"validation_metrics.json").read_text())
with (first/"results.csv").open() as stream:
    first_epochs = list(csv.DictReader(stream))
print("YOLO26 completed epochs:", len(first_epochs), flush=True)
print("YOLO26 validation:", first_report["metrics"], flush=True)
print("GPU:", torch.cuda.get_device_name(0), flush=True)
run_dir = base/"pilot_3564_yolo11n_gpu_autorun"
if not (run_dir/"validation_metrics.json").is_file():
    command = [sys.executable, "-u", "/content/edgefire_colab/code/train_colab.py", "--dataset", "/content/edgefire_colab/dataset", "--save-dir", str(run_dir), "--model", "yolo11n-seg.pt", "--epochs", "30"]
    if (run_dir/"last.pt").is_file():
        command.append("--resume")
    print("Starting YOLO11 GPU comparison:", command, flush=True)
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1) as process:
        for line in process.stdout:
            print(line, end="", flush=True)
        code = process.wait()
    if code:
        raise RuntimeError(f"YOLO11 training failed: exit {code}; inspect output and saved checkpoints")
second_report = json.loads((run_dir/"validation_metrics.json").read_text())
assert first_report["manifest_sha256"] == second_report["manifest_sha256"], "Different evaluation datasets"
report = {"scope":"3564-image pilot, GPU experiments", "test_used_for_selection":False, "operationally_validated":False, "deployment_decision":"review_required", "validation_metrics":{"yolo26n":first_report["metrics"], "yolo11n":second_report["metrics"]}}
(base/"gpu_pilot_comparison.json").write_text(json.dumps(report, indent=2))
print("GPU COMPARISON FINISHED", json.dumps(report), flush=True)
