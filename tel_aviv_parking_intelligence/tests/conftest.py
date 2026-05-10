import sys
from pathlib import Path

# Add the project root to sys.path so `parking.*` imports work from the tests/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))
