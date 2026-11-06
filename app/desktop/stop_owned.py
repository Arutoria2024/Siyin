import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'monitor'))
import monitor
monitor.do_stop()
