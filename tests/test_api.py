import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_home_index():
    r = client.get('/')
    assert r.status_code == 200
    assert 'CNC Workforce' in r.text

def test_orders_list():
    r = client.get('/api/orders')
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) >= 5

def test_tasks_generate():
    r = client.get('/api/tasks?order_id=ORD-1001')
    assert r.status_code == 200

def test_solve():
    r = client.post('/api/solve', json={'orders':['ORD-1001']}, headers={'X-Role':'Production Manager'})
    assert r.status_code == 200
    d = r.json()
    assert d['status'] in ('OPTIMAL','FEASIBLE')
    assert not d['violations']

def test_role_worker_pages():
    # worker can access mytasks endpoint (tasks)
    r = client.get('/api/tasks', headers={'X-Role':'Worker'})
    assert r.status_code == 200