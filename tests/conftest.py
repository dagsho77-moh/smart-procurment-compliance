import os
import sys
from pathlib import Path

os.environ["LLM_PROVIDER"] = "mock"  # tests never call a real LLM
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
