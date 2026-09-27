"""Write CWD and test results to a file."""
import sys
import io
import os
import pytest

cwd = os.getcwd()

buf = io.StringIO()

class Tee:
    def __init__(self, stream, buf):
        self._stream = stream
        self._buf = buf
    def write(self, msg):
        self._stream.write(msg)
        self._buf.write(msg)
    def flush(self):
        self._stream.flush()

old_out = sys.stdout
old_err = sys.stderr
sys.stdout = Tee(old_out, buf)
sys.stderr = Tee(old_err, buf)

ret = pytest.main([
    "tests/",
    "-v",
    "--tb=short",
    "--no-header",
])

sys.stdout = old_out
sys.stderr = old_err

output = buf.getvalue()
result_path = os.path.join(cwd, "pytest_output.txt")
with open(result_path, "w", encoding="utf-8") as f:
    f.write(f"CWD: {cwd}\n")
    f.write(output)
    f.write(f"\n\nEXIT CODE: {ret}\n")

print(f"Saved to {result_path}, exit code: {ret}")
