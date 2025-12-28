import sys, os, re, json
sys.path.insert(0, os.path.abspath('.'))
from main import app, load_sales

sales = load_sales()
sale = sales[0]
receipt = sale.get('receipt')
print('Using receipt', receipt, 'pending', sale.get('pending_amount'))
with app.test_client() as c:
    r = c.get('/')
    html = r.get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html)
    token = m.group(1) if m else None
    r = c.post('/', data={'user':'admin','password':'1234','csrf_token':token}, follow_redirects=True)
    html2 = r.get_data(as_text=True)
    m2 = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html2)
    token2 = m2.group(1) if m2 else token
    # post remaining
    pending = sale.get('pending_amount') or 0
    r = c.post(f'/sales/{receipt}/payment', data={'amount': str(pending), 'method':'Efectivo', 'csrf_token': token2}, follow_redirects=True)
    print('POST full payment', r.status_code)
    sales2 = load_sales()
    s2 = next((x for x in sales2 if x.get('receipt')==receipt), None)
    print('status after:', s2.get('status'), 'paid', s2.get('paid_amount'), 'pending', s2.get('pending_amount'))
