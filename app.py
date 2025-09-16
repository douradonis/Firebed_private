import os
import json
import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from mydatanaut.client import MyDataClient

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CREDENTIALS_FILE = os.path.join(DATA_DIR, "credentials.json")
CACHE_FILE = os.path.join(DATA_DIR, "cache.json")

os.makedirs(DATA_DIR, exist_ok=True)

# -------------------- Helpers --------------------

def load_credentials():
    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_credentials(creds):
    with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
        json.dump(creds, f, ensure_ascii=False, indent=2)

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_cache(data):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# -------------------- Routes --------------------

@app.route("/")
def index():
    return render_template("index.html")

# Credentials list
@app.route("/credentials")
def credentials_list():
    creds = load_credentials()
    return render_template("credentials.html", credentials=creds)

# Add new credential
@app.route("/credentials/add", methods=["GET", "POST"])
def credentials_add():
    if request.method == "POST":
        creds = load_credentials()
        new = {
            "name": request.form["name"],
            "user": request.form["user"],
            "key": request.form["key"],
            "env": request.form.get("env", "sandbox"),
            "vat": request.form.get("vat", "")
        }
        creds.append(new)
        save_credentials(creds)
        flash("Credentials added successfully!", "success")
        return redirect(url_for("credentials_list"))
    return render_template("credentials_add.html")

# Edit credential
@app.route("/credentials/edit/<name>", methods=["GET", "POST"])
def credentials_edit(name):
    creds = load_credentials()
    cred = next((c for c in creds if c["name"] == name), None)
    if not cred:
        flash("Credential not found!", "danger")
        return redirect(url_for("credentials_list"))
    if request.method == "POST":
        cred["user"] = request.form["user"]
        cred["key"] = request.form["key"]
        cred["env"] = request.form.get("env", "sandbox")
        cred["vat"] = request.form.get("vat", "")
        save_credentials(creds)
        flash("Credentials updated!", "success")
        return redirect(url_for("credentials_list"))
    return render_template("credentials_edit.html", credential=cred)

# Fetch invoices from AADE → save to cache
@app.route("/fetch", methods=["GET", "POST"])
def fetch():
    creds = load_credentials()
    if request.method == "POST":
        cred_name = request.form.get("credential")
        cred = next((c for c in creds if c["name"] == cred_name), None)
        if not cred:
            flash("Please select valid credentials", "danger")
            return redirect(url_for("fetch"))

        date_from = request.form.get("date_from")
        date_to = request.form.get("date_to")
        if not date_from or not date_to:
            flash("Both dates are required", "danger")
            return redirect(url_for("fetch"))

        client = MyDataClient(
            user_id=cred["user"],
            subscription_key=cred["key"],
            environment=cred.get("env", "sandbox"),
        )

        try:
            invoices = client.fetch_invoices(
                vat=cred.get("vat"),
                date_from=date_from,
                date_to=date_to,
            )
            save_cache(invoices)
            flash(f"Fetched {len(invoices)} invoices and saved to cache.", "success")
            return redirect(url_for("cache_view"))
        except Exception as e:
            flash(f"Fetch error: {e}", "danger")

    return render_template("fetch.html", credentials=creds)

# View cached invoices
@app.route("/cache")
def cache_view():
    cache = load_cache()
    return render_template("cache.html", invoices=cache)

# Search by MARK
@app.route("/search", methods=["GET", "POST"])
def search():
    result = None
    if request.method == "POST":
        mark = request.form.get("mark")
        cache = load_cache()
        matches = [inv for inv in cache if str(inv.get("mark")) == str(mark)]
        if matches:
            result = matches[0]
        else:
            flash("No invoice found for that MARK", "warning")
    return render_template("search.html", result=result)

# JSON API for cache (optional)
@app.route("/api/cache")
def api_cache():
    return jsonify(load_cache())

# -------------------- Main --------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
