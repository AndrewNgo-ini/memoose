import pytest

from memoose.embeddings import HashEmbedder
from memoose.engine import Engine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMOOSE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEMOOSE_PROJECT_DIR", str(tmp_path / "proj"))
    eng = Engine(embedder=HashEmbedder())
    yield eng
    eng.close()


@pytest.fixture
def ds(engine):
    return engine.dataset("test")
