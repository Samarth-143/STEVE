import subprocess
import sys
import venv
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
VENV_DIR = ROOT_DIR / ".venv"


def _venv_python() -> Path:
	if sys.platform == "win32":
		return VENV_DIR / "Scripts" / "python.exe"
	return VENV_DIR / "bin" / "python"


def _ensure_venv() -> Path:
	if sys.prefix != sys.base_prefix:
		return Path(sys.executable)

	if not _venv_python().exists():
		print("Creating local virtual environment...")
		venv.EnvBuilder(with_pip=True).create(VENV_DIR)

	return _venv_python()


python_executable = _ensure_venv()

print("Installing requirements in the local virtual environment...")
subprocess.run([str(python_executable), "-m", "pip", "install", "--upgrade", "pip"], check=True)
subprocess.run([str(python_executable), "-m", "pip", "install", "-r", "requirements.txt"], check=True)

print("Installing Playwright browsers...")
subprocess.run([str(python_executable), "-m", "playwright", "install"], check=True)

print("\n✅ Setup complete! Run 'python main.py' to start MARK XXV.")

