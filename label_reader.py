"""label_reader.py - tile-by-tile label OCR for the scanner. Needs: flask opencv-python-headless numpy pytesseract + Tesseract installed."""
import os
import re
import shutil
import difflib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import cv2
import numpy as np
import pytesseract
from pytesseract import Output
from flask import Blueprint, request, jsonify
if not shutil.which("tesseract"):
    for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if os.path.exists(p):
            pytesseract.pytesseract.tesseract_cmd = p
            break
bp = Blueprint("label_reader", __name__)
RUPEE = "\u20b9"
STOP = {"the", "after", "each", "use", "your", "only", "for", "and", "with", "keep", "make", "all", "are", "not", "per"}
GENERIC = (r"pens?|pencils?|crayons?|markers?|erasers?|sharpeners?|notebooks?|chips|biscuits?|noodles|snacks?|soap|"
           r"shampoo|oil|tea|coffee|juice|spread|powder|cream|lotion|rice|flour|sugar|salt")
def load_image(data: bytes):
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not read this file as an image")
    h, w = img.shape[:2]
    if w > 2600:
        img = cv2.resize(img, None, fx=2600 / w, fy=2600 / w, interpolation=cv2.INTER_AREA)
    return img
def _tiles(h, w):
    cols = 3 if w > 1.4 * h else 2
    rows = max(2, round(h / (0.28 * w))) if cols == 2 else 2
    th, tw = h / rows, w / cols
    oy, ox = int(th * 0.10), int(tw * 0.10)
    return [(max(0, int(r * th) - oy), min(h, int((r + 1) * th) + oy),
             max(0, int(c * tw) - ox), min(w, int((c + 1) * tw) + ox), c)
            for r in range(rows) for c in range(cols)]
def _ocr_tile(args):
    gray, (y1, y2, x1, x2, col) = args
    t = gray[y1:y2, x1:x2]
    f = min(3.0, max(1.0, 2000.0 / t.shape[1]))
    t = cv2.resize(t, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    cl = cv2.createCLAHE(2.0, (8, 8)).apply(t)
    out = []
    for variant in (cl, 255 - cl):
        for psm in (6, 11):
            d = pytesseract.image_to_data(variant, lang="eng", output_type=Output.DICT, config="--oem 3 --psm %d" % psm)
            groups = {}
            for i, txt in enumerate(d["text"]):
                txt = txt.strip()
                try:
                    conf = float(d["conf"][i])
                except ValueError:
                    continue
                if txt and conf >= 30:
                    groups.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(
                        (txt, x1 + d["left"][i] / f, y1 + d["top"][i] / f, d["width"][i] / f, d["height"][i] / f, conf))
            for ws in groups.values():
                x = min(w[1] for w in ws); y = min(w[2] for w in ws)
                x2 = max(w[1] + w[3] for w in ws); y2_ = max(w[2] + w[4] for w in ws)
                out.append({"text": " ".join(w[0] for w in ws), "x": x, "y": y, "x2": x2, "y2": y2_,
                            "cy": (y + y2_) / 2, "h": y2_ - y, "conf": sum(w[5] for w in ws) / len(ws), "col": col,
                            "words": ws})
    return out
def read_lines(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    tiles = _tiles(h, w)
    with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 2)) as ex:
        results = list(ex.map(_ocr_tile, [(gray, t) for t in tiles]))
    best = {}
    for lines in results:
        for ln in lines:
            key = re.sub(r"[^a-z0-9]", "", ln["text"].lower())
            if len(key) < 4 or ln["conf"] < 40:
                continue
            if key not in best or ln["conf"] > best[key]["conf"]:
                best[key] = ln
    return gray, sorted(best.values(), key=lambda l: (l["col"], l["cy"]))
def _clean(v):
    v = re.split(r"[|{}\[\]_~=\u00ae\u00a9]", v)[0]
    v = re.sub(r"[^\w)\]]+$", "", v.strip())
    return re.sub(r"\s+", " ", v).strip()
def _right_neighbours(line, lines):
    return [o for o in lines if o is not line and o["x"] >= line["x2"] - 10 and abs(o["cy"] - line["cy"]) < 0.8 * max(line["h"], o["h"])]
def _title(s):
    return " ".join(wd.capitalize() if wd.isupper() or wd.islower() else wd for wd in s.split())
_DATE_RE = re.compile(r"^(0?[1-9]|1[0-2])[/\-.](20\d{2}|\d{2})$")
def _read_date_cell(gray, label):
    h, w = gray.shape
    lw = [wd for wd in label["words"] if re.match(r"(manufactur|mfg|packing|import)", wd[0], re.I)]
    if lw:
        x_end, ly, lh = lw[-1][1] + lw[-1][3], lw[-1][2], lw[-1][4]
    else:
        x_end, ly, lh = label["x2"], label["y"], label["h"]
    x1 = int(x_end + 8)
    x2 = min(w, x1 + int(0.22 * w))
    votes = Counter()
    for dy in (0, -3, 3):
        y1, y2 = max(0, int(ly - 0.6 * lh) + dy), min(h, int(ly + lh + 0.6 * lh) + dy)
        crop = gray[y1:y2, x1:x2]
        if crop.shape[0] < 12 or crop.shape[1] < 40:
            continue
        colmean = crop.mean(axis=0)
        good = np.where(colmean > 0.6 * colmean.max())[0]
        if len(good) > 30:
            crop = crop[:, good.min() + 6: max(good.min() + 7, good.max() - 6)]
        for scale, mode, sig, thick, psm, wl in ((3, "otsu", 0, 0, 7, True), (5, "otsu", 0, 0, 7, True),
                                                 (3, "otsu", 0, 0, 7, False), (4, "otsu", 0, 0, 7, True),
                                                 (5, "otsu", 0, 0, 7, False), (6, "otsu", 0, 0, 7, True),
                                                 (2, "flat", 2.0, 2, 7, True), (2, "flat", 1.0, 0, 13, True)):
            big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            if mode == "flat":
                big = cv2.divide(big, cv2.GaussianBlur(big, (0, 0), 20 * scale / 3), scale=255)
            if sig:
                big = cv2.GaussianBlur(big, (0, 0), sig * scale / 3)
            bw = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            if thick:
                bw = cv2.erode(bw, np.ones((thick * scale // 2 + 1,) * 2, np.uint8))
            bw = cv2.copyMakeBorder(bw, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)
            cfg = "--oem 3 --psm %d" % psm + (" -c tessedit_char_whitelist=0123456789/-." if wl else "")
            s = pytesseract.image_to_string(bw, config=cfg).strip().replace("\n", "").replace(" ", "").strip(".;:,()")
            m = _DATE_RE.match(s)
            if m:
                yr = m.group(2) if len(m.group(2)) == 4 else "20" + m.group(2)
                votes["%02d/%s" % (int(m.group(1)), yr)] += 1
    if not votes:
        return None
    value, n = votes.most_common(1)[0]
    return value, n, sum(votes.values()), dict(votes)
def extract_fields(img, product_hint=""):
    gray, lines = read_lines(img)
    text_all = "\n".join(l["text"] for l in lines)
    f, notes, used = {}, [], set()
    unit_re = r"(units?|nos|pcs|pieces?|kg|gms?|g|mg|ml|l|ltr|litres?)"
    for l in lines:
        if re.search(r"net\s*(quantity|qty|wt|weight|content)", l["text"], re.I):
            cand = [l["text"]] + [o["text"] for o in _right_neighbours(l, lines)]
            for c in cand:
                m = re.search(r"(\d+(?:\.\d+)?)\s*%s\b" % unit_re, c, re.I)
                if m:
                    f["net_quantity"] = "%s %s" % (m.group(1), m.group(2).capitalize() if len(m.group(2)) > 2 else m.group(2))
                    used.add(id(l))
                    break
        if "net_quantity" in f:
            break
    if "net_quantity" not in f:
        labels = [l for l in lines if re.search(r"net\s*(quantity|qty|wt|weight|content)", l["text"], re.I)]
        for l in labels:
            near = [o for o in lines if o is not l and abs(o["cy"] - l["cy"]) < 1.5 * max(l["h"], o["h"])]
            for o in sorted(near, key=lambda o: abs(o["x"] - l["x2"])):
                m = re.match(r"\W*(\d+(?:\.\d+)?)\s*%s\b" % unit_re, o["text"].strip(), re.I)
                if m:
                    f["net_quantity"] = "%s %s" % (m.group(1), m.group(2).capitalize() if len(m.group(2)) > 2 else m.group(2))
                    break
            if "net_quantity" in f:
                break
    qty = None
    if "net_quantity" in f and re.search(r"unit|nos|pcs|piece", f["net_quantity"], re.I):
        qty = float(f["net_quantity"].split()[0])
    unit_price = None
    m = re.search(r"unit\s*sale\s*price\W{0,4}(\d+[.,]\d{2})", text_all, re.I)
    if m:
        unit_price = float(m.group(1).replace(",", "."))
    cands = []
    for l in lines:
        if re.search(r"retail\s*price|\bmrp\b|m\.r\.p", l["text"], re.I):
            for src in [l["text"]] + [o["text"] for o in _right_neighbours(l, lines)]:
                for pre, num in re.findall(r"([^\w\s]?)\s*(\d{1,4}[.,]\d{2})\b", src):
                    cands.append((pre, num.replace(",", ".")))
    for l in lines:
        if re.fullmatch(r"[^\w\s]?\s*\d{1,4}[.,]\d{2}\W*", l["text"].strip()):
            for pre, num in re.findall(r"([^\w\s]?)\s*(\d{1,4}[.,]\d{2})", l["text"]):
                if any(re.search(r"retail\s*price|\bmrp\b", o["text"], re.I) for o in lines
                       if abs(o["cy"] - l["cy"]) < 1.5 * o["h"] and o["x2"] <= l["x"] + 10):
                    cands.append((pre, num.replace(",", ".")))
                    used.add(id(l))
    if cands:
        vals = []
        for pre, num in cands:
            vals.append((float(num), pre, num, "as read"))
            if len(num.split(".")[0]) >= 3 and num[0] in "2%":
                vals.append((float(num[1:]), "", num[1:], "sign"))
        pick = None
        if unit_price and qty:
            for v, pre, num, why in vals:
                if abs(v - unit_price * qty) < 0.51:
                    pick = (num, "amount confirmed with unit price %.2f x %d" % (unit_price, qty))
                    break
        if not pick:
            for v, pre, num, why in vals:
                if pre and not pre.isalnum() and why == "as read":
                    pick = (num, None)
                    break
        if not pick:
            pick = (vals[0][2], None)
        amount = "%.2f" % float(pick[0])
        tax = " (inclusive of all taxes)" if re.search(r"inclusive\s*of\s*all\s*tax", text_all, re.I) else ""
        f["mrp"] = "Maximum Retail Price%s: %s%s" % (tax, RUPEE, amount)
        if pick[1]:
            notes.append("MRP: the Rs sign was misread by OCR, " + pick[1])
    for l in lines:
        m = re.search(r"(?:month\s*(?:&|and)?\s*year\s*of\s*(?:manufacture|mfg|packing|import)|mf[gd]\.?(?:\s*date)?|packed\s*on|date\s*of\s*(?:manufacture|packing))"
                      r"\W{0,8}(\d{1,2}\s?[/\-.]\s?\d{2,4})", l["text"], re.I)
        if m:
            f["mfg_date"] = "Month & Year of Manufacture: " + re.sub(r"\s", "", m.group(1))
            used.add(id(l))
            break
    if "mfg_date" not in f:
        label = next((l for l in lines if re.search(r"month", l["text"], re.I) and re.search(r"manufactur|packing|import", l["text"], re.I)), None)
        if label:
            used.add(id(label))
            got = _read_date_cell(gray, label)
            if got:
                if got[1] >= 5 and got[1] >= 0.8 * got[2]:
                    f["mfg_date"] = "Month & Year of Manufacture: " + got[0]
                    notes.append("Manufacture date %s was read from the printed box - please confirm it on the pack." % got[0])
                else:
                    notes.append("Manufacture date: the printed box is hard to read (best guess %s, not sure). Please type the month/year exactly as printed on the pack." % got[0])
    for l in lines:
        m = re.search(r"product\s*name\W{0,4}(.*)", l["text"], re.I)
        if m:
            val = _clean(m.group(1))
            if not val:
                nb = _right_neighbours(l, lines)
                val = _clean(nb[0]["text"]) if nb else ""
            if val:
                hint = product_hint.lower().split()
                toks = val.split()
                best, score = None, 0
                for i in range(max(1, len(hint) - len(toks) + 1)):
                    seg = " ".join(hint[i:i + len(toks)])
                    r = difflib.SequenceMatcher(None, seg, val.lower()).ratio()
                    if r > score:
                        best, score = seg, r
                full = " ".join(hint)
                if len(val) >= 4 and len(full) > len(val) and full.startswith(val.lower()):
                    val = _title(full)
                elif best and score >= 0.8:
                    val = _title(best)
                f["product_name"] = val
                used.add(id(l))
                break
    best_co = None
    for l in lines:
        m = re.search(r"([A-Za-z][A-Za-z&.\-]*(?:\s+[A-Za-z][A-Za-z&.\-]*){0,4}?\s+(?:private\s+limited|pvt\.?\s*ltd\.?|limited|ltd\.?|llp))", l["text"], re.I)
        if m and re.search(r"\b(?:by|b[;:,])[:;,\-\s]*$", l["text"][:m.start()]) and (best_co is None or l["conf"] > best_co[1]["conf"]):
            best_co = (" ".join(m.group(1).split()), l)
    if best_co:
        f["manufacturer"] = best_co[0]
        notes.append("Manufacturer '%s' was read after a 'by' word - please confirm the 'Manufactured by' wording and address on the pack." % best_co[0])
    out = []
    if "product_name" in f: out.append("Product Name: " + f["product_name"])
    if "manufacturer" in f: out.append("Manufactured by: " + f["manufacturer"])
    if "mrp" in f: out.append(f["mrp"])
    if "mfg_date" in f: out.append(f["mfg_date"])
    if "net_quantity" in f: out.append("Net Quantity: " + f["net_quantity"])
    raw = [l["text"] for l in lines if id(l) not in used]
    return {"fields": f, "notes": notes, "clean": out, "raw": raw}
def read_labels(images, product_hint=""):
    merged_clean, notes, raw, seen_field = [], [], [], set()
    for img in images:
        r = extract_fields(img, product_hint)
        for line in r["clean"]:
            key = line.split(":")[0].lower()
            if key not in seen_field:
                seen_field.add(key)
                merged_clean.append(line)
        notes += r["notes"]
        for ln in r["raw"]:
            if ln not in raw:
                raw.append(ln)
    text = "\n".join(merged_clean + ([""] if merged_clean else []) + raw)
    return {"text": text, "notes": notes, "raw_lines": len(raw)}
@bp.route("/api/ocr", methods=["POST"])
def api_ocr():
    files = request.files.getlist("images")
    if not files:
        return jsonify({"error": "No image uploaded"}), 400
    images = []
    for f in files[:6]:
        try:
            images.append(load_image(f.read()))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    try:
        return jsonify(read_labels(images, request.form.get("product", "")))
    except pytesseract.TesseractNotFoundError:
        return jsonify({"error": "Tesseract is not installed on this computer"}), 500
    except Exception as e:
        return jsonify({"error": "OCR failed: %s" % e}), 500