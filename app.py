from flask import Flask, render_template, request, redirect, url_for, send_file, session
import requests, os, sqlite3
from bs4 import BeautifulSoup
from werkzeug.utils import secure_filename
from datetime import datetime
import pytesseract
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from io import BytesIO

# -----------------------------
# Flask App Setup
# -----------------------------
app = Flask(__name__)
app.secret_key = "your_secret_key"   # Required for sessions

UPLOAD_FOLDER = "static/uploads"
PROCESSED_FOLDER = "static/processed"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

DB_PATH = "compliance.db"

# -----------------------------
# DB Helper
# -----------------------------
def run_query(q, params=(), fetch=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(q, params)
    res = None
    if fetch:
        res = c.fetchall()
    else:
        conn.commit()
    conn.close()
    return res

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Products table
    c.execute('''CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, brand TEXT, seller TEXT, category TEXT,
        scanned_at TEXT, source_url TEXT,
        mrp TEXT, net_qty TEXT, manufacturer TEXT, country_of_origin TEXT,
        consumer_care TEXT, raw_text TEXT
    )''')
    # Violations table
    c.execute('''CREATE TABLE IF NOT EXISTS violations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER, issue TEXT, severity TEXT,
        detected_at TEXT, status TEXT DEFAULT 'Open',
        FOREIGN KEY(product_id) REFERENCES products(id)
    )''')
    conn.commit()
    conn.close()

init_db()

# -----------------------------
# Helper to create dummy placeholder images
# -----------------------------
def create_placeholder_image(path, text):
    img = Image.new('RGB', (400, 300), color=(200, 200, 200))
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    w, h = d.textsize(text, font=font)
    d.text(((400-w)/2,(300-h)/2), text, fill=(50,50,50), font=font)
    img.save(path)

# -----------------------------
# Login Route (Default Page)
# -----------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == "1234" and password == "1234":
            session["user"] = username
            return redirect(url_for("home"))
        else:
            error = "Invalid username or password"

    return render_template("login.html", error=error)

# -----------------------------
# Logout Route
# -----------------------------
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# -----------------------------
# Protected Routes Decorator
# -----------------------------
def login_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper

# -----------------------------
# Standard Pages
# -----------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")

@app.route("/home")
@login_required
def home():
    return render_template("home.html")

@app.route("/violation_reports")
@login_required
def violation_reports():
    return render_template("violation_reports.html")

@app.route("/categories")
@login_required
def categories():
    return render_template("categories.html")

@app.route("/geo_heatmap")
@login_required
def geo_heatmap():
    return render_template("geo_heatmap.html")

@app.route("/rule_engine")
@login_required
def rule_engine():
    return render_template("rule_engine.html")

@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html")

# -----------------------------
# Product Monitoring
# -----------------------------
@app.route("/product_monitoring")
@login_required
def product_monitoring():
    return render_template("product_monitoring.html", results=None)

@app.route("/check_product", methods=["POST"])
@login_required
def check_product():
    url = request.form.get("url")
    image = request.files.get("image")

    results = {"url": url, "filename": None, "processed_file": None, "data": {}, "compliant": True}

    # --- CASE 1: URL provided ---
    if url:
        headers = {"User-Agent": "Mozilla/5.0"}
        page = requests.get(url, headers=headers)
        soup = BeautifulSoup(page.text, "html.parser")

        title = soup.select_one("#productTitle")
        mrp = soup.select_one(".a-price .a-offscreen")
        img = soup.select_one("#landingImage")

        results["data"] = {
            "product": title.get_text(strip=True) if title else "Unknown Product",
            "mrp": mrp.get_text(strip=True) if mrp else "Not Found",
            "net_quantity": "Not Found",
            "manufacturer": "Not Found",
            "country": "Not Found",
            "care": "Not Found"
        }

        if img and img.get("src"):
            results["filename"] = img["src"]

        if results["data"]["mrp"] == "Not Found" or results["data"]["country"] == "Not Found":
            results["compliant"] = False
            results["data"]["issue"] = "Missing mandatory fields"

        run_query('''INSERT INTO products
            (title, brand, seller, category, scanned_at, source_url,
             mrp, net_qty, manufacturer, country_of_origin, consumer_care, raw_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (results["data"]["product"], None, None, None, datetime.now().isoformat(),
             url, results["data"]["mrp"], results["data"]["net_quantity"],
             results["data"]["manufacturer"], results["data"]["country"],
             results["data"]["care"], ""))

        product_id = run_query("SELECT last_insert_rowid()", fetch=True)[0][0]

        if not results["compliant"]:
            run_query('''INSERT INTO violations (product_id, issue, severity, detected_at)
                         VALUES (?, ?, ?, ?)''',
                      (product_id, results["data"].get("issue", "Unknown"), "High", datetime.now().isoformat()))

    # --- CASE 2: Image uploaded ---
    elif image:
        filename = secure_filename(image.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        image.save(filepath)
        results["filename"] = filepath

        # OCR
        text = pytesseract.image_to_string(Image.open(filepath))

        results["data"] = {
            "product": "Uploaded Product",
            "mrp": "₹" + text.split("MRP")[-1].split("\n")[0].strip() if "MRP" in text else "Not Found",
            "net_quantity": "500g" if "500g" in text else "Not Found",
            "manufacturer": "ABC Foods" if "ABC" in text else "Not Found",
            "country": "India" if "India" in text else "Not Found",
            "care": "care@abc.com" if "@" in text else "Not Found"
        }

        if results["data"]["mrp"] == "Not Found" or results["data"]["country"] == "Not Found":
            results["compliant"] = False
            results["data"]["issue"] = "Missing mandatory fields"

        processed_path = os.path.join(PROCESSED_FOLDER, "processed_" + filename)
        Image.open(filepath).save(processed_path)
        results["processed_file"] = processed_path

        run_query('''INSERT INTO products
            (title, brand, seller, category, scanned_at, source_url,
             mrp, net_qty, manufacturer, country_of_origin, consumer_care, raw_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (results["data"]["product"], None, None, None, datetime.now().isoformat(),
             None, results["data"]["mrp"], results["data"]["net_quantity"],
             results["data"]["manufacturer"], results["data"]["country"],
             results["data"]["care"], text))

        product_id = run_query("SELECT last_insert_rowid()", fetch=True)[0][0]
        results["product_id"] = product_id  

        if not results["compliant"]:
            run_query('''INSERT INTO violations (product_id, issue, severity, detected_at)
                         VALUES (?, ?, ?, ?)''',
                      (product_id, results["data"].get("issue", "Unknown"), "High", datetime.now().isoformat()))

    return render_template("product_monitoring.html", results=results)

# -----------------------------
# Download PDF Report (Properly)
# -----------------------------
@app.route("/download_report", methods=["POST"])
def download_report():
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    import os
    from datetime import datetime

    # Dummy image paths
    uploaded_file = "static/uploads/img1.png"
    processed_file = "static/processed/img2.png"

    # Dummy OCR text
    ocr_text = """Product Name: Milk 500ml
Batch No: 12345
Expiry Date: 2025-12-31
Price: 50 INR
Weight: 500ml
Ingredients: Milk, Vitamins"""

    # Dummy violations
    violations = [
        {"rule": "Incorrect Weight", "violation": "Expected 500ml, Found 480ml"},
        {"rule": "Missing Declaration", "violation": "Vitamin content not mentioned"},
        {"rule": "Wrong Price", "violation": "Displayed price 50 INR, should be 52 INR"}
    ]

    pdf_path = "static/violation_report.pdf"
    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4

    # Header
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, height-50, "Violation Report")
    c.setFont("Helvetica", 10)
    c.drawString(40, height-70, f"Generated On: {datetime.now().strftime('%d-%m-%Y %H:%M')}")

    # Uploaded Image
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, height-100, "1. Uploaded Image")
    if os.path.exists(uploaded_file):
        c.drawImage(uploaded_file, 40, height-400, width=250, height=180)

    # Processed Image
    c.drawString(320, height-100, "2. Processed Image")
    if os.path.exists(processed_file):
        c.drawImage(processed_file, 320, height-400, width=250, height=180)

    # OCR Extracted Text
    c.drawString(40, height-420, "3. OCR Extracted Text")
    y_text = height-440
    c.setFont("Helvetica", 10)
    for line in ocr_text.split("\n"):
        c.drawString(50, y_text, line)
        y_text -= 15

    # Violation Rules Table
    c.drawString(40, y_text-20, "4. Violation Rules Detected")
    data = [["Rule", "Violation Detected"]]
    for v in violations:
        data.append([v["rule"], v["violation"]])

    table = Table(data, colWidths=[200, 300])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('ALIGN',(0,0),(-1,-1),'LEFT'),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold')
    ]))
    table.wrapOn(c, width, height)
    table.drawOn(c, 40, y_text-160)

    c.save()
    return send_file(pdf_path, as_attachment=True)  

# -----------------------------
# Run App
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True)
