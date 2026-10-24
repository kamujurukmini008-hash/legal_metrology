import os
import json
import sqlite3
from flask import Flask, render_template, request, jsonify, abort
import barcodes
from ingredients import analyze
from rules import check_label, check_fields, extract_fields, is_perishable

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "scans_v2.db")

FIELD_NAMES = ("name", "manufacturer", "quantity", "mrp", "mrp_taxes",
               "date", "care", "country", "expiry", "ingredients")

app = Flask(__name__)

# Server-side label reader (needs opencv + pytesseract + Tesseract installed).
# If it is not installed, the scanner page falls back to reading in the browser.
try:
    from label_reader import bp as label_reader_bp
    app.register_blueprint(label_reader_bp)
except Exception as err:
    print("Server OCR not available (browser OCR will be used):", err)


def get_db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = get_db()
    con.execute("""CREATE TABLE IF NOT EXISTS scans(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product TEXT, text TEXT, score INTEGER,
        status TEXT, result TEXT,
        created TEXT DEFAULT (datetime('now','localtime')))""")
    con.commit()
    con.close()


init_db()


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/scanner")
def scanner():
    return render_template("scanner.html")


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@app.route("/history")
def history():
    con = get_db()
    rows = con.execute("SELECT * FROM scans ORDER BY id DESC").fetchall()
    con.close()
    return render_template("history.html", rows=rows)


@app.route("/report/<int:scan_id>")
def report(scan_id):
    con = get_db()
    row = con.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
    con.close()
    if row is None:
        abort(404)
    return render_template("report.html", row=row, result=json.loads(row["result"]))


@app.route("/api/extract", methods=["POST"])
def api_extract():
    """Read the label text and return each detail, ready to be corrected."""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "No text to read"}), 400
    fields = extract_fields(text)
    perishable, why = is_perishable(text, "auto", fields)
    return jsonify({"fields": fields, "perishable": perishable})


@app.route("/api/barcode", methods=["POST"])
def api_barcode():
    """Check a barcode number and look the product up."""
    data = request.get_json(silent=True) or {}
    return jsonify(barcodes.lookup(data.get("code")))


@app.route("/api/check", methods=["POST"])
def api_check():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    category = data.get("category", "auto")
    fields = data.get("fields")

    if isinstance(fields, dict):
        # the user has confirmed (or corrected) every detail
        f = {k: str(fields.get(k) or "").strip() for k in FIELD_NAMES}
        f["imported"] = bool(fields.get("imported"))
        result = check_fields(f, category, text)
        result["fields"] = f
        result["ingredients"] = analyze(f["ingredients"], text, f["name"])
        product = f["name"] or "Unnamed product"
    elif text:
        result = check_label(text, category, (data.get("product") or "").strip())
        result["ingredients"] = analyze(result["fields"].get("ingredients"), text, result["fields"]["name"])
        product = result["fields"]["name"] or (data.get("product") or "").strip() or "Unnamed product"
    else:
        return jsonify({"error": "No text to check"}), 400

    bc = data.get("barcode")
    if isinstance(bc, dict) and barcodes.clean_code(bc.get("code")):
        result["barcode"] = {"code": barcodes.clean_code(bc.get("code")),
                             "country": str(bc.get("country") or "")[:60],
                             "note": str(bc.get("note") or "")[:300]}

    con = get_db()
    cur = con.execute(
        "INSERT INTO scans(product, text, score, status, result) VALUES (?,?,?,?,?)",
        (product, text, result["score"], result["status"], json.dumps(result)))
    con.commit()
    result["id"] = cur.lastrowid
    con.close()
    return jsonify(result)


@app.route("/api/stats")
def api_stats():
    con = get_db()
    rows = con.execute("SELECT status, result FROM scans").fetchall()
    con.close()
    counts = {"Compliant": 0, "Review Required": 0, "Non-Compliant": 0}
    failures = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        for item in json.loads(r["result"])["rows"]:
            if item["status"] in ("Missing", "Potential Non-Compliance", "Review Required"):
                failures[item["rule"]] = failures.get(item["rule"], 0) + 1
    return jsonify({"total": len(rows),
                    "compliant": counts["Compliant"],
                    "review": counts["Review Required"],
                    "non_compliant": counts["Non-Compliant"],
                    "failures": failures})


@app.route("/api/delete/<int:scan_id>", methods=["POST"])
def api_delete(scan_id):
    con = get_db()
    con.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
    con.commit()
    con.close()
    return jsonify({"ok": True})


@app.route("/api/clear", methods=["POST"])
def api_clear():
    con = get_db()
    con.execute("DELETE FROM scans")
    con.commit()
    con.close()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True)
    