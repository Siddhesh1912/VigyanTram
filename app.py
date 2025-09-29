from flask import Flask, render_template, request, redirect, url_for, send_file, session
import requests, os, sqlite3
from bs4 import BeautifulSoup
from werkzeug.utils import secure_filename
from datetime import datetime
import pytesseract
from PIL import Image, ImageDraw, ImageFont
from PIL import ImageFile, ImageFilter, ImageOps
from PIL import UnidentifiedImageError
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from io import BytesIO
import difflib
import re

# Prefer explicit Tesseract path on Windows per user setup
try:
    if os.name == 'nt':
        t_path = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
        if os.path.exists(t_path):
            pytesseract.pytesseract.tesseract_cmd = t_path
except Exception as _e:
    print("Warning: could not set Tesseract path:", _e)

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

# Allow loading of truncated images to avoid hard failures on partial uploads
ImageFile.LOAD_TRUNCATED_IMAGES = True

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
import csv

def load_products_csv(file_path):
    """Load products from CSV file"""
    products = []
    try:
        with open(file_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                products.append(row)
    except FileNotFoundError:
        print(f"Warning: CSV file {file_path} not found")
    except Exception as e:
        print(f"Error loading CSV file {file_path}: {e}")
    return products

# Load all CSV data
laptop_products = load_products_csv("data/laptop.csv")
mobile_products = load_products_csv("data/mobile.csv")
protein_products = load_products_csv("data/protein.csv")

# Combine all products for general use
all_products = laptop_products + mobile_products + protein_products

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
# Fuzzy match OCR text to CSV products
# -----------------------------
def _normalize_text(value):
    if not value:
        return ""
    value = value.lower()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value

def find_best_csv_match(ocr_text, products):
    """Return (best_product, best_score_float_0_to_1). Compares OCR text to product name/details.
    Uses difflib ratio; not heavy and no extra deps.
    """
    if not ocr_text or not products:
        return None, 0.0
    ocr_norm = _normalize_text(ocr_text)
    if not ocr_norm:
        return None, 0.0

    best = None
    best_score = 0.0
    for product in products:
        name = _normalize_text(product.get('name') or product.get('Product Name') or "")
        details = _normalize_text(product.get('details') or product.get('Details') or "")
        combo = (name + " " + details).strip()
        if not combo:
            continue
        score = difflib.SequenceMatcher(None, ocr_norm, combo).ratio()
        # Also try just name to avoid details noise
        if name:
            score = max(score, difflib.SequenceMatcher(None, ocr_norm, name).ratio())
        if score > best_score:
            best = product
            best_score = score
    return best, best_score

# Return top matches at or above a minimum ratio
def find_top_csv_matches(ocr_text, products, min_ratio=0.5, limit=5):
    if not ocr_text or not products:
        return []
    ocr_norm = _normalize_text(ocr_text)
    if not ocr_norm:
        return []

    scored = []
    for product in products:
        name = _normalize_text(product.get('name') or product.get('Product Name') or "")
        details = _normalize_text(product.get('details') or product.get('Details') or "")
        combo = (name + " " + details).strip()
        if not combo:
            continue
        score = difflib.SequenceMatcher(None, ocr_norm, combo).ratio()
        if name:
            score = max(score, difflib.SequenceMatcher(None, ocr_norm, name).ratio())
        if score >= min_ratio:
            scored.append({
                "product": product,
                "score": round(score * 100, 2)
            })
    # sort by score desc and take top N
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]

# -----------------------------
# Path normalization for URLs
# -----------------------------
def to_url_path(p):
    if not p:
        return p
    return p.replace('\\', '/')

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
    # Pass CSV data organized by categories
    return render_template("categories.html", 
                         laptop_products=laptop_products,
                         mobile_products=mobile_products,
                         protein_products=protein_products)

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
# CSV Data Routes
# -----------------------------
@app.route("/data/<filename>")
@login_required
def serve_csv(filename):
    """Serve CSV files from the data directory"""
    import os
    csv_path = os.path.join("data", filename)
    if os.path.exists(csv_path):
        return send_file(csv_path, mimetype='text/csv')
    else:
        return "File not found", 404

# -----------------------------
# Product Monitoring
# -----------------------------
@app.route("/product_monitoring")
@login_required
def product_monitoring():
    # Pass CSV data to template for display
    return render_template("product_monitoring.html", 
                         results=None, 
                         laptop_products=laptop_products[:10],  # Show first 10 for demo
                         mobile_products=mobile_products[:10],
                         protein_products=protein_products[:10])

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

        # Compliance decision: if matched with high confidence, mark compliant; otherwise use missing fields
        if extracted_data.get("matched_from_csv") and extracted_data.get("match_score", 0) >= 90:
            results["compliant"] = True
            results["data"]["compliance_note"] = "Matched product in catalog with high confidence (>=90%)."
        else:
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
        results["filename"] = to_url_path(filepath)

        # Try to open the image robustly
        try:
            pil_img = Image.open(filepath)
            pil_img.load()  # force loading to catch issues early
        except UnidentifiedImageError:
            # Gracefully report invalid image and return page
            results["compliant"] = False
            results["data"] = {"issue": "Invalid or corrupted image. Please recapture or upload a valid image."}
            return render_template("product_monitoring.html", results=results)
        except Exception as _open_e:
            print('Image open error:', _open_e)
            results["compliant"] = False
            results["data"] = {"issue": "Unable to read the uploaded image."}
            return render_template("product_monitoring.html", results=results)

        # OCR with Pillow-only preprocessing (no OpenCV dependency)
        try:
            pil_gray = pil_img.convert('L')
            w, h = pil_gray.size
            pil_gray = pil_gray.resize((w*2, h*2))
            pil_blur = pil_gray.filter(ImageFilter.GaussianBlur(radius=1))
            pil_autocontrast = ImageOps.autocontrast(pil_blur)
            # Simple threshold to boost contrast
            pil_thresh = pil_autocontrast.point(lambda p: 255 if p > 160 else 0)
            text = pytesseract.image_to_string(pil_thresh, config='--oem 3 --psm 6')
            processed_image_for_save = pil_thresh
        except Exception as _pe:
            print('Pillow preprocess error:', _pe)
            try:
                text = pytesseract.image_to_string(pil_img, config='--oem 3 --psm 6')
                processed_image_for_save = pil_img
            except Exception as _pe2:
                print('OCR fallback error:', _pe2)
                results["compliant"] = False
                results["data"] = {"issue": "OCR failed on the uploaded image."}
                return render_template("product_monitoring.html", results=results)

        # Extract data from OCR text and validate against CSV data
        extracted_data = {
            "product": "Uploaded Product",
            "mrp": "₹" + text.split("MRP")[-1].split("\n")[0].strip() if "MRP" in text else "Not Found",
            "net_quantity": "500g" if "500g" in text else "Not Found",
            "manufacturer": "ABC Foods" if "ABC" in text else "Not Found",
            "country": "India" if "India" in text else "Not Found",
            "care": "care@abc.com" if "@" in text else "Not Found"
        }
        
        # Try to match with existing products in CSV data (fuzzy >= 0.9)
        matched_product, match_score = find_best_csv_match(text, all_products)
        if matched_product and match_score >= 0.90:
            # Merge best-known fields from CSV
            extracted_data.update({
                "product": matched_product.get('name') or matched_product.get('Product Name') or extracted_data.get('product'),
                "mrp": matched_product.get('price') or matched_product.get('Price') or extracted_data.get('mrp'),
                "matched_from_csv": True,
                "match_score": round(match_score * 100, 2)
            })
        
        results["data"] = extracted_data

        if results["data"]["mrp"] == "Not Found" or results["data"]["country"] == "Not Found":
            results["compliant"] = False
            results["data"]["issue"] = "Missing mandatory fields"

        processed_path = os.path.join(PROCESSED_FOLDER, "processed_" + filename)
        try:
            processed_image_for_save.save(processed_path)
        except Exception as _se:
            print('Processed save error:', _se)
            Image.open(filepath).save(processed_path)
        results["processed_file"] = to_url_path(processed_path)
        results["raw_text"] = text

        # Compute 50%+ similarity matches across all CSVs
        try:
            top_matches = find_top_csv_matches(text, all_products, min_ratio=0.50, limit=5)
        except Exception as _me:
            print('Match computation error:', _me)
            top_matches = []

        # Prepare compact compare summary for UI
        compare_summary = {
            "threshold": 50,
            "has_match": True if top_matches else False,
            "top_matches": [
                {
                    "name": (m["product"].get('name') or m["product"].get('Product Name') or "Unnamed Product"),
                    "price": (m["product"].get('price') or m["product"].get('Price') or "N/A"),
                    "details": (m["product"].get('details') or m["product"].get('Details') or ""),
                    "score_percent": m["score"]
                }
                for m in top_matches
            ]
        }
        results["compare"] = compare_summary

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

        # Append extracted data to CSV log
        try:
            csv_log_path = os.path.join("data", "captures.csv")
            os.makedirs("data", exist_ok=True)
            file_exists = os.path.exists(csv_log_path)
            import csv as _csv
            with open(csv_log_path, mode="a", newline="", encoding="utf-8") as f:
                writer = _csv.writer(f)
                if not file_exists:
                    writer.writerow([
                        "timestamp","filename","processed_file","product","mrp","net_quantity","manufacturer",
                        "country","care","compliant","issue","product_id","raw_text_preview"
                    ])
                writer.writerow([
                    datetime.now().isoformat(),
                    results.get("filename"),
                    results.get("processed_file"),
                    results["data"].get("product"),
                    results["data"].get("mrp"),
                    results["data"].get("net_quantity"),
                    results["data"].get("manufacturer"),
                    results["data"].get("country"),
                    results["data"].get("care"),
                    results.get("compliant"),
                    results["data"].get("issue"),
                    product_id,
                    (text[:200] if text else None)
                ])
        except Exception as e:
            print("CSV log write error:", e)

        # Write full extracted text to a dedicated CSV log
        try:
            extracted_csv_path = os.path.join("data", "extracted_texts.csv")
            os.makedirs("data", exist_ok=True)
            file_exists_et = os.path.exists(extracted_csv_path)
            import csv as _csv
            with open(extracted_csv_path, mode="a", newline="", encoding="utf-8") as f:
                writer = _csv.writer(f)
                if not file_exists_et:
                    writer.writerow(["timestamp", "filename", "processed_file", "product_id", "full_text"]) 
                writer.writerow([
                    datetime.now().isoformat(),
                    results.get("filename"),
                    results.get("processed_file"),
                    product_id,
                    text
                ])
        except Exception as e:
            print("Extracted text CSV write error:", e)

    return render_template("product_monitoring.html", results=results)

@app.route("/search_products", methods=["GET", "POST"])
@login_required
def search_products():
    if request.method == "POST":
        search_term = request.form.get("search_term", "").strip().lower()
        category = request.form.get("category", "all")
        
        # Only filter if there's an actual search term
        if search_term:
            filtered_products = []
            
            if category == "laptop" or category == "all":
                filtered_products.extend([p for p in laptop_products if search_term in p.get('name', '').lower()])
            if category == "mobile" or category == "all":
                filtered_products.extend([p for p in mobile_products if search_term in p.get('name', '').lower()])
            if category == "protein" or category == "all":
                filtered_products.extend([p for p in protein_products if search_term in p.get('name', '').lower()])
        else:
            # No search term, don't show search results
            filtered_products = None
        
        return render_template("categories.html", 
                             laptop_products=laptop_products,
                             mobile_products=mobile_products,
                             protein_products=protein_products,
                             search_results=filtered_products,
                             search_term=search_term,
                             selected_category=category)
    
    return render_template("categories.html", 
                         laptop_products=laptop_products,
                         mobile_products=mobile_products,
                         protein_products=protein_products)

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

    # Use actual uploaded files if they exist, otherwise use placeholder
    uploaded_file = "static/uploads/img1.png"
    processed_file = "static/processed/img2.png"
    
    # Check if files exist, if not create placeholder
    if not os.path.exists(uploaded_file):
        create_placeholder_image(uploaded_file, "Uploaded Image")
    if not os.path.exists(processed_file):
        create_placeholder_image(processed_file, "Processed Image")

    # Generate OCR text from sample product data
    sample_product = all_products[0] if all_products else {}
    ocr_text = f"""Product Name: {sample_product.get('name', 'Sample Product')}
Price: {sample_product.get('price', 'Not Available')}
Details: {sample_product.get('details', 'No details available')}
Image URL: {sample_product.get('image_url', 'No image')}"""

    # Generate violations based on CSV data analysis
    violations = []
    if all_products:
        # Check for common compliance issues
        for product in all_products[:5]:  # Check first 5 products
            if not product.get('price'):
                violations.append({"rule": "Missing Price", "violation": f"Product {product.get('name', 'Unknown')} has no price information"})
            if not product.get('details'):
                violations.append({"rule": "Missing Details", "violation": f"Product {product.get('name', 'Unknown')} has no product details"})
    
    # If no violations found, add some sample ones
    if not violations:
        violations = [
            {"rule": "Data Validation", "violation": "All products have required information"},
            {"rule": "Price Compliance", "violation": "Prices are within acceptable ranges"},
            {"rule": "Product Details", "violation": "Product descriptions are complete"}
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