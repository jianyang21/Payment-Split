import os

from flask import Flask, Response, render_template_string, request

from qr import (
    generate_payment_qr,
    parse_amount,
    AmountError,
    render_qr_png,
    links_collection,
    PAYEE_NAME,
    MAX_QR_AMOUNT,
    SPLIT_THRESHOLD,
    MAX_TOTAL_AMOUNT,
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
  <input type="number" step="0.01" min="0.01" max="{{ '%.0f'|format(max_total_amount) }}" name="amount" placeholder="Amount (e.g. 25.00)" required>
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

  /* Once JS takes over, only the active card in the grid is shown. */
  .qr-grid.carousel .qr-card { display: none; }
  .qr-grid.carousel .qr-card.active { display: block; max-width: 320px; margin: 0 auto; }

  .qr-nav { display: none; align-items: center; justify-content: center; gap: 16px; margin-top: 16px; }
  .qr-nav.active { display: flex; }
  .qr-nav button {
    font-size: 1rem;
    padding: 8px 16px;
    border: 1px solid #ccc;
    border-radius: 6px;
    background: #fff;
    cursor: pointer;
  }
  .qr-nav button:disabled { opacity: 0.4; cursor: default; }
  .qr-timer { font-variant-numeric: tabular-nums; color: #555; min-width: 130px; }
</style>
<h1>Scan to Pay &#8377;{{ '%.2f'|format(amount) }}</h1>
{% if qrs|length > 1 %}
<p class="notice">
  UPI QR codes of &#8377;{{ '%.0f'|format(split_threshold) }} or more need extra verification, so this payment
  is split into {{ qrs|length }} QR codes of &#8377;{{ '%.0f'|format(max_qr_amount) }} or less each.
  Scan and pay <strong>all {{ qrs|length }}</strong> to complete the &#8377;{{ '%.2f'|format(amount) }} total.
  Each one shows for two minutes before moving to the next, or use the buttons below to go at your own pace.
</p>
{% endif %}
<div class="qr-grid" id="qr-grid">
  {% for qr in qrs %}
  <div class="qr-card">
    {% if qrs|length > 1 %}<h3>QR {{ qr.part }} of {{ qr.total_parts }} &mdash; &#8377;{{ '%.2f'|format(qr.amount) }}</h3>{% endif %}
    <img src="{{ url_for('serve_qr', payment_id=qr.payment_id) }}" alt="Payment QR code {{ qr.part }}">
  </div>
  {% endfor %}
</div>
<div class="qr-nav" id="qr-nav">
  <button type="button" id="qr-prev">&larr; Previous</button>
  <span class="qr-timer" id="qr-timer"></span>
  <button type="button" id="qr-next">Next &rarr;</button>
</div>
<p>Scan with any UPI app (GPay, PhonePe, Paytm...) to pay <strong>{{ payee_name }}</strong></p>
<p><a href="{{ url_for('index') }}">&larr; Generate another</a></p>
<script>
(function () {
  var grid = document.getElementById('qr-grid');
  var cards = grid.querySelectorAll('.qr-card');
  var total = cards.length;
  if (total <= 1) return;

  var nav = document.getElementById('qr-nav');
  var prevBtn = document.getElementById('qr-prev');
  var nextBtn = document.getElementById('qr-next');
  var timerEl = document.getElementById('qr-timer');
  var DURATION = 120;
  var current = 0;
  var remaining = DURATION;
  var intervalId = null;

  grid.classList.add('carousel');
  nav.classList.add('active');

  function render() {
    for (var i = 0; i < cards.length; i++) {
      cards[i].classList.toggle('active', i === current);
    }
    prevBtn.disabled = current === 0;
    nextBtn.disabled = current === total - 1;
  }

  function formatTime(seconds) {
    var m = Math.floor(seconds / 60);
    var s = seconds % 60;
    return 'Next in ' + m + ':' + (s < 10 ? '0' : '') + s;
  }

  function goTo(index) {
    current = Math.max(0, Math.min(total - 1, index));
    remaining = DURATION;
    render();
    timerEl.textContent = formatTime(remaining);
  }

  function tick() {
    remaining -= 1;
    if (remaining <= 0) {
      if (current < total - 1) {
        goTo(current + 1);
        return;
      }
      clearInterval(intervalId);
      timerEl.textContent = 'All QR codes shown';
      return;
    }
    timerEl.textContent = formatTime(remaining);
  }

  prevBtn.addEventListener('click', function () { goTo(current - 1); });
  nextBtn.addEventListener('click', function () { goTo(current + 1); });

  goTo(0);
  intervalId = setInterval(tick, 1000);
})();
</script>
"""

ERROR_HTML = """
<!doctype html>
<title>Payment QR Generator</title>
<style>
  body { font-family: sans-serif; max-width: 420px; margin: 60px auto; text-align: center; }
  .error { background: #fdecea; border: 1px solid #f5b3ab; padding: 10px 16px; border-radius: 6px; display: inline-block; }
</style>
<h1>Generate a Payment QR</h1>
<p class="error">{{ message }}</p>
<p><a href="{{ url_for('index') }}">&larr; Try again</a></p>
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
    return render_template_string(INDEX_HTML, max_total_amount=float(MAX_TOTAL_AMOUNT))


@app.post("/generate")
def generate():
    try:
        amount = parse_amount(request.form.get("amount", ""))
    except AmountError as exc:
        return render_template_string(ERROR_HTML, message=str(exc)), 400

    qrs = generate_payment_qr(amount)
    return render_template_string(
        RESULT_HTML,
        amount=float(amount),
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
    response = Response(png_bytes, mimetype="image/png")
    # Content for a given payment_id never changes once created.
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.get("/pay/<payment_id>")
def pay(payment_id):
    payment = links_collection.find_one({"payment_id": payment_id})
    if not payment:
        return render_template_string(PAY_HTML, payment_id=payment_id, payment=None), 404
    return render_template_string(PAY_HTML, payment_id=payment_id, payment=payment)


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG") == "1"
    app.run(debug=debug_mode, port=5000)
