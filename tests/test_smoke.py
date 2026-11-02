import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest


def test_home_loads():
    at = AppTest.from_file("app.py")
    at.run()
    assert not at.exception


def test_switch_role_worker():
    at = AppTest.from_file("app.py")
    at.run()
    # select role
    at.selectbox[0].select("Worker").run()
    assert not at.exception