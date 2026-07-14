from pathlib import Path
import os
import subprocess
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parent
DB = ROOT / "database.pghembk"
OUT = ROOT / "reports" / ("multiaccount_report_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))


def pause() -> None:
    try:
        input("Press Enter to exit...")
    except EOFError:
        pass


if not DB.exists():
    print("ERROR: database.pghembk not found.")
    print("Put your HM2 backup in this folder and rename it to database.pghembk")
    pause()
    raise SystemExit(2)

cmd = [
    sys.executable,
    "-m", "plo_multiaccount_detector",
    "--input", str(DB),
    "--out", str(OUT),
    "--config", str(ROOT / "config.json"),
    "--site-id", "4",
    "--contains", "Omaha PL",
    "--top", "100",
]

env = dict(**os.environ)
env["PYTHONPATH"] = str(ROOT / "src")

print("Running PLO Multiaccount Detector...")
print("Output:", OUT)
result = subprocess.run(cmd, cwd=ROOT, env=env)
print()
if result.returncode == 0:
    print("Done. Open:")
    print(OUT / "multiaccount_candidates.csv")
    print(OUT / "top_candidates.md")
else:
    print("Run failed with code", result.returncode)

pause()
raise SystemExit(result.returncode)
