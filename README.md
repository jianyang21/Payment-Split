# Payment QR Generator

This is a small Flask app I built to generate UPI payment QR codes on the fly. You type in an amount, it spits out a scannable QR code that opens straight into GPay, PhonePe, Paytm or whatever UPI app the person has installed, with the amount and your name already filled in.

I started building this because merchants shouldn't have to pay charges just to collect a payment. Most payment gateway setups take a cut on every transaction, even small ones. UPI between two people is free, so this app just builds a direct UPI link to your own account instead of routing the money through some gateway that takes a percentage. The merchant keeps the full amount every time.

## What it needs

Python 3.11 or newer works fine. You'll also need a MongoDB database somewhere, since every generated payment gets logged there with its own id, amount and status. I used MongoDB Atlas's free tier for this since it doesn't need anything installed locally and works from anywhere once deployed.

## Setting it up

First install the dependencies.

```
pip install -r requirements.txt
```

Then copy `.env.example` to `.env` and fill in your own values.

```
PAYEE_VPA=yourname@upi
PAYEE_NAME=Your Name
MONGO_URI=your mongodb connection string
BASE_URL=http://localhost:5000
```

`PAYEE_VPA` is your actual UPI id, the one money lands in when someone scans and pays. `PAYEE_NAME` is just the name shown to the payer inside their UPI app. `MONGO_URI` points at your database, local or hosted. `BASE_URL` is used for building internal status links and should match wherever the app is actually running.

Once that's filled in, start the app.

```
python app.py
```

It runs on port 5000 by default. Open `localhost:5000` in a browser, type an amount, hit generate, and you'll get one or more QR codes depending on how big the amount is.

## How the QR itself works

Each QR encodes a proper UPI deep link, not a link to this app. That means scanning it opens the payment app directly with the amount and payee already filled in, no extra redirect needed. The image itself is generated in memory every time someone requests it rather than being saved as a file anywhere, which keeps the app stateless and means it'll behave the same whether it's running on my laptop or deployed somewhere like Vercel.

## Routes

The homepage lets you enter an amount. Submitting it hits `/generate`, which creates the payment record (or records, if it had to split) and shows the QR codes back to you. Each QR image is served from `/qrcodes/<id>.png`, generated fresh from the stored payment data each time. There's also a `/pay/<id>` page that shows the current status of a specific payment by looking it up in the database.

## A note on the env file

Never commit your real `.env`. It's already listed in `.gitignore` for that reason. The `.env.example` file is the only one meant to be public, and it just has placeholder values so anyone cloning this knows what to fill in.
