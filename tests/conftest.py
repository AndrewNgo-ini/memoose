import pytest

from mnemoth.embeddings import HashEmbedder
from mnemoth.engine import Engine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMOTH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MNEMOTH_PROJECT_DIR", str(tmp_path / "proj"))
    eng = Engine(embedder=HashEmbedder())
    yield eng
    eng.close()


@pytest.fixture
def ds(engine):
    return engine.dataset("test")
