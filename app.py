# app.py
import os
from dotenv import load_dotenv
from flask import Flask, request, render_template_string, url_for, send_file, redirect
from utils import (
    extract_marks_from_url, extract_mark, decode_qr_from_file, 
    extract_vat_categories, summarize_invoice, format_euro_str,
    is_mark_transmitted, fetch_by_mark, save_summary_to_excel,
    extract_marks_from_text, EXCEL_FILE
)

# Load env
load_dotenv()

AADE_USER = os.getenv("AADE_USER_ID", "")
AADE_KEY = os.getenv("AADE_SUBSCRIPTION_KEY", "")
ENV = (os.getenv("MYDATA_ENV", "sandbox") or "sandbox").lower()

# Endpoints
REQUESTDOCS_URL = (
    "https://mydataapidev.aade.gr/RequestTransmittedDocs"
    if ENV in ("sandbox", "demo", "dev")
    else "https://mydatapi.aade.gr/myDATA/RequestDocs"
)
TRANSMITTED_URL = (
    "https://mydataapidev.aade.gr/RequestTransmittedDocs"
    if ENV in ("sandbox", "demo", "dev")
    else "https://mydatapi.aade.gr/myDATA/RequestTransmittedDocs"
)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# HTML templates (unchanged from your original code)
NAV_HTML = """..."""  # Keep your HTML template here
VIEWER_HTML = """..."""  # Keep your HTML template here
PLACEHOLDER_HTML = """..."""  # Keep your HTML template here
LIST_HTML = """..."""  # Keep your HTML template here

# Routes (unchanged from your original code)
@app.route("/")
def home():
    return render_template_string(NAV_HTML)

@app.route("/options")
def options():
    return render_template_string(PLACEHOLDER_HTML, title="Επιλογές", message="Εδώ θα μπουν μελλοντικές ρυθμίσεις.")

@app.route("/viewer", methods=["GET", "POST"])
def viewer():
    error = ""
    payload = None
    raw = None
    summary = None
    message = None

    if request.method == "POST":
        input_text = request.form.get("mark", "") if "mark" in request.form else ""
        marks = []

        # 1) αν ανέβηκε αρχείο, προτεραιότητα στο αρχείο
        if "file" in request.files:
            f = request.files["file"]
            if f and f.filename:
                data = f.read()
                mark_from_file = decode_qr_from_file(data, f.filename)
                if mark_from_file:
                    marks = [mark_from_file]
                else:
                    error = "Δεν βρέθηκε ΜΑΡΚ στο αρχείο."

        # 2) αλλιώς αν υπάρχει input_text (MARK ή URL)
        if not marks and input_text:
            # αν είναι URL -> κάνουμε webscrape για όλα τα 15-ψήφια MARKs
            try:
                parsed_url = urlparse(input_text)
                if parsed_url.scheme in ("http", "https") and parsed_url.netloc:
                    marks_from_page = extract_marks_from_url(input_text)
                    if marks_from_page:
                        marks = marks_from_page
                    else:
                        # αν δεν βρέθηκε, ενημέρωση error (θα δείξουμε popup)
                        error = "Δεν βρέθηκε ΜΑΡΚ στη σελίδα."
                else:
                    # απλό text/mark
                    marks = extract_marks_from_text(input_text)
            except Exception:
                marks = extract_marks_from_text(input_text)

        if not marks:
            if not error:
                error = "Δεν βρέθηκε ΜΑΡΚ."
        else:
            successes = []
            duplicates = []
            api_errors = []
            last_summary = None
            last_payload = None
            last_raw = None

            for m in marks:
                # ΠΡΩΤΑ: έλεγχος στο RequestTransmittedDocs
                try:
                    if is_mark_transmitted(m, AADE_USER, AADE_KEY, TRANSMITTED_URL):
                        api_errors.append((m, "το παραστατικο ειναι ηδη καταχωρημενο-χαρακτηρισμενο"))
                        continue
                except Exception as e:
                    # σε περίπτωση σφάλματος στο check, προχωράμε κανονικά (θα καταγραφεί)
                    print("is_mark_transmitted error:", e)

                try:
                    err, parsed, raw_xml, summ = fetch_by_mark(m, AADE_USER, AADE_KEY, REQUESTDOCS_URL)
                except Exception as e:
                    api_errors.append((m, f"Exception: {e}"))
                    continue

                if err:
                    api_errors.append((m, err))
                    continue
                if not parsed or not summ:
                    api_errors.append((m, "Αποτυχία parse ή κενά δεδομένα."))
                    continue

                try:
                    vat_cats = extract_vat_categories(parsed)
                    saved = save_summary_to_excel(summ, m, vat_categories=vat_cats)
                    if saved:
                        successes.append(m)
                    else:
                        duplicates.append(m)
                except Exception as e:
                    api_errors.append((m, f"Σφάλμα αποθήκευσης: {e}"))
                    continue

                last_summary = summ
                last_payload = json.dumps(parsed, ensure_ascii=False, indent=2)
                last_raw = raw_xml

            parts = []
            if successes:
                parts.append(f"Αποθηκεύτηκαν: {len(successes)} ({', '.join(successes)})")
            if duplicates:
                parts.append(f"Διπλοεγγραφές (παραλήφθηκαν): {len(duplicates)} ({', '.join(duplicates)})")
            if api_errors:
                parts.append(f"Σφάλματα/Μηνύματα: {len(api_errors)}")
                parts += [f"- {m}: {e}" for m, e in api_errors[:20]]
            message = "\n".join(parts) if parts else None

            if last_summary:
                summary = last_summary
                payload = last_payload
                raw = last_raw

            if not successes and not duplicates and api_errors and not summary:
                error = "Απέτυχαν όλες οι προσπάθειες. Δες λεπτομέρειες στο μήνυμα."

    return render_template_string(
        VIEWER_HTML,
        error=error,
        payload=payload,
        raw=raw,
        summary=summary,
        env=ENV,
        endpoint=REQUESTDOCS_URL,
        message=message
    )

@app.route("/list", methods=["GET"])
def list_invoices():
    filepath = EXCEL_FILE
    table_html = ""
    error = ""
    css_numcols = ""

    if os.path.exists(filepath):
        try:
            df = pd.read_excel(filepath, engine="openpyxl", dtype=str).fillna("")
            df = df.astype(str)

            # Απόκρυψη στήλης ΦΠΑ_ΑΝΑΛΥΣΗ από τη λίστα αν υπάρχει
            if "ΦΠΑ_ΑΝΑΛΥΣΗ" in df.columns:
                df = df.drop(columns=["ΦΠΑ_ΑΝΑΛΥΣΗ"])

            # Προσθήκη checkbox για διαγραφή (χρησιμοποιούμε το MARK ως id)
            if "MARK" in df.columns:
                checkboxes = df["MARK"].apply(lambda v: f'<input type="checkbox" name="delete_mark" value="{str(v)}">')
                df.insert(0, "✓", checkboxes)

            table_html = df.to_html(classes="summary-table", index=False, escape=False)

            # Βάλε checkbox "select all" στον header της πρώτης στήλης
            table_html = table_html.replace(
                "<th>✓</th>", '<th><input type="checkbox" id="selectAll" title="Επιλογή όλων"></th>'
            )

            table_html = table_html.replace("<td>", '<td><div class="cell-wrap">').replace("</td>", "</div></td>")

            # Δεξιά στοίχιση για αριθμητικές στήλες
            headers = re.findall(r'<th[^>]*>(.*?)</th>', table_html, flags=re.S)
            num_indices = []
            for i, h in enumerate(headers):
                text = re.sub(r'<.*?>', '', h).strip()
                if text in ("Καθαρή Αξία", "ΦΠΑ", "Σύνολο", "Total", "Net", "VAT") or "ΦΠΑ" in text or "ΠΟΣΟ" in text:
                    num_indices.append(i+1)  # nth-child 1-based
            css_rules = []
            for idx in num_indices:
                css_rules.append(f".summary-table td:nth-child({idx}), .summary-table th:nth-child({idx}) {{ text-align: right; }}")
            css_numcols = "\n".join(css_rules)

        except Exception as e:
            error = f"Σφάλμα ανάγνωσης Excel: {e}"
    else:
        error = "Δεν βρέθηκε το αρχείο invoices.xlsx."

    return render_template_string(
        LIST_HTML,
        table_html=table_html,
        error=error,
        file_exists=os.path.exists(filepath),
        css_numcols=css_numcols
    )

@app.route("/delete", methods=["POST"])
def delete_invoices():
    """
    Διαγράφει εγγραφές βάσει MARK από το invoices.xlsx και επιστρέφει στη λίστα.
    """
    marks_to_delete = request.form.getlist("delete_mark")
    if not marks_to_delete:
        return redirect(url_for("list_invoices"))

    if os.path.exists(EXCEL_FILE):
        try:
            df = pd.read_excel(EXCEL_FILE, engine="openpyxl", dtype=str).fillna("")
            if "MARK" in df.columns:
                before = len(df)
                df = df[~df["MARK"].astype(str).isin([str(m).strip() for m in marks_to_delete])]
                after = len(df)
                if after != before:
                    df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
        except Exception as e:
            print("Σφάλμα διαγραφής:", e)

    return redirect(url_for("list_invoices"))

@app.route("/download", methods=["GET"])
def download_excel():
    if not os.path.exists(EXCEL_FILE):
        return ("Το αρχείο .xlsx δεν υπάρχει.", 404)
    return send_file(
        EXCEL_FILE,
        as_attachment=True,
        download_name="invoices.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
