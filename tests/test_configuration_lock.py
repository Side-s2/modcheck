import sys
from pathlib import Path
from subprocess import PIPE, Popen

import pytest

from modcheck.errors import ConfigError
from modcheck.storage.instance import configuration_lock


def test_config_lock_excludes_other_process_and_recovers_after_exit(tmp_path: Path) -> None:
    source = str(Path(__file__).resolve().parents[1] / "src")
    script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from modcheck.storage.instance import configuration_lock
with configuration_lock(Path(sys.argv[2])):
    print("ready", flush=True)
    sys.stdin.read()
"""
    other_directory = tmp_path / "other"
    other_directory.mkdir()
    with Popen([sys.executable, "-c", script, source, str(tmp_path)],
               stdin=PIPE, stdout=PIPE, text=True) as writer:
        try:
            assert writer.stdout.readline().strip() == "ready"
            with pytest.raises(ConfigError, match="另一个"):
                with configuration_lock(tmp_path):
                    pytest.fail("config directory has two writers")
            with configuration_lock(other_directory):
                assert writer.poll() is None
        finally:
            writer.kill()
    with configuration_lock(tmp_path):
        assert (tmp_path / ".modcheck.lock").is_file()
