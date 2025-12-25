import re, json, os, sys
# ensure project root is on sys.path when running from tests/ folder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from main import app, load_sales

with app.test_client() as c:
    # GET login page (csrf)
    r = c.get('/')
    html = r.get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html)
    token = m.group(1) if m else None
    assert token, 'no csrf token'

    # login as admin
    r = c.post('/', data={'user': 'admin', 'password': '1234', 'csrf_token': token}, follow_redirects=True)
    assert r.status_code == 200
    html2 = r.get_data(as_text=True)
    m2 = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html2)
    token2 = m2.group(1) if m2 else token

    # create a sale with one existing product
    sales_before = load_sales()
    # pick pid from inventory via dashboard
    r = c.get('/dashboard')
    # create a simple item using pid 4 or 3
    items = [{'pid': 4, 'qty': 1, 'price': 2.5}]
    r = c.post('/sell', data={'items': json.dumps(items), 'csrf_token': token2}, follow_redirects=True)
    assert r.status_code == 200

    sales = load_sales()
    if not sales:
        print('no sales created')
        raise SystemExit(1)
    sale = sales[0]
    receipt = sale.get('receipt')
    print('Created sale', receipt, 'total', sale.get('total'))

    # GET sales page to refresh token
    r = c.get('/sales')
    html3 = r.get_data(as_text=True)
    m3 = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html3)
    token3 = m3.group(1) if m3 else token2

    # post a payment of 1.00
    pay = {'amount': '1.00', 'method': 'Efectivo', 'csrf_token': token3}
    r = c.post(f'/sales/{receipt}/payment', data=pay, follow_redirects=True)
    print('POST payment status', r.status_code)
    sales_after = load_sales()
    sale_after = next((s for s in sales_after if s.get('receipt')==receipt), None)
    print('Payments count after:', len(sale_after.get('payments', [])))
    print('Paid amount:', sale_after.get('paid_amount'))
    print('Pending amount:', sale_after.get('pending_amount'))

    # inspect payment_debug.log
    logf = os.path.join(os.path.dirname(__file__), '..', 'payment_debug.log')
    if os.path.exists(logf):
        print('\nLast lines of payment_debug.log:')
        with open(logf, 'r', encoding='utf-8') as fh:
            lines = fh.read().splitlines()
            for ln in lines[-20:]:
                print(ln)
    else:
        print('No payment_debug.log found')
