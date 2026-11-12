"""Starter der installierten Windows-Version von Tally.

Legt alle veränderlichen Dateien (Einstellungen, Zugangsdaten, Vote-Listen) in
%APPDATA%\\Tally ab, damit sie Updates und eine Neuinstallation überleben, und
startet dann denselben Einstiegspunkt wie run.py.
"""
import os
import sys
import traceback

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

os.environ.setdefault(
    "TALLY_DATA_DIR",
    os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Tally"),
)
if "--no-browser" in sys.argv:
    os.environ["VOTEBOT_NO_BROWSER"] = "1"

if os.name == "nt":
    os.system("title Tally")

try:
    import run

    run.main()
except KeyboardInterrupt:
    pass
except Exception:
    traceback.print_exc()
    print()
    input("Tally konnte nicht gestartet werden. Enter zum Schliessen ...")
