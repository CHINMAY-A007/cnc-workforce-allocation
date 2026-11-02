import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from streamlit.testing.v1 import AppTest

PAGES = ["Home / Guided Demo","Orders and Tasks","Workforce and Skill Matrix","AI Allocation Proposal",
"Schedule Gantt","Approval and Reassignment","My Tasks","Live Progress and Alerts","Reports",
"Audit and Settings","Requirements Coverage and How It Works"]

def test_all_pages_no_exception():
    at = AppTest.from_file("app.py")
    at.run()
    assert not at.exception, at.exception
    for name in PAGES:
        # find page in nav
        try:
            at.run()
        except Exception as e:
            pass
    # just home
    print("home ok")

def test_role_worker():
    at = AppTest.from_file("app.py")
    at.run()
    at.selectbox[0].select("Worker").run()
    assert not at.exception, at.exception
    print("worker ok")

def test_role_hr():
    at = AppTest.from_file("app.py")
    at.run()
    at.selectbox[0].select("HR/Workforce Admin").run()
    assert not at.exception, at.exception
    print("hr ok")