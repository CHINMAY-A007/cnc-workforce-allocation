import os, sys, tempfile
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_tmp = tempfile.mkdtemp()
os.environ["CNC_DB_PATH"] = os.path.join(_tmp, "test.db")
os.environ.pop("GEMINI_ENABLED", None)
os.environ["GEMINI_API_KEY"] = "test-key-not-real"


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    import app as appmod
    from core.db import reset_demo
    from data.seed import seed
    reset_demo(appmod.DB)
    seed(appmod.DB)
    with TestClient(appmod.app) as c:
        yield c
