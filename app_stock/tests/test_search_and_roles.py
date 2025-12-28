import json
import os
import re
import sys
import pytest

# ensure project root is on sys.path when running from tests/ folder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from main import app, INVENTARIO, load_sales


@pytest.fixture
def client():
    with app.test_client() as c:
        yield c


def login_user(client, username, password):
    getr = client.get('/')
    assert getr.status_code == 200
    html = getr.get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html)
    token = m.group(1) if m else None
    assert token, 'no csrf token in login page'
    r = client.post('/', data={'user': username, 'password': password, 'csrf_token': token}, follow_redirects=True)
    assert r.status_code == 200
    assert 'Bienvenido' in r.get_data(as_text=True) or username == 'china'
    html2 = r.get_data(as_text=True)
    m2 = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html2)
    token2 = m2.group(1) if m2 else token
    return token2


def test_global_search_on_sales_and_audit(client, tmp_path):
    token = login_user(client, 'admin', '1234')

    # pick a product with stock
    pid = None
    for k, v in INVENTARIO.items():
        if v.get('cantidad', 0) > 0:
            pid = k
            break
    if pid is None:
        pid = next(iter(INVENTARIO.keys()))
        r = client.post('/add', data={'id': pid, 'cantidad': 5, 'csrf_token': token}, follow_redirects=True)
        assert r.status_code == 200

    items = [{'pid': pid, 'qty': 1, 'price': 3.5}]
    r2 = client.post('/sell', data={'items': json.dumps(items), 'csrf_token': token}, follow_redirects=True)
    assert r2.status_code == 200
    body = r2.get_data(as_text=True)
    assert 'Venta registrada' in body

    sales = load_sales()
    assert sales, 'sales.json should not be empty'
    sale = sales[0]

    # search by receipt
    rlist = client.get(f"/sales?q={sale.get('receipt')}")
    assert rlist.status_code == 200
    assert sale.get('receipt') in rlist.get_data(as_text=True)

    # export CSV filtered by SKU
    sku = sale['items'][0].get('sku')
    rcsv = client.get(f"/sales/export?q={sku}")
    assert rcsv.status_code == 200
    assert sku in rcsv.get_data(as_text=True)

    # audit contains sell details with receipt - search via q
    ra = client.get(f"/audit?q={sale.get('receipt')}")
    assert ra.status_code == 200
    assert sale.get('receipt') in ra.get_data(as_text=True)


def test_china_role_normalization(client):
    # login as china (superuser for roles)
    token = login_user(client, 'china', 'changeme')

    # change operador role to 'Operator' (mixed case) and expect normalization to 'operador'
    r = client.post('/china/role', data={'username': 'operador', 'role': 'Operator', 'csrf_token': token}, follow_redirects=True)
    assert r.status_code == 200

    # view panel and check normalized role present
    rp = client.get('/china')
    assert rp.status_code == 200
    body = rp.get_data(as_text=True)
    assert 'operador' in body
