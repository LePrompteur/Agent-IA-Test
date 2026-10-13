"""Point d'entrée de compatibilité : délègue à src/main.py."""

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.argv[0] = str(Path(__file__).parent / "src" / "main.py")
    runpy.run_path(sys.argv[0], run_name="__main__")
