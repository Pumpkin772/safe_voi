from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'src'))
from scripts.direction5_accr.run_a5_certificates import main

main()
