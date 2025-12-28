import json
import os
import sys
import pytest

# ensure project root is on sys.path when running from tests/ folder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from main import app, INVENTARIO, load_sales


@pytest.fixture
def client():
    with app.test_client() as c:
        yield c


def login_admin(client):
    # GET login page to obtain CSRF token
    getr = client.get('/')
    assert getr.status_code == 200
    html = getr.get_data(as_text=True)
    import re
    m = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html)
    token = m.group(1) if m else None
    assert token, 'no csrf token in login page'
    r = client.post('/', data={'user': 'admin', 'password': '1234', 'csrf_token': token}, follow_redirects=True)
    assert r.status_code == 200
    assert 'Bienvenido' in r.get_data(as_text=True)
    # parse dashboard token for subsequent POSTs
    html2 = r.get_data(as_text=True)
    m2 = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html2)
    token2 = m2.group(1) if m2 else token
    return token2


def test_sale_and_exports(client, tmp_path):
    token = login_admin(client)

    # ensure product with stock
    pid = None
    for k, v in INVENTARIO.items():
        if v.get('cantidad', 0) > 0:
            pid = k
            break
    if pid is None:
        pid = next(iter(INVENTARIO.keys()))
        r = client.post('/add', data={'id': pid, 'cantidad': 5, 'csrf_token': token}, follow_redirects=True)
        assert r.status_code == 200

    initial_qty = INVENTARIO[pid]['cantidad']
    items = [{'pid': pid, 'qty': 1, 'price': 2.5}]

    r2 = client.post('/sell', data={'items': json.dumps(items), 'csrf_token': token}, follow_redirects=True)
    assert r2.status_code == 200
    assert 'Venta registrada' in r2.get_data(as_text=True)

    # sales.json exists and top sale matches
    sales = load_sales()
    assert sales, 'sales.json should not be empty'
    sale = sales[0]
    assert sale['items'][0]['pid'] == pid

    # inventory persisted
    with open(os.path.join(os.getcwd(), 'inventory.json'), 'r', encoding='utf-8') as f:
        inv = json.load(f)
    assert inv.get(str(pid))['cantidad'] == initial_qty - 1

    # audit contains sell entry
    with open(os.path.join(os.getcwd(), 'audit.json'), 'r', encoding='utf-8') as f:
        audit = json.load(f)
    assert any(a.get('action') == 'sell' and a.get('details') and a['details'].get('receipt') == sale.get('receipt') for a in audit)

    # export CSV
    rcsv = client.get('/sales/export')
    assert rcsv.status_code == 200
    text = rcsv.get_data(as_text=True)
    assert sale.get('receipt') in text

    # receipt page
    rrec = client.get(f"/receipt/{sale.get('receipt')}")
    assert rrec.status_code == 200
    assert sale.get('receipt') in rrec.get_data(as_text=True)

    # sales list page
    rlist = client.get('/sales')
    assert rlist.status_code == 200
    assert sale.get('receipt') in rlist.get_data(as_text=True)

    # filtered CSV by receipt
    rcsvf = client.get(f"/sales/export?receipt={sale.get('receipt')}")
    assert rcsvf.status_code == 200
    assert sale.get('receipt') in rcsvf.get_data(as_text=True)
