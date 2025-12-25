import json
import os
import re
import sys
import pytest

# ensure project root is on sys.path when running from tests/ folder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from main import app, INVENTARIO, save_inventory, load_sales


@pytest.fixture
def client():
    with app.test_client() as c:
        yield c


def login_admin(client):
    getr = client.get('/')
    assert getr.status_code == 200
    html = getr.get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html)
    token = m.group(1) if m else None
    assert token, 'no csrf token in login page'
    r = client.post('/', data={'user': 'admin', 'password': '1234', 'csrf_token': token}, follow_redirects=True)
    assert r.status_code == 200
    assert 'Bienvenido' in r.get_data(as_text=True)
    html2 = r.get_data(as_text=True)
    m2 = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html2)
    token2 = m2.group(1) if m2 else token
    return token2


def test_sale_financials_flow(client, tmp_path):
    token = login_admin(client)

    # pick a product with stock
    pid = None
    for k, v in INVENTARIO.items():
        if v.get('cantidad', 0) >= 2:
            pid = k
            break
    if pid is None:
        pid = next(iter(INVENTARIO.keys()))
        r = client.post('/add', data={'id': pid, 'cantidad': 5, 'csrf_token': token}, follow_redirects=True)
        assert r.status_code == 200

    # set known cost for product and persist
    INVENTARIO[pid]['cost'] = 1.0
    save_inventory(INVENTARIO)

    initial_qty = INVENTARIO[pid]['cantidad']
    items = [{'pid': pid, 'qty': 2, 'price': 5.0}]

    r2 = client.post('/sell', data={'items': json.dumps(items), 'csrf_token': token}, follow_redirects=True)
    assert r2.status_code == 200
    assert 'Venta registrada' in r2.get_data(as_text=True)

    sales = load_sales()
    assert sales, 'sales.json should not be empty'
    sale = sales[0]

    # financial assertions
    assert sale.get('total') == pytest.approx(10.0)
    assert sale.get('cost_total') == pytest.approx(2.0)
    assert sale.get('profit_total') == pytest.approx(8.0)

    li = sale['items'][0]
    assert li.get('unit_cost') == pytest.approx(1.0)
    assert li.get('line_cost') == pytest.approx(2.0)
    assert li.get('line_total') == pytest.approx(10.0)
    assert li.get('line_profit') == pytest.approx(8.0)

    # inventory persisted
    with open(os.path.join(os.getcwd(), 'inventory.json'), 'r', encoding='utf-8') as f:
        inv = json.load(f)
    assert inv.get(str(pid))['cantidad'] == initial_qty - 2
