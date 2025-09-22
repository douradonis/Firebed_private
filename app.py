import os
import json
import re
from urllib.parse import urlparse
from dotenv import load_dotenv
from flask import Flask, request, render_template_string, url_for, send_file, redirect, session
import pandas as pd
from utils import (
    extract_marks_from_url, extract_mark, decode_qr_from_file, 
    extract_vat_categories, summarize_invoice, format_euro_str,
    is_mark_transmitted, fetch_by_mark, save_summary_to_excel,
    extract_marks_from_text, EXCEL_FILE
)
import datetime
import datetime
# μετά το app = Flask(...)
app.jinja_env.globals['datetime'] = datetime

app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.secret_key = os.getenv("FLASK_SECRET", "change-me")

# make datetime available in Jinja templates (fix for 'datetime' is undefined)
app.jinja_env.globals['datetime'] = datetime

# First create the Flask app
app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Now define CONFIG_FILE after app is created
CONFIG_FILE = os.path.join(app.config["UPLOAD_FOLDER"], "config.json")

# Load environment variables
load_dotenv()

def load_config():
    """Load configuration from file or environment variables"""
    config_data = {}
    
    # Try to load from file first
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config_data = json.load(f)
        except:
            pass
    
    # Fall back to environment variables
    if not config_data.get('AADE_USER_ID'):
        config_data['AADE_USER_ID'] = os.getenv("AADE_USER_ID", "")
    if not config_data.get('AADE_SUBSCRIPTION_KEY'):
        config_data['AADE_SUBSCRIPTION_KEY'] = os.getenv("AADE_SUBSCRIPTION_KEY", "")
    if not config_data.get('MYDATA_ENV'):
        config_data['MYDATA_ENV'] = os.getenv("MYDATA_ENV", "sandbox")
    
    return config_data

# Load initial configuration
config_data = load_config()
AADE_USER = config_data.get("AADE_USER_ID", "")
AADE_KEY = config_data.get("AADE_SUBSCRIPTION_KEY", "")
ENV = config_data.get("MYDATA_ENV", "sandbox").lower()

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

# HTML templates (unchanged from your original code)
# In the NAV_HTML template, add this line to the menu
NAV_HTML = """<!doctype html>
<html lang="el">
<head><meta charset="utf-8"><title>myDATA - Μενού</title>
<style>
body {font-family:Arial,sans-serif;max-width:900px;margin:20px auto;background:#fafafa;}
.card {background:white;padding:16px;margin:16px 0;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.05);}
.menu {display:flex;gap:12px;flex-wrap:wrap;}
.menu a {display:block;padding:12px 18px;background:#0d6efd;color:#fff;border-radius:10px;text-decoration:none;}
.menu a.secondary {background:#6c757d;}
</style>
</head><body>
<div class="card"><h1>myDATA - Κεντρικό Μενού</h1>
<p>Επέλεξε λειτουργία:</p>
<div class="menu">
<a href="{{ url_for('viewer') }}">Εισαγωγή Παραστατικού</a>
<a href="{{ url_for('config') }}" class="secondary">Ρύθμιση Παραμέτρων</a>
<a href="{{ url_for('list_invoices') }}">Λίστα Παραστατικών</a>
</div>
</div>
</body></html>
"""

VIEWER_HTML = """<!doctype html>
<html lang="el">
<head>
<meta charset="UTF-8">
<title>myDATA QR Viewer</title>
<style>
body {font-family:Arial,sans-serif;max-width:900px;margin:20px auto;background:#fafafa;}
.card {background:white;padding:16px;margin:16px 0;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.05);}
input, button {width:100%;padding:8px;margin:6px 0;border-radius:8px;}
button {background:#0d6efd;color:white;border:none;cursor:pointer;}
button:hover {background:#0b5ed7;}
pre {white-space:pre-wrap;word-wrap:break-word;background:#f7f7f7;padding:10px;border-radius:8px;}
.summary-table {width:100%;border-collapse:collapse;}
.summary-table th {background:#0d6efd;color:white;padding:8px;text-align:left;}
.summary-table td {border:1px solid #ddd;padding:8px;}
.summary-table tr:nth-child(even) td{background:#f9f9f9;}
.modal{display:none;position:fixed;z-index:1000;left:0;top:0;width:100%;height:100%;overflow:auto;background:rgba(0,0,0,0.5);}
.modal-content{background:#fff;margin:8% auto;padding:20px;border-radius:12px;width:80%;max-width:600px;}
.close{float:right;font-size:24px;font-weight:bold;cursor:pointer;}
.close:hover{color:#000;}
</style>
<script src="https://unpkg.com/html5-qrcode" defer></script>
</head>
<body>
<h1>myDATA QR Viewer</h1>
<p>Σκάναρε QR, ανέβασε εικόνα/PDF ή γράψε ΜΑΡΚ / URL.</p>

<p><a href="{{ url_for('home') }}">⬅ Επιστροφή στο μενού</a></p>

<div class="card">
<h3>1) Σάρωση QR</h3>
<div id="reader"></div>
<p>Περιβάλλον: {{ env|e }}, Endpoint: {{ endpoint|e }}</p>
</div>

<div class="card">
<h3>2) Εισαγωγή ΜΑΡΚ χειροκίνητα (ή URL)</h3>
<form method="post">
<input type="text" name="mark" placeholder="π.χ. 123456789012345  - ή -  https://... (URL με mark)" />
<button type="submit">Ανάκτηση</button>
</form>
</div>

<div class="card">
<h3>3) Upload εικόνας ή PDF</h3>
<form method="post" enctype="multipart/form-data">
<input type="file" name="file" />
<button type="submit">Ανέβασμα & Ανάκτηση</button>
</form>
</div>

{% if message %}
<div class="card" style="background:#e6ffed;border-color:#b7f5c6;">
<h3>OK</h3><pre>{{ message }}</pre>
</div>
{% endif %}

{% if error %}
<div class="card" style="background:#fff5f5;border-color:#f5c2c7;">
<h3>Σφάλμα</h3><pre>{{ error }}</pre>
</div>
{% endif %}

{% if summary %}
<div id="summaryModal" class="modal">
<div class="modal-content">
<span class="close" onclick="document.getElementById('summaryModal').style.display='none';">&times;</span>
<h3>Περίληψη Παραστατικού</h3>
<table class="summary-table">
<tr><th colspan="2">Εκδότης</th></tr>
<tr><td>ΑΦΜ</td><td>{{ summary['Εκδότης']['ΑΦΜ'] }}</td></tr>
<tr><td>Επωνυμία</td><td style="white-space:normal;word-break:break-word;">{{ summary['Εκδότης']['Επωνυμία'] }}</td></tr>
<tr><th colspan="2">Στοιχεία Παραστατικού</th></tr>
<tr><td>Σειρά</td><td>{{ summary['Στοιχεία Παραστατικού']['Σειρά'] }}</td></tr>
<tr><td>Αριθμός</td><td>{{ summary['Στοιχεία Παραστατικού']['Αριθμός'] }}</td></tr>
<tr><td>Ημερομηνία</td><td>{{ summary['Στοιχεία Παραστατικού']['Ημερομηνία'] }}</td></tr>
<tr><td>Είδος</td><td>{{ summary['Στοιχεία Παραστατικού']['Είδος'] }}</td></tr>
<tr><th colspan="2">Σύνολα</th></tr>
<tr><td>Καθαρή Αξία</td><td>{{ summary['Σύνολα']['Καθαρή Αξία'] }}</td></tr>
<tr><td>ΦΠΑ</td>
<td style="color: {% if summary['Σύνολα']['ΦΠΑ']|float > 100 %}red{% else %}green{% endif %};">
{{ summary['Σύνολα']['ΦΠΑ'] }}
</td></tr>
<tr><td>Σύνολο</td>
<td style="color: {% if summary['Σύνολα']['Σύνολο']|float > 500 %}red{% else %}black{% endif %};">
{{ summary['Σύνολα']['Σύνολο'] }}
</td></tr>

</table>
</div>
</div>
{% endif %}

{% if payload %}
<div class="card">
<h3>JSON (ολόκληρο)</h3>
<pre>{{ payload }}</pre>
</div>
{% endif %}

{% if raw %}
<div class="card">
<h3>XML Απόκριση</h3>
<pre>{{ raw }}</pre>
</div>
{% endif %}

<script>
document.addEventListener("DOMContentLoaded", function(){
  if (window.Html5Qrcode) {
    const html5QrcodeScanner = new Html5QrcodeScanner("reader", { fps:10, qrbox:240 });
    html5QrcodeScanner.render((decodedText)=>{
      const mark = (function(text){
        try{
          if(/^\d{15}$/.test(text.trim())) return text.trim();
          const url=new URL(text);
          const params=new URLSearchParams(url.search||"");
          const keys=["mark","MARK","invoiceMark","invMark","ΜΑΡΚ","Μ.Α.Ρ.Κ.","Μ.Αρ.Κ."];
          for(const k of keys){
            const v=params.get(k);
            if(v && /^\d{15}$/.test(v)) return v;
          }
        }catch(e){}
        return null;
      })(decodedText);
      if(mark){
        const form=document.createElement("form");
        form.method="POST";
        const input=document.createElement("input");
        input.type="hidden"; input.name="mark"; input.value=mark;
        form.appendChild(input); document.body.appendChild(form); form.submit();
      } else { alert("Το QR διαβάστηκε αλλά δεν βρέθηκε έγκυρος ΜΑΡΚ."); }
    });
  }

  {% if summary %}
    document.getElementById('summaryModal').style.display = 'block';
  {% endif %}
});
</script>

</body>
</html>
"""

PLACEHOLDER_HTML = """<!doctype html><html lang="el"><head><meta charset="utf-8"><title>{{ title }}</title>
<style>body{font-family:Arial,sans-serif;max-width:900px;margin:20px auto;background:#fafafa}.card{background:#fff;padding:16px;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.05)}</style></head>
<body><div class="card"><h1>{{ title }}</h1><p>{{ message }}</p><p><a href='{{ url_for("home") }}'>⬅ Επιστροφή</a></p></div></body></html>
"""

LIST_HTML = """<!doctype html>
<html lang="el">
<head>
<meta charset="UTF-8">
<title>Λίστα Παραστατικών</title>
<style>
body {font-family:Arial,sans-serif;max-width:1100px;margin:20px auto;background:#fafafa;}
.card {background:white;padding:16px;margin:16px 0;border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.05);}
.summary-table {width:100%;border-collapse:collapse;table-layout:fixed;}
.summary-table th, .summary-table td {border:1px solid #ddd;padding:8px;vertical-align:top;position:relative;}
.summary-table th {background:#0d6efd;color:white;user-select:none; cursor:grab;}
.summary-table th:active {cursor:grabbing;}
.summary-table tr:nth-child(even) td{background:#f9f9f9;}
nav {display:flex;gap:10px;margin-bottom:10px;}
nav a, nav span {text-decoration:none;padding:8px 12px;border-radius:8px;background:#0d6efd;color:#fff;}
nav a:hover {background:#0b5ed7;}
.small-btn {display:inline-block;padding:8px 12px;border-radius:8px;background:#198754;color:#fff;text-decoration:none;}
.cell-wrap {white-space:pre-wrap; word-break:break-word; max-width:360px; overflow:hidden;}
.controls {display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:8px;}
.controls input[type="text"] {padding:8px; border-radius:8px; border:1px solid #ddd; min-width:260px;}
.controls .danger {background:#dc3545;}
.controls .primary {background:#0d6efd;}
.controls .secondary {background:#6c757d;}
/* arrows */
th.sorted-asc::after { content: " \\2191"; }
th.sorted-desc::after { content: " \\2193"; }
/* resize handle */
th .resize-handle{
  position:absolute; right:0; top:0; width:6px; height:100%;
  cursor:col-resize; user-select:none;
}
th.drag-over-left { box-shadow: inset 3px 0 0 rgba(0,0,0,0.25); }
th.drag-over-right{ box-shadow: inset -3px 0 0 rgba(0,0,0,0.25); }
{{ css_numcols | safe }}
</style>
</head>
<body>
<nav>
  <a href="{{ url_for('home') }}">Αρχική</a>
  <a href="{{ url_for('viewer') }}">Εισαγωγή Παραστατικού</a>
  <a href="{{ url_for('options') }}">Επιλογές</a>
  <span style="background:#6c757d">Λίστα Παραστατικών</span>
</nav>

<div class="card">
  <h1>Λίστα Παραστατικών</h1>

  <div class="controls">
    <input type="text" id="globalSearch" placeholder="🔎 Αναζήτηση σε όλες τις στήλες...">
    {% if file_exists %}
      <a class="small-btn primary" href="{{ url_for('download_excel') }}">⬇️ Κατέβασμα .xlsx</a>
    {% endif %}
    <a class="small-btn secondary" href="{{ url_for('viewer') }}">➕ Εισαγωγή Παραστατικού</a>
  </div>

  {% if error %}
    <div style="background:#fff5f5;padding:12px;border-radius:8px;margin-top:12px;">{{ error }}</div>
  {% endif %}

  {% if table_html %}
    <form method="POST" action="{{ url_for('delete_invoices') }}">
      <div style="overflow:auto;margin-top:12px;">
        {{ table_html | safe }}
      </div>

      <div class="controls" style="margin-top:12px;">
        <button type="submit" class="small-btn danger">🗑️ Διαγραφή Επιλεγμένων</button>
      </div>
    </form>
  {% else %}
    <div style="color:#666;margin-top:12px;">Δεν υπάρχουν εγγραφές προς εμφάνιση.</div>
  {% endif %}
</div>

<script>
document.addEventListener("DOMContentLoaded", function(){
  const table = document.querySelector(".summary-table");
  if (!table) return;

  const thead = table.querySelector("thead");
  const tbody = table.querySelector("tbody");

  // ===== Global search (μόνο αυτό — αφαιρέθηκε το οριζόντιο φίλτρο) =====
  const search = document.getElementById("globalSearch");
  if (search){
    search.addEventListener("input", function(){
      const q = (search.value || "").toLowerCase();
      Array.from(tbody.rows).forEach(row=>{
        row.style.display = row.innerText.toLowerCase().includes(q) ? "" : "none";
      });
    });
  }

  // ===== Sorting (click-to-sort με ↑/↓) =====
  let lastSortedIndex = -1;
  let lastAsc = true;

  function normalizeValue(txt){
    const t = txt.trim();
    const euro = t.replace(/\./g,"").replace(",",".").replace(/[^\d\.\-]/g,"");
    if (!isNaN(parseFloat(euro)) && /[\d]/.test(euro)) return {num:parseFloat(euro), raw:t, isNum:true};
    const eng = t.replace(/,/g,"").replace(/[^\d\.\-]/g,"");
    if (!isNaN(parseFloat(eng)) && /[\d]/.test(eng)) return {num:parseFloat(eng), raw:t, isNum:true};
    return {num:0, raw:t.toLowerCase(), isNum:false};
  }

  function sortByColumn(colIndex, asc){
    const rows = Array.from(tbody.rows);
    rows.sort((a,b)=>{
      const A = a.cells[colIndex]?.innerText || "";
      const B = b.cells[colIndex]?.innerText || "";
      const nA = normalizeValue(A);
      const nB = normalizeValue(B);
      if (nA.isNum && nB.isNum) return asc ? (nA.num - nB.num) : (nB.num - nA.num);
      return asc ? nA.raw.localeCompare(nB.raw, "el", {numeric:true}) : nB.raw.localeCompare(nA.raw, "el", {numeric:true});
    });
    rows.forEach(r=>tbody.appendChild(r));
    thead.querySelectorAll("th").forEach(th=>th.classList.remove("sorted-asc","sorted-desc"));
    const th = thead.querySelectorAll("th")[colIndex];
    if (th) th.classList.add(asc ? "sorted-asc" : "sorted-desc");
    lastSortedIndex = colIndex; lastAsc = asc;
  }

  // ===== Resize handles & reorder =====
  thead.querySelectorAll("th").forEach((th, idx) => {
    // click-to-sort (exclude clicks on resize handle)
    th.addEventListener("click", function(e){
      if (e.target.classList.contains("resize-handle")) return;
      const colIndex = Array.from(thead.rows[0].cells).indexOf(th);
      const asc = (lastSortedIndex !== colIndex) ? true : !lastAsc;
      sortByColumn(colIndex, asc);
    });

    const handle = document.createElement("div");
    handle.className = "resize-handle";
    th.appendChild(handle);

    let startX = 0, startW = 0;
    function mmove(e){
      const dx = e.pageX - startX;
      const newW = Math.max(40, startW + dx);
      th.style.width = newW + "px";
    }
    function mup(){
      document.removeEventListener("mousemove", mmove);
      document.removeEventListener("mouseup", mup);
    }
    handle.addEventListener("mousedown", (e)=>{
      startX = e.pageX; startW = th.offsetWidth;
      document.addEventListener("mousemove", mmove);
      document.addEventListener("mouseup", mup);
      e.preventDefault(); e.stopPropagation();
    });

    // Reorder
    th.setAttribute("draggable","true");
    th.addEventListener("dragstart", (e)=>{
      e.dataTransfer.setData("text/plain", idx.toString());
    });
    th.addEventListener("dragover", (e)=>{
      e.preventDefault();
      const rect = th.getBoundingClientRect();
      const halfway = rect.left + rect.width / 2;
      th.classList.toggle("drag-over-left", e.clientX < halfway);
      th.classList.toggle("drag-over-right", e.clientX >= halfway);
    });
    th.addEventListener("dragleave", ()=>{
      th.classList.remove("drag-over-left","drag-over-right");
    });
    th.addEventListener("drop", (e)=>{
      e.preventDefault();
      const fromIndex = parseInt(e.dataTransfer.getData("text/plain"), 10);
      const headers = Array.from(thead.rows[0].cells);
      const toIndex = headers.indexOf(th);
      if (fromIndex === -1 || toIndex === -1 || fromIndex === toIndex) {
        th.classList.remove("drag-over-left","drag-over-right");
        return;
      }
      const dropOnRightHalf = th.classList.contains("drag-over-right");
      th.classList.remove("drag-over-left","drag-over-right");

      const fromTh = headers[fromIndex];
      const toTh = headers[toIndex];
      if (dropOnRightHalf) {
        toTh.after(fromTh);
      } else {
        toTh.before(fromTh);
      }

      // reorder cells
      const newHeaders = Array.from(thead.rows[0].cells);
      const newOrderMap = {};
      newHeaders.forEach((h, newPos) => {
        const origPos = headers.indexOf(h);
        newOrderMap[newPos] = origPos;
      });

      Array.from(tbody.rows).forEach(tr => {
        const cells = Array.from(tr.cells);
        const newCells = new Array(cells.length);
        for (let newPos=0; newPos<newCells.length; newPos++){
          const origPos = newOrderMap[newPos];
          newCells[newPos] = cells[origPos];
        }
        newCells.forEach((c, i)=>{
          if (i === 0) tr.appendChild(c); else newCells[i-1].after(c);
        });
      });

      thead.querySelectorAll("th").forEach(h=>h.classList.remove("sorted-asc","sorted-desc"));
      lastSortedIndex = -1;
    });
  });

  // ===== Select all / none (checkbox in header if any) =====
  const headerCheckbox = document.getElementById("selectAll");
  if (headerCheckbox){
    headerCheckbox.addEventListener("change", function(){
      const chks = table.querySelectorAll('input[type="checkbox"][name="delete_mark"]');
      chks.forEach(c => { c.checked = headerCheckbox.checked; });
    });
  }
});
</script>
</body>
</html>
"""
CONFIG_HTML = """
<!doctype html>
<html lang="el">
<head>
    <meta charset="UTF-8">
    <title>Ρύθμιση Παραμέτρων</title>
    <style>
        body {font-family: Arial, sans-serif; max-width: 600px; margin: 20px auto; padding: 20px;}
        .form-group {margin-bottom: 15px;}
        label {display: block; margin-bottom: 5px; font-weight: bold;}
        input[type="text"], select {width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px;}
        button {background: #0d6efd; color: white; border: none; padding: 10px 15px; border-radius: 4px; cursor: pointer;}
        button:hover {background: #0b5ed7;}
        .card {background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);}
    </style>
</head>
<body>
    <div class="card">
        <h1>Ρύθμιση Παραμέτρων AADE</h1>
        <form method="post">
            <div class="form-group">
                <label for="aade_user_id">AADE User ID:</label>
                <input type="text" id="aade_user_id" name="aade_user_id" value="{{ config.get('AADE_USER_ID', '') }}" required>
            </div>
            
            <div class="form-group">
                <label for="aade_subscription_key">AADE Subscription Key:</label>
                <input type="text" id="aade_subscription_key" name="aade_subscription_key" value="{{ config.get('AADE_SUBSCRIPTION_KEY', '') }}" required>
            </div>
            
            <div class="form-group">
                <label for="mydata_env">Περιβάλλον:</label>
                <select id="mydata_env" name="mydata_env">
                    <option value="sandbox" {% if config.get('MYDATA_ENV') == 'sandbox' %}selected{% endif %}>Sandbox (δοκιμαστικό)</option>
                    <option value="production" {% if config.get('MYDATA_ENV') == 'production' %}selected{% endif %}>Production (πραγματικό)</option>
                </select>
            </div>
            
            <button type="submit">Αποθήκευση Ρυθμίσεων</button>
        </form>
        
        <p style="margin-top: 20px;">
            <a href="{{ url_for('home') }}">Επιστροφή στην αρχική σελίδα</a>
        </p>
    </div>
</body>
</html>
"""

# Routes
@app.route("/")
def home():
    return render_template_string(NAV_HTML)

@app.route("/options")
def options():
    return render_template_string(PLACEHOLDER_HTML, title="Επιλογές", message="Εδώ θα μπουν μελλοντικές ρυθμίσεις.")

@app.route('/config', methods=['GET', 'POST'])
def config():
    """Configuration page for users to input their AADE credentials"""
    if request.method == 'POST':
        # Get form data
        user_id = request.form.get('aade_user_id')
        subscription_key = request.form.get('aade_subscription_key')
        environment = request.form.get('mydata_env', 'sandbox')
        
        # Save configuration
        config_data = {
            'AADE_USER_ID': user_id,
            'AADE_SUBSCRIPTION_KEY': subscription_key,
            'MYDATA_ENV': environment
        }
        
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config_data, f)
            return redirect(url_for('home'))
        except Exception as e:
            return f"Error saving configuration: {e}"
    
    # Load existing config if available
    config_data = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config_data = json.load(f)
        except:
            pass
    
    return render_template_string(CONFIG_HTML, config=config_data)

@app.route("/viewer", methods=["GET", "POST"])
def viewer():
    # Check if we have valid configuration
    config_data = load_config()
    if not config_data.get("AADE_USER_ID") or not config_data.get("AADE_SUBSCRIPTION_KEY"):
        return redirect(url_for('config'))
    
    # Use the configuration
    AADE_USER = config_data.get("AADE_USER_ID", "")
    AADE_KEY = config_data.get("AADE_SUBSCRIPTION_KEY", "")
    ENV = config_data.get("MYDATA_ENV", "sandbox").lower()
    
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
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
