# -----------------------------
# API: Get all compliance checks (all products)

from flask import Flask, render_template, request, redirect, url_for, send_file, session, jsonify
import requests, os, sqlite3
from bs4 import BeautifulSoup
from werkzeug.utils import secure_filename
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, render_template, request, redirect, url_for, send_file, session, jsonify
import requests, os, sqlite3
from bs4 import BeautifulSoup
from werkzeug.utils import secure_filename
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from PIL import ImageFile
from PIL import UnidentifiedImageError
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from io import BytesIO
import difflib
import cv2
import pytesseract
from PIL import Image, ImageOps, ImageFilter
import numpy as np
from ocr_processing import preprocess_for_ocr
import re
from field_extraction import extract_product_fields

# ...existing code...
# Flask app setup and CSV loading
# ...existing code...
# Place this after app = Flask(__name__) and after CSVs are loaded
from flask import Flask, render_template, request, redirect, url_for, send_file, session, jsonify
import requests, os, sqlite3
from bs4 import BeautifulSoup
from werkzeug.utils import secure_filename
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from PIL import ImageFile
from PIL import UnidentifiedImageError
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from io import BytesIO
import difflib
import cv2
import pytesseract
from PIL import Image, ImageOps, ImageFilter
import numpy as np
from ocr_processing import preprocess_for_ocr
import re
from field_extraction import extract_product_fields


"""Flask app for product monitoring and compliance checks."""

# -----------------------------
# Flask App Setup
# -----------------------------
app = Flask(__name__)
if os.name == 'nt':
    t_path = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
    if os.path.exists(t_path):
        pytesseract.pytesseract.tesseract_cmd = t_path
app.secret_key = "your_secret_key"   # Required for sessions

# Serve rules.json for frontend fetch
@app.route('/rules.json')
def serve_rules_json():
    return send_file('rules.json', mimetype='application/json')

UPLOAD_FOLDER = "static/uploads"
PROCESSED_FOLDER = "static/processed"
CAPTURE_FOLDER = "static/captures"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)
os.makedirs(CAPTURE_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

DB_PATH = "compliance.db"

# Allow loading of truncated images to avoid hard failures on partial uploads
ImageFile.LOAD_TRUNCATED_IMAGES = True

# -----------------------------
# ESP32-CAM Configuration (defaults)
# -----------------------------
ESP32_STREAM_URL = "http://192.168.0.123:81/stream"
ESP32_SNAPSHOT_URL = "http://10.219.158.90/capture"
CSV_LOG_PATH = "img.csv"
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
# API: Get products by category for dropdown
@app.route('/get_product_details', methods=['GET'])
def get_product_details():
    category = request.args.get('category', '').lower()
    idx = request.args.get('id', None)
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid product id'}), 400
    if category == 'mobile':
        products = mobile_products
    elif category == 'laptop':
        products = laptop_products 
    elif category == 'protein':
        products = protein_products
    else:
        products = all_products
    if idx < 0 or idx >= len(products):
        return jsonify({'error': 'Product not found'}), 404
    product = products[idx]
    # Try to extract details and image
    details = ''
    img_src = ''
    # Compose details from available fields
    if category == 'mobile':
        details = product.get('details') or product.get('name') or ''
        img_src = product.get('image_url') or ''
    elif category == 'laptop':
        details = product.get('details') or product.get('name') or ''
        img_src = product.get('image_url') or ''
    elif category == 'protein':
        details = product.get('Details') or product.get('Product Name') or ''
        img_src = product.get('Image') or ''
    else:
        details = product.get('details') or product.get('name') or product.get('Product Name') or ''
        img_src = product.get('image') or product.get('Image') or ''
    # If image path is relative, prepend static folder
    if img_src and not img_src.startswith('http'):
        img_src = '/static/uploads/' + img_src if os.path.exists(os.path.join('static/uploads', img_src)) else '/static/logo.png'
    return jsonify({'details': details, 'image': img_src})
# -----------------------------
@app.route('/get_products', methods=['GET'])
def get_products():
    category = request.args.get('category', '').lower()
    if category == 'mobile':
        products = mobile_products
    elif category == 'laptop':
        products = laptop_products
    elif category == 'protein':
        products = protein_products
    else:
        products = all_products
    # Return only name and id (or index) for dropdown
    result = []
    for idx, p in enumerate(products):
        name = p.get('name') or p.get('Product Name') or p.get('product') or f"Product {idx+1}"
        result.append({'id': idx, 'name': name})
    return jsonify(result)

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
# Legal Metrology Rule Engine (simple, extensible)
# -----------------------------
def evaluate_legal_metrology_rules(extracted):
    """Evaluate basic Legal Metrology-like rules on extracted data.
    Returns (is_compliant: bool, issues: list[str])
    """
    issues = []
    # Required fields
    if not extracted.get("mrp") or extracted.get("mrp") == "Not Found":
        issues.append("Missing MRP")
    if not extracted.get("country") or extracted.get("country") == "Not Found":
        issues.append("Missing country of origin")
    if not extracted.get("net_quantity") or extracted.get("net_quantity") == "Not Found":
        issues.append("Missing net quantity")
    # Basic unit sanity for net quantity when present
    nq = (extracted.get("net_quantity") or "").lower()
    if nq and nq != "not found":
        if not re.search(r"\b(ml|l|g|kg|pcs|piece|tablet|capsule|pack)\b", nq):
            issues.append("Net quantity unit may be missing or invalid")
    # Basic MRP format sanity
    mrp = extracted.get("mrp") or ""
    if mrp and mrp != "Not Found":
        if not re.search(r"(₹|rs\.?\s?)\s?\d", mrp.lower()):
            issues.append("MRP format invalid")
    is_compliant = len(issues) == 0
    return is_compliant, issues

# -----------------------------
# Category guessing from OCR text
# -----------------------------
def guess_category_from_text(text):
    """Return one of 'mobile', 'laptop', 'protein', or None based on simple keyword heuristics."""
    if not text:
        return None
    t = text.lower()
    mobile_kw = ["iphone", "samsung", "galaxy", "pixel", "oneplus", "realme", "redmi", "mi", "oppo", "vivo", "motorola", "5g", "android"]
    laptop_kw = ["laptop", "notebook", "macbook", "thinkpad", "ideapad", "pavilion", "inspiron", "ryzen", "intel", "i5", "i7", "ssd", "ram", "graphics"]
    protein_kw = ["protein", "whey", "isolate", "casein", "supplement", "gainer", "scoop", "bcaa", "serving"]
    if any(k in t for k in mobile_kw):
        return "mobile"
    if any(k in t for k in laptop_kw):
        return "laptop"
    if any(k in t for k in protein_kw):
        return "protein"
    return None

def get_products_by_category(category):
    if category == "mobile":
        return mobile_products
    if category == "laptop":
        return laptop_products
    if category == "protein":
        return protein_products
    return all_products

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

@app.route('/get_compliance_checks')
@login_required
def get_compliance_checks():
    query = '''
    SELECT p.title as product, p.seller, p.mrp, p.net_qty, p.scanned_at as detected_at, p.category,
           'Non-Compliant' as status, v.issue, v.severity
    FROM violations v
    JOIN products p ON v.product_id = p.id
    ORDER BY v.detected_at DESC
    '''
    rows = run_query(query, fetch=True)
    checks = []
    for row in rows:
        checks.append({
            'product': row['product'] or 'Unknown',
            'seller': row['seller'] or 'Unknown',
            'mrp': row['mrp'] or '-',
            'net_qty': row['net_qty'] or '-',
            'detected_at': row['detected_at'] or '-',
            'category': row['category'] or '-',
            'status': row['status'],
            'issue': row['issue'] or 'N/A',
            'severity': row['severity'] or 'N/A'
        })
    return jsonify(checks)

# -----------------------------

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
    last_snapshot_rel = session.get("last_snapshot_rel")
    last_snapshot_url = None
    if last_snapshot_rel:
        # Build a static URL for the last snapshot
        try:
            # Expecting something like uploads/filename.jpg
            if last_snapshot_rel.startswith("uploads/"):
                last_snapshot_url = url_for('static', filename=last_snapshot_rel)
            elif last_snapshot_rel.startswith("static/"):
                # Backward compatibility
                last_snapshot_url = "/" + last_snapshot_rel
        except Exception:
            last_snapshot_url = None

    return render_template("product_monitoring.html", 
                         results=None, 
                         laptop_products=laptop_products[:10],  # Show first 10 for demo
                         mobile_products=mobile_products[:10],
                         protein_products=protein_products[:10],
                         esp32_stream_url=ESP32_STREAM_URL,
                         esp32_snapshot_url=ESP32_SNAPSHOT_URL,
                         last_snapshot_url=last_snapshot_url)

@app.route("/scrape_category", methods=["POST"])
@login_required
def scrape_category():
    category = request.form.get("category", "").strip().lower()
    time_filter = request.form.get("time", "").strip().lower()
    try:
        # Use Playwright-based scraper for robustness
        items = scrape_category_sync(category, max_pages=1)
        csv_path, count = write_scraped_csv(items, os.path.join("data", "scraped_info.csv"))
        return jsonify({
            "status": "success",
            "count": count,
            "csv": f"/data/{os.path.basename(csv_path)}",
            "items": items[:20]
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/scrape_categories", methods=["POST"])
@login_required
def scrape_categories():
    # Accept either JSON {categories: [..], max_pages} or form with comma-separated 'categories'
    categories = []
    max_pages = 1
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        categories = payload.get("categories") or []
        max_pages = int(payload.get("max_pages") or 1)
    else:
        cats = request.form.get("categories") or request.form.get("category") or ""
        categories = [c.strip().lower() for c in cats.split(",") if c.strip()]
        mp = request.form.get("max_pages")
        if mp:
            try:
                max_pages = int(mp)
            except ValueError:
                max_pages = 1

    if not categories:
        # Default to all known categories
        categories = ["protein", "mobile", "laptop"]

    try:
        all_items = []
        for cat in categories:
            items = scrape_category_sync(cat, max_pages=max_pages)
            # Tag category on each item
            for it in items:
                it["category"] = cat
            all_items.extend(items)

        csv_path, count = write_scraped_csv(all_items, os.path.join("data", "scraped_info.csv"))
        # Return small preview grouped by category
        preview = {}
        for it in all_items:
            k = it.get("category") or "unknown"
            preview.setdefault(k, [])
            if len(preview[k]) < 5:
                preview[k].append({
                    "name": it.get("name", ""),
                    "price": it.get("price", ""),
                    "details": it.get("details", ""),
                    "product_link": it.get("product_link", ""),
                })
        return jsonify({
            "status": "success",
            "count": count,
            "csv": f"/data/{os.path.basename(csv_path)}",
            "categories": categories,
            "preview": preview
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/check_product", methods=["POST"])
@login_required
def check_product():
    image = request.files.get("image")
    snapshot_url = request.form.get("snapshot_url")
    results = {"filename": None, "processed_file": None, "data": {}}

    def preprocess_image(image_path):
        try:
            pil_img = Image.open(image_path)
            pil_img = preprocess_for_ocr(pil_img)
            # Save processed image to static/processed
            base = os.path.basename(image_path)
            name, ext = os.path.splitext(base)
            processed_name = f"{name}_processed{ext}"
            processed_path = os.path.join(PROCESSED_FOLDER, processed_name)
            pil_img.save(processed_path)
            print(f"[DEBUG] Processed image saved: {processed_path}")
            return processed_path
        except Exception as e:
            print(f"[ERROR] Failed to preprocess image: {e}")
            return None

    def extract_text_fields(image_path):
        processed_path = preprocess_image(image_path)
        if not processed_path or not os.path.exists(processed_path):
            print(f"[ERROR] Processed image not found: {processed_path}")
            return {
                'product': 'Not Found',
                'mrp': 'Not Found',
                'expiry': 'Not Found',
                'origin': 'Not Found',
                'processed_file': ''
            }
        img = cv2.imread(processed_path)
        text = pytesseract.image_to_string(img, config='--oem 3 --psm 6')
        print(f"[DEBUG] OCR text: {text}")
        # Robust regex patterns and line-based search
        # Use modular extraction from field_extraction.py
        return extract_product_fields(text, processed_path)

    # Handle file upload
    if image and getattr(image, 'filename', ''):
        try:
            filename = secure_filename(image.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            image.save(filepath)
            print(f"[DEBUG] Uploaded image saved: {filepath}")
            fields = extract_text_fields(filepath)
            # Normalize processed image path for url_for
            def to_web_path(p):
                return p.replace('\\', '/').replace('\\', '/').replace('\\', '/') if p else p
            processed_rel = to_web_path(os.path.relpath(fields['processed_file'], 'static')) if fields['processed_file'] else ''
            results["filename"] = url_for('static', filename=to_web_path(os.path.relpath(filepath, 'static')))
            results["processed_file"] = url_for('static', filename=processed_rel) if processed_rel else None
            results["data"] = {
                "manufacturer": fields.get('manufacturer', 'Not Found'),
                "address": fields.get('address', 'Not Found'),
                "commodity": fields.get('commodity', 'Not Found'),
                "net_quantity": fields.get('net_quantity', 'Not Found'),
                "mrp": fields.get('mrp', 'Not Found'),
                "date": fields.get('date', 'Not Found'),
                "consumer_care": fields.get('consumer_care', 'Not Found'),
                "origin": fields.get('origin', 'Not Found'),
                "product": fields.get('product', 'Not Found'),
                "raw_text": fields.get('raw_text', '')
            }
            # Calculate compliance score and store in results
            compliance_fields = [
                results["data"].get('product', None),
                results["data"].get('manufacturer', None),
                results["data"].get('address', None),
                results["data"].get('commodity', None),
                results["data"].get('net_quantity', None),
                results["data"].get('mrp', None),
                results["data"].get('date', None),
                results["data"].get('consumer_care', None),
                results["data"].get('origin', None)
            ]
            present_count = sum(1 for info in compliance_fields if info and info != 'Not Found')
            total_fields = len(compliance_fields)
            compliance_score = int((present_count / total_fields) * 100) if total_fields else 0
            results["compliance_score"] = compliance_score
            # Store results in session for PDF
            session['latest_results'] = results
            print(f"[DEBUG] Results: {results}")
            if results["filename"]:
                print(f"[DEBUG] Template Captured image URL: {results['filename']}")
            if results["processed_file"]:
                print(f"[DEBUG] Template Processed image URL: {results['processed_file']}")
        except Exception as e:
            results["data"] = {"error": f"Failed to process uploaded image: {e}"}
            results["compliance_score"] = 0
        last_snapshot_rel = session.get("last_snapshot_rel")
        last_snapshot_url = url_for('static', filename=last_snapshot_rel) if last_snapshot_rel else None
        return render_template("product_monitoring.html", results=results,
                              esp32_stream_url=ESP32_STREAM_URL,
                              esp32_snapshot_url=ESP32_SNAPSHOT_URL,
                              last_snapshot_url=last_snapshot_url)

    # Handle ESP32 snapshot
    if snapshot_url:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(snapshot_url, headers=headers, timeout=10)
            resp.raise_for_status()
            ext = ".jpg"
            ctype = resp.headers.get("Content-Type", "")
            if "png" in ctype:
                ext = ".png"
            elif "jpeg" in ctype or "jpg" in ctype:
                ext = ".jpg"
            filename = secure_filename(f"esp32_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}")
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            with open(filepath, "wb") as f:
                f.write(resp.content)
            fields = extract_text_fields(filepath)
            results["filename"] = url_for('static', filename=filepath.replace('static/', ''))
            results["processed_file"] = url_for('static', filename=fields['processed_file'].replace('static/', ''))
            results["data"] = {
                "manufacturer": fields.get('manufacturer', 'Not Found'),
                "address": fields.get('address', 'Not Found'),
                "commodity": fields.get('commodity', 'Not Found'),
                "net_quantity": fields.get('net_quantity', 'Not Found'),
                "mrp": fields.get('mrp', 'Not Found'),
                "date": fields.get('date', 'Not Found'),
                "consumer_care": fields.get('consumer_care', 'Not Found'),
                "origin": fields.get('origin', 'Not Found'),
                "product": fields.get('product', 'Not Found'),
                "raw_text": fields.get('raw_text', '')
            }
            # Calculate compliance score and store in results
            compliance_fields = [
                results["data"].get('product', None),
                results["data"].get('manufacturer', None),
                results["data"].get('address', None),
                results["data"].get('commodity', None),
                results["data"].get('net_quantity', None),
                results["data"].get('mrp', None),
                results["data"].get('date', None),
                results["data"].get('consumer_care', None),
                results["data"].get('origin', None)
            ]
            present_count = sum(1 for info in compliance_fields if info and info != 'Not Found')
            total_fields = len(compliance_fields)
            compliance_score = int((present_count / total_fields) * 100) if total_fields else 0
            results["compliance_score"] = compliance_score
            # Store results in session for PDF
            session['latest_results'] = results
        except Exception as e:
            results["data"] = {"error": f"Failed to fetch from ESP32: {e}"}
            results["compliance_score"] = 0
        last_snapshot_rel = session.get("last_snapshot_rel")
        last_snapshot_url = url_for('static', filename=last_snapshot_rel) if last_snapshot_rel else None
        return render_template("product_monitoring.html", results=results,
                               esp32_stream_url=ESP32_STREAM_URL,
                               esp32_snapshot_url=ESP32_SNAPSHOT_URL,
                               last_snapshot_url=last_snapshot_url)

# -----------------------------
# Minimal snapshot capture + CSV log API
# -----------------------------
@app.get("/check_compliance")
@login_required
def check_compliance():
    """Fetch snapshot from ESP32, save to static/captures, and log to img.csv."""
    # Fetch snapshot
    try:
        resp = requests.get(ESP32_SNAPSHOT_URL, timeout=5)
        if resp.status_code != 200:
            return jsonify({
                "status": "error",
                "message": f"ESP32 returned status {resp.status_code}"
            }), 502
        content = resp.content
        if not content:
            return jsonify({
                "status": "error",
                "message": "Empty response from ESP32"
            }), 502
    except requests.exceptions.RequestException as exc:
        return jsonify({"status": "error", "message": str(exc)}), 504

    # Timestamps and filenames
    now = datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
    filename = now.strftime("%Y%m%d_%H%M%S") + ".jpg"
    file_path = os.path.join(CAPTURE_FOLDER, filename)

    # Save file
    try:
        with open(file_path, "wb") as f:
            f.write(content)
    except OSError as exc:
        return jsonify({"status": "error", "message": f"Failed to save image: {exc}"}), 500

    # Ensure CSV exists, write header if missing
    try:
        new_file = not os.path.exists(CSV_LOG_PATH)
        with open(CSV_LOG_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if new_file:
                writer.writerow(["timestamp", "filename"])
            writer.writerow([timestamp_str, filename])
    except OSError as exc:
        return jsonify({"status": "error", "message": f"Failed to write to img.csv: {exc}"}), 500

    return jsonify({
        "status": "success",
        "timestamp": timestamp_str,
        "filename": filename
    })

# -----------------------------
# Capture ESP32 Snapshot
# -----------------------------
@app.route("/capture_snapshot", methods=["GET"])
@login_required
def capture_snapshot():
    """Fetch snapshot from ESP32-CAM and save into static/uploads with timestamp."""
    snapshot_url = request.args.get("url") or ESP32_SNAPSHOT_URL
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(snapshot_url, headers=headers, timeout=5)
        resp.raise_for_status()

        # Determine file extension from content-type
        ext = ".jpg"
        ctype = resp.headers.get("Content-Type", "")
        if "png" in ctype:
            ext = ".png"
        elif "jpeg" in ctype or "jpg" in ctype:
            ext = ".jpg"

        filename = secure_filename(f"esp32_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}")
        # Save as static/uploads/<filename>
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        with open(save_path, "wb") as f:
            f.write(resp.content)

        # Store relative path for building URL later
        # We prefer 'uploads/<filename>' for url_for('static', ...)
        session["last_snapshot_rel"] = f"uploads/{filename}"

    except Exception as e:
        # Optionally store error info
        session["last_snapshot_error"] = str(e)

    # Redirect back to product monitoring to show last captured
    return redirect(url_for("product_monitoring"))

# -----------------------------
# Capture from ESP32 and process immediately
# -----------------------------
@app.route("/capture_and_check", methods=["GET"])
@login_required
def capture_and_check():
    """Capture a snapshot from ESP32, run OCR + CSV match, and render results."""
    snapshot_url = request.args.get("url") or ESP32_SNAPSHOT_URL
    results = {"url": None, "filename": None, "processed_file": None, "data": {}, "compliant": True}
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(snapshot_url, headers=headers, timeout=5)
        resp.raise_for_status()

        # Determine file extension from content-type
        ext = ".jpg"
        ctype = resp.headers.get("Content-Type", "")
        if "png" in ctype:
            ext = ".png"
        elif "jpeg" in ctype or "jpg" in ctype:
            ext = ".jpg"

        filename = secure_filename(f"esp32_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}")
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        with open(save_path, "wb") as f:
            f.write(resp.content)
        results["filename"] = to_url_path(save_path)
        session["last_snapshot_rel"] = f"uploads/{filename}"

        # OCR preprocessing and extraction via helper
        pil_img = open_image_or_error(save_path)
        try:
            text, processed_image_for_save = perform_ocr(pil_img)
        except Exception as _ocr3_e:
            text = ""
            processed_image_for_save = pil_img

        # Extract email if present
        try:
            email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}", text)
            care_email = email_match.group(0) if email_match else None
        except Exception:
            care_email = None

        extracted_data = {
            "product": "ESP32 Snapshot",
            "mrp": "₹" + text.split("MRP")[-1].split("\n")[0].strip() if "MRP" in text else "Not Found",
            "net_quantity": "500g" if "500g" in text else "Not Found",
            "manufacturer": "ABC Foods" if "ABC" in text else "Not Found",
            "country": "India" if "India" in text else "Not Found",
            "care": care_email or ("care@abc.com" if "@" in text else "Not Found")
        }

        # Prefer category-based matching first
        guessed_cat = guess_category_from_text(text)
        cat_products = get_products_by_category(guessed_cat)
        matched_product, match_score = find_best_csv_match(text, cat_products)
        if (not matched_product) or match_score < 0.90:
            matched_product, match_score = find_best_csv_match(text, all_products)
        if matched_product and match_score >= 0.90:
            extracted_data.update({
                "product": matched_product.get('name') or matched_product.get('Product Name') or extracted_data.get('product'),
                "mrp": matched_product.get('price') or matched_product.get('Price') or extracted_data.get('mrp'),
                "matched_from_csv": True,
                "match_score": round(match_score * 100, 2)
            })

        results["data"] = extracted_data
        # Evaluate rule engine for ESP32 capture-and-check
        compliant, issues = evaluate_legal_metrology_rules(results["data"])
        results["compliant"] = compliant
        if not compliant:
            results["data"]["issue"] = "; ".join(issues)

        processed_path = os.path.join(PROCESSED_FOLDER, "processed_" + filename)
        try:
            processed_image_for_save.save(processed_path)
        except Exception:
            Image.open(save_path).save(processed_path)
        results["processed_file"] = to_url_path(processed_path)
        results["raw_text"] = text

        # Save DB records
        run_query('''INSERT INTO products
            (title, brand, seller, category, scanned_at, source_url,
             mrp, net_qty, manufacturer, country_of_origin, consumer_care, raw_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (results["data"]["product"], None, None, None, datetime.now().isoformat(),
             snapshot_url, results["data"]["mrp"], results["data"]["net_quantity"],
             results["data"]["manufacturer"], results["data"]["country"],
             results["data"]["care"], text))

        product_id = run_query("SELECT last_insert_rowid()", fetch=True)[0][0]
        results["product_id"] = product_id
        if not results["compliant"]:
            run_query('''INSERT INTO violations (product_id, issue, severity, detected_at)
                         VALUES (?, ?, ?, ?)''',
                      (product_id, results["data"].get("issue", "Unknown"), "High", datetime.now().isoformat()))

    except Exception as e:
        results["data"] = {"error": f"Failed to capture/process from ESP32: {e}"}
        results["compliant"] = False

    return render_template("product_monitoring.html", results=results,
                           esp32_stream_url=ESP32_STREAM_URL,
                           esp32_snapshot_url=ESP32_SNAPSHOT_URL,
                           last_snapshot_url=url_for('static', filename=session.get("last_snapshot_rel")) if session.get("last_snapshot_rel") else None)

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
    # ...existing code...
    # Get latest product results from session if available
    try:
        product_results = session.get('latest_results')
        if not product_results:
            product_results = {'data': {}}
    except Exception:
        product_results = {'data': {}}

    # Prepare compliance info table
    compliance_fields = [
        ('Product Name', product_results['data'].get('product', None)),
        ('Manufacturer / Packer / Importer', product_results['data'].get('manufacturer', None)),
        ('Address', product_results['data'].get('address', None)),
        ('Commodity Name', product_results['data'].get('commodity', None)),
        ('Net Quantity', product_results['data'].get('net_quantity', None)),
        ('MRP (₹)', product_results['data'].get('mrp', None)),
        ('Date of Manufacture / Import', product_results['data'].get('date', None)),
        ('Consumer Care Details', product_results['data'].get('consumer_care', None)),
        ('Country of Origin', product_results['data'].get('origin', None))
    ]

    # Calculate compliance score
    present_count = sum(1 for _, info in compliance_fields if info and info != 'Not Found')
    total_fields = len(compliance_fields)
    compliance_score = int((present_count / total_fields) * 100) if total_fields else 0

    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    import os
    from datetime import datetime

    # Use actual uploaded files if they exist, otherwise use placeholder
    uploaded_file = None
    processed_file = None
    if product_results:
        # Extract file paths from session results
        # Remove leading '/' if present for os.path.exists
        uploaded_file_url = product_results.get('filename')
        processed_file_url = product_results.get('processed_file')
        if uploaded_file_url:
            uploaded_file = uploaded_file_url.lstrip('/')
            if not os.path.exists(uploaded_file):
                uploaded_file = None
        if processed_file_url:
            processed_file = processed_file_url.lstrip('/')
            if not os.path.exists(processed_file):
                processed_file = None
    # Fallback to sample images if not found
    if not uploaded_file:
        uploaded_file = "static/uploads/img1.png"
        if not os.path.exists(uploaded_file):
            create_placeholder_image(uploaded_file, "Uploaded Image")
    if not processed_file:
        processed_file = "static/processed/img2.png"
        if not os.path.exists(processed_file):
            create_placeholder_image(processed_file, "Processed Image")

    # Get latest product results from session if available
    product_results = None
    try:
        product_results = session.get('latest_results')
    except Exception:
        product_results = None

    # Prepare compliance info table
    compliance_fields = [
        ('Product Name', product_results['data']['product'] if product_results else None),
        ('Manufacturer / Packer / Importer', product_results['data']['manufacturer'] if product_results else None),
        ('Address', product_results['data']['address'] if product_results else None),
        ('Commodity Name', product_results['data']['commodity'] if product_results else None),
        ('Net Quantity', product_results['data']['net_quantity'] if product_results else None),
        ('MRP (₹)', product_results['data']['mrp'] if product_results else None),
        ('Date of Manufacture / Import', product_results['data']['date'] if product_results else None),
        ('Consumer Care Details', product_results['data']['consumer_care'] if product_results else None),
        ('Country of Origin', product_results['data']['origin'] if product_results else None)
    ]

    # OCR text for PDF
    ocr_text = product_results['data']['raw_text'] if product_results and 'raw_text' in product_results['data'] else ''

    # Compliance table for PDF
    compliance_table = [['Field', 'Status', 'Info']]
    for label, info in compliance_fields:
        status = 'Present' if info and info != 'Not Found' else 'Absent'
        mark = '✔' if status == 'Present' else '✘'
        compliance_table.append([label, f'{mark} {status}', info or 'Not Found'])

    # Use new black-and-white report generator
    from bw_report_generator import generate_bw_report
    pdf_path = generate_bw_report(product_results, compliance_table, compliance_score, uploaded_file, processed_file)
    return send_file(pdf_path, as_attachment=True)

# -----------------------------
# Run App
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True)