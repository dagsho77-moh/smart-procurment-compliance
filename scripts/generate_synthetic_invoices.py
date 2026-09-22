"""Generate synthetic invoices + master data. Equivalent to `python -m invoice_guard synth`."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from invoice_guard.config import load_settings  # noqa: E402
from invoice_guard.synthetic.generator import generate  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=8, help="number of clean invoices (min 4)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    s = load_settings()
    manifest = generate(s.paths.synthetic_dir, s.paths.master_dir, clean_count=args.count, seed=args.seed)
    print(f"Generated {len(manifest['cases'])} documents in {s.paths.synthetic_dir}")
