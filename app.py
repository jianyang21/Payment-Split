from flask import Flask, Response, render_template_string, request

from qr import (
    generate_payment_qr,
    render_qr_png,
    links_collection,
    PAYEE_NAME,
    MAX_QR_AMOUNT,
    SPLIT_THRESHOLD,
)

app = Flask(__name__)

INDEX_HTML = """
<!doctype html>
<title>Payment QR Generator</title>
<style>
  body { font-family: sans-serif; max-width: 420px; margin: 60px auto; text-align: center; }
  input, button { font-size: 1rem; padding: 8px; }
</style>
<h1>Generate a Payment QR</h1>
<form method="post" action="{{ url_for('generate') }}">
  <input type="number" step="0.01" name="amount" placeholder="Amount (e.g. 25.00)" required>
  <button type="submit">Generate</button>
</form>
"""

RESULT_HTML = """
<!doctype html>
<title>Payment QR</title>
<style>
  body { font-family: sans-serif; max-width: 960px; margin: 60px auto; padding: 0 16px; text-align: center; }
  a { display: inline-block; margin-top: 16px; }
  .notice { background: #fff8e1; border: 1px solid #f0d379; padding: 10px 16px; border-radius: 6px; display: inline-block; margin-bottom: 20px; }
  .qr-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 32px;
    margin-top: 12px;
    align-items: start;
  }
  .qr-card {
    box-sizing: border-box;
    border: 1px solid #ddd;
    border-radius: 10px;
    padding: 16px;
    background: #fff;
  }
  .qr-card h3 { margin: 0 0 12px; font-size: 1rem; }
  .qr-card img { width: 100%; height: auto; display: block; }
</style>
<h1>Scan to Pay &#8377;{{ '%.2f'|format(amount) }}</h1>
{% if qrs|length > 1 %}
<p class="notice">
  UPI QR codes of &#8377;{{ '%.0f'|format(split_threshold) }} or more need extra verification, so this payment
  is split into {{ qrs|length }} QR codes of &#8377;{{ '%.0f'|format(max_qr_amount) }} or less each.
  Scan and pay <strong>all {{ qrs|length }}</strong> to complete the &#8377;{{ '%.2f'|format(amount) }} total.
</p>
{% endif %}
<div class="qr-grid">
  {% for qr in qrs %}
  <div class="qr-card">
    {% if qrs|length > 1 %}<h3>QR {{ qr.part }} of {{ qr.total_parts }} &mdash; &#8377;{{ '%.2f'|format(qr.amount) }}</h3>{% endif %}
    <img src="{{ url_for('serve_qr', payment_id=qr.payment_id) }}" alt="Payment QR code {{ qr.part }}">
  </div>
  {% endfor %}
</div>
<p>Scan with any UPI app (GPay, PhonePe, Paytm...) to pay <strong>{{ payee_name }}</strong></p>
<p><a href="{{ url_for('index') }}">&larr; Generate another</a></p>
"""

PAY_HTML = """
<!doctype html>
<title>Pay {{ payment_id }}</title>
<style>
  body { font-family: sans-serif; max-width: 420px; margin: 60px auto; text-align: center; }
</style>
{% if payment %}
  <h1>Payment {{ payment.status }}</h1>
  <p>Amount: &#8377;{{ '%.2f'|format(payment.amount) }}</p>
  <p>ID: <code>{{ payment.payment_id }}</code></p>
{% else %}
  <h1>Payment not found</h1>
{% endif %}
"""


@app.get("/")
def index():
    return render_template_string(INDEX_HTML)


@app.post("/generate")
def generate():
    amount = float(request.form["amount"])
    qrs = generate_payment_qr(amount)
    return render_template_string(
        RESULT_HTML,
        amount=amount,
        qrs=qrs,
        payee_name=PAYEE_NAME,
        max_qr_amount=float(MAX_QR_AMOUNT),
        split_threshold=float(SPLIT_THRESHOLD),
    )


@app.get("/qrcodes/<payment_id>.png")
def serve_qr(payment_id):
    payment = links_collection.find_one({"payment_id": payment_id})
    if not payment:
        return "Not found", 404
    png_bytes = render_qr_png(payment["upi_url"])
    return Response(png_bytes, mimetype="image/png")


@app.get("/pay/<payment_id>")
def pay(payment_id):
    payment = links_collection.find_one({"payment_id": payment_id})
    return render_template_string(PAY_HTML, payment_id=payment_id, payment=payment)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
