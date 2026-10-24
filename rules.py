import re
from ingredients import find_ingredient_text


def find(pattern, text, flags=re.I):
    return re.search(pattern, text, flags)


def clean(s):
    return " ".join(str(s or "").split())


# ---------- small building blocks (regular expressions) ----------
DATE_FULL = r"\b(0?[1-9]|[12]\d|3[01])\s*[/\-]\s*(0?[1-9]|1[0-2])\s*[/\-]\s*(?:20)?\d{2}\b"
DATE_MY = r"\b(0?[1-9]|1[0-2])\s*[/\-]\s*(?:20)?\d{2}\b"
DATE_MON = r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s\-/,.]*\d{2,4}\b"
ANY_DATE = "(?:" + DATE_FULL + ")|(?:" + DATE_MY + ")|(?:" + DATE_MON + ")"

UNITS = r"(?:kg|mg|g|gm|gms|ml|l|ltr|litres?|metres?|meters?|cm|m|units?|nos?|pcs|pieces|tablets?|capsules?|strips?|sachets?|packs?|pairs?|sheets?)"
QTY = r"\d+(?:\.\d+)?\s*" + UNITS + r"\b"
REL = r"\d+\s*(?:months?|days?|years?)(?:\s*(?:from|of)\s*(?:the\s*)?(?:date\s*of\s*)?(?:manufactur\w*|packing|mfg|pkd))?"

COMPANY = r"((?:[A-Za-z][A-Za-z&\-]*\s+){1,5}(?:private\s+limited|pvt\.?\s*ltd\.?|limited|ltd\.?|llp|industries|enterprises))"
EXPIRY_WORDS = r"(?:best\s*before|use\s*before|use\s*by|expiry(?:\s*date)?|expires|\bexp\b\.?)"
MFG_WORDS = r"(?:mfg|mfd|manufactur\w*|pkd|packed(?:\s*on)?|packing)"
SYMBOL = r"(₹|\brs\b\.?|\binr\b)\s*([\d,]+(?:\.\d+)?)"


# ---------- STEP 1: read the label text and pick out each detail ----------
def extract_fields(text, product=""):
    t = text or ""
    f = {}

    # commodity name
    m = find(r"(?:product name|name of (?:the )?commodity|common name|generic name)\s*[:\-]?\s*"
             r"([A-Za-z0-9]+(?: [A-Za-z0-9]+){0,3})", t)
    f["name"] = clean(m.group(1)) if m else clean(product)

    # manufacturer / packer / importer (company name + place and PIN code)
    comp = find(COMPANY, t)
    pin = find(r"(?:([A-Za-z]{3,})\s*[-,]?\s*)?\b(\d{6})\b", t)
    if comp:
        company = clean(comp.group(1))
        company = re.sub(r"^(?:(?:\w*ctured|mfd|mfg|packed|marketed|imported|by|at|for|and|the)\b\s*)+", "", company, flags=re.I)
        if pin and pin.group(1):
            f["manufacturer"] = company + ", " + pin.group(1) + "-" + pin.group(2)
        elif pin:
            f["manufacturer"] = company + ", PIN " + pin.group(2)
        else:
            f["manufacturer"] = company
    else:
        m = find(r"(?:\w*ctured|mfd\.?|packed|marketed|imported)\s*(?:by|at)\s*[:\-]?\s*([^\n.]{3,80})", t)
        f["manufacturer"] = clean(m.group(1)) if m else ""

    # net quantity
    m = find(r"net\s*(?:wt|weight|qty|quantity|content|contents)\.?\s*[:\-]?\s*(" + QTY + ")", t) \
        or find("(" + QTY + ")", t)
    f["quantity"] = clean(m.group(1)) if m else ""

    # MRP and whether it says "inclusive of all taxes"
    f["mrp"] = ""
    key = find(r"\bm\.?r\.?p\b|maximum\s*retail\s*price", t)
    if key:
        window = t[key.end(): key.end() + 150]
        cut = find(r"unit\s*sale", window)          # do not read the unit price by mistake
        if cut:
            window = window[:cut.start()]
        s = find(SYMBOL, window)
        if s:
            f["mrp"] = ("₹" if s.group(1) == "₹" else "Rs. ") + s.group(2)
        else:
            n = find(r"\d[\d,]*(?:\.\d+)?", window)
            if n:
                f["mrp"] = n.group(0)               # no currency sign was read
    if not f["mrp"]:
        s = find(SYMBOL, t)
        if s:
            f["mrp"] = ("₹" if s.group(1) == "₹" else "Rs. ") + s.group(2)
    excl = find(r"(?:excl\w*\.?\s*(?:of\s*)?|plus\s*|\+\s*)(?:all\s*)?tax", t)
    incl = find(r"incl\w*\.?\s*(?:of\s*)?(?:all\s*)?tax", t)
    f["mrp_taxes"] = "no" if excl else ("yes" if incl else "unknown")

    # month and year of manufacture / packing (not the expiry date)
    f["date"] = ""
    good = []
    for d in re.finditer(ANY_DATE, t, re.I):
        before = t[max(0, d.start() - 25): d.start()]
        if find(EXPIRY_WORDS, before):
            continue
        good.append(d)
    pick = None
    for d in good:
        if find(MFG_WORDS, t[max(0, d.start() - 40): d.start()]):
            pick = d
            break
    if not pick and good:
        pick = good[0]
    if pick:
        f["date"] = clean(pick.group(0))

    # consumer care (phone and/or email)
    email = find(r"[\w.\-]+@[\w.\-]+\.\w+", t)
    phone = find(r"\b1800[\s\-]?\d{3}[\s\-]?\d{3,4}\b|\b\d{10}\b", t)
    f["care"] = ", ".join(clean(x.group(0)) for x in (phone, email) if x)

    # country of origin
    m = find(r"(?:made\s*in|country of origin|product of|imported from)\s*[:\-]?\s*([A-Za-z]+)", t)
    f["country"] = m.group(1).title() if m else ""

    # expiry / best before (food, medicine, cosmetics)
    m = find(EXPIRY_WORDS + r"\s*[:\-]?\s*(?P<val>" + REL + "|" + ANY_DATE + ")", t)
    f["expiry"] = clean(m.group("val")) if m else ""

    f["ingredients"] = find_ingredient_text(t)

    f["imported"] = bool(find(r"imported\s*(?:by|from)|\bimporter\b", t))
    return f


# ---------- STEP 2: check each confirmed detail ----------
def v_name(f):
    v = clean(f.get("name"))
    if not v:
        return "Missing", "No commodity name entered - type it from the pack"
    return "Detected", v


def v_manufacturer(f):
    v = clean(f.get("manufacturer"))
    if not v:
        return "Missing", "No manufacturer / packer / importer entered"
    if find(r"\b\d{6}\b", v) and len(v.split()) >= 3:
        return "Detected", v
    return "Review Required", v + "  (add the full address with the 6-digit PIN code)"


def v_quantity(f):
    v = clean(f.get("quantity"))
    if not v:
        return "Missing", "No net quantity entered"
    if find(QTY, v):
        return "Detected", v
    return "Review Required", v + "  (write a number with a unit, like 50 g, 1 L or 12 Units)"


def v_mrp(f):
    v = clean(f.get("mrp"))
    taxes = f.get("mrp_taxes") or "unknown"
    if not v:
        return "Missing", "No MRP entered"
    if taxes == "no":
        return "Potential Non-Compliance", v + "  (MRP must be inclusive of all taxes)"
    if not find(r"\d", v):
        return "Review Required", v + "  (no amount found)"
    if not find(r"(₹|\brs\b\.?|\binr\b)\s*[\d,]+", v):
        return "Review Required", v + "  (add the Rs/₹ sign - OCR often misreads it)"
    if taxes != "yes":
        return "Review Required", v + "  (confirm that 'inclusive of all taxes' is printed on the pack)"
    return "Detected", v + " (inclusive of all taxes)"


def v_date(f):
    v = clean(f.get("date"))
    if not v:
        return "Missing", "No month and year of manufacture entered"
    if find(ANY_DATE, v):
        return "Detected", v
    return "Review Required", v + "  (write it like 10/2025 or Oct 2025)"


def v_care(f):
    v = clean(f.get("care"))
    if not v:
        return "Missing", "No consumer care details entered"
    if find(r"[\w.\-]+@[\w.\-]+\.\w+|\b\d[\d\s\-]{8,}\d\b", v):
        return "Detected", v
    return "Review Required", v + "  (add a phone number or email)"


def v_country(f):
    v = clean(f.get("country"))
    if v:
        return "Detected", v
    if f.get("imported"):
        return "Missing", "Imported product but no country of origin entered"
    return "Review Required", "Not entered - mandatory for imported goods; confirm if this product is imported"


def v_expiry(f):
    v = clean(f.get("expiry"))
    if not v:
        return "Missing", "No expiry or best-before information entered"
    if find(ANY_DATE, v) or find(REL, v):
        return "Detected", v
    return "Review Required", v + "  (write a date like 12/2027 or '6 months from manufacture')"


RULES = [
    ("Commodity name", "Common or generic name of the commodity", v_name),
    ("Manufacturer / Packer / Importer", "Name and address of manufacturer, packer or importer", v_manufacturer),
    ("Net quantity", "Net quantity in standard units", v_quantity),
    ("MRP", "Retail sale price in rupees, inclusive of all taxes", v_mrp),
    ("Manufacture / Packing date", "Month and year of manufacture, packing or import", v_date),
    ("Consumer care", "Consumer care details (phone, email or address)", v_care),
    ("Country of origin", "Country of origin (mandatory for imported goods)", v_country),
]

EXPIRY = ("Expiry / Best before", "Expiry or best-before date (food, medicine, cosmetics)", v_expiry)


def is_perishable(raw_text, category, f):
    if category == "perishable":
        return True, "product marked as perishable"
    if category == "general":
        return False, "product marked as non-perishable"
    if clean(f.get("expiry")):
        return True, "an expiry / best-before value was found"
    m = find(r"(best\s*before|use\s*before|use\s*by|expiry|expires|expiration|\bexp\b|fssai|ingredients|nutrition|mfg\.?\s*lic)", raw_text or "")
    if m:
        return True, "auto-detected from '" + m.group(0) + "'"
    return False, "no expiry or food/medicine markers found"


def check_fields(f, category="auto", raw_text=""):
    perishable, why = is_perishable(raw_text, category, f)
    rules = list(RULES)
    if perishable:
        rules.append(EXPIRY)
    rows = []
    detected = 0
    for name, requirement, fn in rules:
        status, evidence = fn(f)
        rows.append({"rule": name, "requirement": requirement,
                     "status": status, "evidence": evidence})
        if status == "Detected":
            detected += 1
    if not perishable:
        rows.append({"rule": EXPIRY[0], "requirement": EXPIRY[1],
                     "status": "Not Applicable",
                     "evidence": "Not checked - " + why})
    statuses = [r["status"] for r in rows]
    if detected == len(rules):
        overall = "Compliant"
    elif "Missing" in statuses or "Potential Non-Compliance" in statuses:
        overall = "Non-Compliant"
    else:
        overall = "Review Required"
    score = round(detected / len(rules) * 100)
    return {"rows": rows, "score": score, "status": overall, "expiry_note": why}


def check_label(text, category="auto", product=""):
    """Read the text, pick out the details, then check them."""
    f = extract_fields(text, product)
    result = check_fields(f, category, text)
    result["fields"] = f
    return result