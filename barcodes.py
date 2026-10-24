import json
import re
import urllib.request
import urllib.error

# GS1 prefix -> country where the barcode number was REGISTERED.
# (This is not always the country where the product was made.)
PREFIXES = {
    "890": "India", "880": "South Korea", "885": "Thailand", "888": "Singapore",
    "893": "Vietnam", "899": "Indonesia", "955": "Malaysia", "489": "Hong Kong",
    "471": "Taiwan", "628": "Saudi Arabia", "729": "Israel", "750": "Mexico",
    "789": "Brazil", "790": "Brazil", "539": "Ireland", "560": "Portugal",
}
RANGES = [(300, 379, "France"), (450, 459, "Japan"), (490, 499, "Japan"),
          (690, 699, "China"), (930, 939, "Australia"), (940, 949, "New Zealand")]
# two-digit prefixes
PREFIXES_2 = {
    "40": "Germany", "41": "Germany", "42": "Germany", "43": "Germany", "44": "Germany",
    "46": "Russia", "50": "United Kingdom", "54": "Belgium", "57": "Denmark", "64": "Finland",
    "73": "Sweden", "70": "Norway", "76": "Switzerland", "80": "Italy", "81": "Italy",
    "82": "Italy", "83": "Italy", "84": "Spain", "87": "Netherlands", "90": "Austria",
    "91": "Austria",
}
for n in range(0, 14):
    PREFIXES_2["%02d" % n] = "United States / Canada"


def clean_code(code):
    return re.sub(r"\D", "", str(code or ""))


def is_valid(code):
    """Check the digits and the last 'check digit' of EAN-13, UPC-A (12) or EAN-8."""
    c = clean_code(code)
    if len(c) not in (8, 12, 13):
        return False
    digits = [int(x) for x in c]
    body, check = digits[:-1], digits[-1]
    total = 0
    for i, d in enumerate(reversed(body)):
        total += d * (3 if i % 2 == 0 else 1)
    return (10 - total % 10) % 10 == check


def country_of_prefix(code):
    c = clean_code(code)
    if len(c) == 12:                 # UPC-A is an EAN-13 with a leading 0
        c = "0" + c
    if len(c) == 8:
        return ""                    # EAN-8 has no clear country prefix
    if c[:3] in PREFIXES:
        return PREFIXES[c[:3]]
    for low, high, name in RANGES:
        if low <= int(c[:3]) <= high:
            return name
    return PREFIXES_2.get(c[:2], "")


def fetch_open_food_facts(code):
    """Ask the free Open Food Facts database about this barcode. Returns a dict or None."""
    url = ("https://world.openfoodfacts.org/api/v2/product/%s.json"
           "?fields=product_name,brands,quantity,ingredients_text,origins,manufacturing_places" % code)
    req = urllib.request.Request(url, headers={"User-Agent": "LegalCheck/1.0 (student project)"})
    with urllib.request.urlopen(req, timeout=6) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    if data.get("status") != 1:
        return None
    p = data.get("product") or {}
    return {
        "name": " ".join(str(p.get("product_name") or "").split()),
        "brand": " ".join(str(p.get("brands") or "").split()),
        "quantity": " ".join(str(p.get("quantity") or "").split()),
        "ingredients": " ".join(str(p.get("ingredients_text") or "").split()),
    }


def lookup(code):
    """Full barcode answer for the website."""
    c = clean_code(code)
    out = {"code": c, "valid": is_valid(c), "country": "", "found": False, "product": None, "message": ""}
    if not c:
        out["message"] = "Please type or scan a barcode number."
        return out
    if not out["valid"]:
        out["message"] = "This number is not a valid barcode (EAN-13, UPC-A or EAN-8). Check the digits."
        return out
    out["country"] = country_of_prefix(c)
    try:
        prod = fetch_open_food_facts(c)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        out["message"] = "Barcode is valid, but the product database could not be reached (check your internet)."
        return out
    if prod:
        out["found"] = True
        out["product"] = prod
        out["message"] = "Product found in Open Food Facts."
    else:
        out["message"] = "Barcode is valid, but this product is not in the free database. Please use the label photo."
    return out
