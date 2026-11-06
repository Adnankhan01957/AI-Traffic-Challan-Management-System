# Traffic Challan Assistant (v2)

A Streamlit tool that helps a traffic officer go from **photo → reviewed challan → PDF → WhatsApp notice**.
The AI only *suggests* the plate and violation. The officer reviews, corrects and confirms before anything is issued.

## What it does
- Officer login (hashed passwords), roles: officer / admin, audit log of every action
- Upload a photo or use the phone/laptop camera
- One AI call reads the plate and suggests the violation (Groq vision model)
- Plate format check for Indian plates (TS / TG and other states) with look-alike fixes (O↔0, S↔5, B↔8 …)
- Owner lookup from the vehicle registry (mobile numbers masked for non-admins)
- Overspeed needs a radar/speed-gun reading (a photo alone cannot prove speed)
- Duplicate warning (same vehicle + same violation within 24 h)
- Challan number, evidence photo stored with a SHA-256 fingerprint, printable PDF
- WhatsApp: tap-to-send link (no setup), or automatic via Twilio / Meta Cloud API
- Records page (search, filter, mark Paid, cancel with reason, CSV export), dashboard, admin page (fines, officers)

## Run on Windows

1. Open a terminal in the project folder.
2. Install dependencies:

   `pip install -r requirements.txt`

3. Copy the example environment file:

   `copy .env.example .env`

4. Open `.env` and configure:
   - `ADMIN_USER=admin`
   - `ADMIN_PASSWORD=your_unique_password_at_least_12_characters`
   - `GROQ_API_KEY=your_groq_api_key`

5. Save `.env`.
6. Start the application:

   `streamlit run app.py`

   Alternatively, double-click `run.bat`.

7. Log in using the administrator credentials configured in `.env`.

**Security:** Never upload `.env` to GitHub. Use a unique administrator password and keep your API key private.

## Bring your old data across (once)
```
python scripts/migrate_legacy.py "E:\Projects\traffic_challan\traffic_challan\Traffic_Chalan"
```
This imports vehicles, driver photos, fines and the old challan history. Safe to run again.

## Tests (no internet needed)
```
python -m unittest discover -s tests -v
python tests/smoke_ui.py
```

## Before real field use, please check
1. **Fine amounts** in Admin were copied from your first version (Helmet ₹200, Parking ₹100 …). Compare them with the official Telangana fine schedule and set the correct values and sections.
2. **Official channel.** Real e-challans in Telangana go through the official traffic police system. Put the official payment link in `PAYMENT_URL`, and get your department's approval before using this on real citizens.
3. **Owner data.** The registry here is a local demo database. Real owner details come from authorised government sources only.
4. **AI mistakes.** Test with many real photos. Check plates against the photo every time; this app forces that review step.
5. **Privacy.** `data/` and `.env` contain personal data and secrets. Never upload them to GitHub (the included `.gitignore` already excludes them).
6. **WhatsApp rules.** Automatic business messages need a Twilio or Meta business account. Meta only allows free-form text inside a 24-hour window; otherwise an approved message template is required.
