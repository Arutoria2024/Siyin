import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'monitor'),str(root/'desktop')]
import monitor,workbench
workbench.install(monitor)
monitor.ThreadingHTTPServer(('127.0.0.1',19888),monitor.H).serve_forever()
