import queue
import pytest
from pathlib import Path


@pytest.fixture
def tmp_output(tmp_path: Path) -> Path:
    """Temporary output folder with the three required subfolders."""
    for sub in ("AudioFiles", "TranscriptionFiles", "SummaryFiles"):
        (tmp_path / sub).mkdir()
    return tmp_path


@pytest.fixture
def ui_queue() -> queue.Queue:
    return queue.Queue()
