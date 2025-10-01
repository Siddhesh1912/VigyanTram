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
import re


"""Flask app for product monitoring and compliance checks."""

# -----------------------------
# Flask App Setup
# -----------------------------
app = Flask(__name__)
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
    url = request.form.get("url")
    image = request.files.get("image")
    snapshot_url = request.form.get("snapshot_url")

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

        # Compliance decision based on presence of mandatory fields
        # Evaluate rule engine
        compliant, issues = evaluate_legal_metrology_rules(results["data"])
        results["compliant"] = compliant
        if not compliant:
            results["data"]["issue"] = "; ".join(issues)

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
    elif image and getattr(image, 'filename', ''):
        filename = secure_filename(image.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        image.save(filepath)
        results["filename"] = to_url_path(filepath)

        # Try to open the image robustly
        try:
            pil_img = open_image_or_error(filepath)
        except UnidentifiedImageError:
            # Gracefully report invalid image and return page
            results["compliant"] = False
            results["data"] = {"issue": "Invalid or corrupted image. Please recapture or upload a valid image."}
            last_snapshot_rel = session.get("last_snapshot_rel")
            last_snapshot_url = url_for('static', filename=last_snapshot_rel) if last_snapshot_rel else None
            return render_template("product_monitoring.html", results=results,
                                   esp32_stream_url=ESP32_STREAM_URL,
                                   esp32_snapshot_url=ESP32_SNAPSHOT_URL,
                                   last_snapshot_url=last_snapshot_url)
        except Exception as _open_e:
            print('Image open error:', _open_e)
            results["compliant"] = False
            results["data"] = {"issue": "Unable to read the uploaded image."}
            last_snapshot_rel = session.get("last_snapshot_rel")
            last_snapshot_url = url_for('static', filename=last_snapshot_rel) if last_snapshot_rel else None
            return render_template("product_monitoring.html", results=results,
                                   esp32_stream_url=ESP32_STREAM_URL,
                                   esp32_snapshot_url=ESP32_SNAPSHOT_URL,
                                   last_snapshot_url=last_snapshot_url)

        # OCR using helper module
        try:
            text, processed_image_for_save = perform_ocr(pil_img)
        except Exception as _ocr_e:
            print('OCR error:', _ocr_e)
            results["compliant"] = False
            results["data"] = {"issue": "OCR failed on the uploaded image."}
            last_snapshot_rel = session.get("last_snapshot_rel")
            last_snapshot_url = url_for('static', filename=last_snapshot_rel) if last_snapshot_rel else None
            return render_template("product_monitoring.html", results=results,
                                   esp32_stream_url=ESP32_STREAM_URL,
                                   esp32_snapshot_url=ESP32_SNAPSHOT_URL,
                                   last_snapshot_url=last_snapshot_url)

        # Extract data from OCR text and validate against CSV data
        # Extract email if present
        try:
            email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}", text)
            care_email = email_match.group(0) if email_match else None
        except Exception:
            care_email = None

        extracted_data = {
            "product": "Uploaded Product",
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

        # Compute 50%+ similarity matches, prioritize guessed category
        try:
            top_matches = find_top_csv_matches(text, cat_products, min_ratio=0.50, limit=5)
            if not top_matches:
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

    # --- CASE 3: ESP32 snapshot URL provided ---
    elif snapshot_url:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(snapshot_url, headers=headers, timeout=10)
            resp.raise_for_status()
            # Determine extension from content-type if possible
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
            results["filename"] = to_url_path(filepath)

            # OCR using helper module
            try:
                pil_img = open_image_or_error(filepath)
                text, processed_image_for_save = perform_ocr(pil_img)
            except Exception as _ocr2_e:
                results["compliant"] = False
                results["data"] = {"issue": f"OCR failed: {_ocr2_e}"}
                text = ""
                processed_image_for_save = pil_img if 'pil_img' in locals() else Image.open(filepath)

            extracted_data = {
                "product": "ESP32 Snapshot",
                "mrp": "₹" + text.split("MRP")[-1].split("\n")[0].strip() if "MRP" in text else "Not Found",
                "net_quantity": "500g" if "500g" in text else "Not Found",
                "manufacturer": "ABC Foods" if "ABC" in text else "Not Found",
                "country": "India" if "India" in text else "Not Found",
                "care": "care@abc.com" if "@" in text else "Not Found"
            }

            # Lightweight name keyword match
            matched_product = None
            for product in all_products:
                if any(keyword in text.lower() for keyword in (product.get('name', '') or '').lower().split()[:3]):
                    matched_product = product
                    break
            if matched_product:
                extracted_data.update({
                    "product": matched_product.get('name', 'ESP32 Snapshot'),
                    "mrp": matched_product.get('price', 'Not Found'),
                    "matched_from_csv": True
                })

            results["data"] = extracted_data
            # Evaluate rule engine for ESP32 URL flow
            compliant, issues = evaluate_legal_metrology_rules(results["data"])
            results["compliant"] = compliant
            if not compliant:
                results["data"]["issue"] = "; ".join(issues)

            processed_path = os.path.join(PROCESSED_FOLDER, "processed_" + filename)
            try:
                processed_image_for_save.save(processed_path)
            except Exception:
                Image.open(filepath).save(processed_path)
            results["processed_file"] = to_url_path(processed_path)

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
            results["data"] = {"error": f"Failed to fetch from ESP32: {e}"}
            results["compliant"] = False

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