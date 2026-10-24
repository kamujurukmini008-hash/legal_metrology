import re
from urllib.parse import quote_plus

# Each item: (words to look for, nice name, level, short reason)
# Levels: "Avoid" (red), "Limit" (orange), "Caution" (cyan-ish note)
# This is general nutrition guidance for awareness - NOT medical advice.
FLAGS = [
    (r"partially\s*hydrogenated|hydrogenated\s*(?:vegetable\s*)?(?:fat|oil)|vanaspati|trans\s*fat",
     "Trans fat / hydrogenated fat", "Avoid",
     "Raises bad cholesterol and increases heart-disease risk."),
    (r"potassium\s*bromate|\bins\s*924\b",
     "Potassium bromate", "Avoid",
     "A flour improver that FSSAI has banned in India."),
    (r"\btbhq\b|tertiary\s*butyl",
     "TBHQ (preservative)", "Caution",
     "Allowed only in small amounts; large amounts are not good for health."),
    (r"tartrazine|sunset\s*yellow|allura\s*red|carmoisine|ponceau|\bins\s*(?:102|110|122|124|129)\b|artificial\s*colou?r|synthetic\s*food\s*colou?r",
     "Artificial colour", "Caution",
     "Some synthetic colours are linked to hyperactivity in some children."),
    (r"monosodium\s*glutamate|\bmsg\b|\bins\s*621\b",
     "Flavour enhancer (MSG)", "Limit",
     "Some people are sensitive to it. Better to avoid in food for babies."),
    (r"disodium\s*(?:inosinate|guanylate)|\bins\s*(?:627|631)\b|flavou?r\s*enhancers?",
     "Flavour enhancer (627 / 631)", "Caution",
     "Added to make food taste stronger; not needed in a healthy diet."),
    (r"sodium\s*benzoate|\bins\s*211\b|potassium\s*sorbate|\bins\s*202\b",
     "Chemical preservative", "Caution",
     "Keeps food from spoiling; better to choose products without it where possible."),
    (r"aspartame|acesulfame|sucralose|saccharin|\bins\s*(?:951|950|955|954)\b",
     "Artificial sweetener", "Caution",
     "Not advised for young children or pregnant women without a doctor's advice."),
    (r"high\s*fructose|glucose\s*syrup|liquid\s*glucose|invert\s*syrup|corn\s*syrup|\bsugar\b",
     "Added sugar", "Limit",
     "Too much added sugar leads to weight gain and tooth and diabetes problems."),
    (r"palm\s*oil|palmolein|palm\s*olein",
     "Palm oil", "Limit",
     "High in saturated fat; best not eaten in large amounts every day."),
    (r"refined\s*wheat\s*flour|\bmaida\b",
     "Refined flour (maida)", "Limit",
     "Low in fibre and nutrients; whole grains are better."),
    (r"\bnitrites?\b|\bnitrates?\b|\bins\s*(?:250|251|249|252)\b",
     "Nitrite / nitrate", "Caution",
     "Used in processed meat; regular large amounts are not recommended."),
    (r"caramel\s*colou?r|\bins\s*150d?\b",
     "Caramel colour", "Caution",
     "Added only for colour; no nutritional value."),
    (r"phosphoric\s*acid|\bins\s*338\b|caffeine",
     "Phosphoric acid / caffeine", "Limit",
     "Common in cola drinks; too much is not good, especially for children."),
]

LEVEL_ORDER = {"Avoid": 0, "Limit": 1, "Caution": 2}

# product type -> words that show it, healthier swap ideas, what to search
SWAPS = [
    ("Chips and namkeen",
     r"chips|crisps|namkeen|bhujia|nachos|puffs|kurkure|wafers|snack",
     [("Roasted makhana (fox nuts)", "roasted makhana"),
      ("Millet / ragi chips (baked, not fried)", "baked millet chips"),
      ("Roasted chana or peanuts", "roasted chana")]),
    ("Biscuits and cookies",
     r"biscuit|cookie|cracker|rusk",
     [("Whole wheat or ragi biscuits (no maida, low sugar)", "ragi biscuits no maida"),
      ("Oats cookies with jaggery", "oats jaggery cookies"),
      ("Roasted seeds and nuts mix", "mixed nuts and seeds")]),
    ("Noodles and pasta",
     r"noodle|pasta|macaroni|vermicelli|maggi",
     [("Millet or whole wheat noodles", "millet noodles"),
      ("Oats or ragi vermicelli", "ragi vermicelli"),
      ("Brown rice pasta", "brown rice pasta")]),
    ("Cold drinks and juices",
     r"cola|soda|soft\s*drink|carbonated|energy\s*drink|fruit\s*drink|juice|squash",
     [("Coconut water", "tender coconut water"),
      ("Fresh lime water / buttermilk (home-made)", "buttermilk"),
      ("100% juice with no added sugar", "100 percent juice no added sugar")]),
    ("Chocolates and sweets",
     r"chocolate|candy|toffee|jelly|cocoa|sweets|gummy",
     [("Dark chocolate (70% or more cocoa)", "dark chocolate 70 percent"),
      ("Dates and nut laddoos (no added sugar)", "dates nut ladoo"),
      ("Dry fruit bars", "dry fruit bar no added sugar")]),
    ("Breakfast and instant mixes",
     r"cereal|corn\s*flakes|muesli|instant\s*mix|ready\s*to\s*eat|soup|oats",
     [("Plain rolled oats or muesli with no added sugar", "plain rolled oats"),
      ("Millet porridge mix (ragi / jowar)", "ragi porridge mix"),
      ("Poha or upma mix with no preservatives", "poha no preservatives")]),
    ("Bread and bakery",
     r"bread|bun\b|cake|pastry|bakery",
     [("100% whole wheat or multigrain bread", "whole wheat bread"),
      ("Millet bread", "millet bread")]),
]

STORES = [
    ("Amazon", "https://www.amazon.in/s?k="),
    ("Blinkit", "https://blinkit.com/s/?q="),
    ("Zepto", "https://www.zeptonow.com/search?query="),
]

SECTION = re.compile(
    r"ingredients?\s*[:\-]?\s*(.{5,600}?)"
    r"(?=\n\s*\n|nutrition|allergen|may\s*contain|manufactured|mfd|packed\s*by|marketed|net\s*(?:wt|weight|qty|quantity)|mrp|maximum\s*retail|best\s*before|fssai|customer\s*care|storage|$)",
    re.I | re.S)


def find_ingredient_text(text):
    """Cut out the ingredients part of the label text (or '' if none)."""
    m = SECTION.search(text or "")
    if not m:
        return ""
    return " ".join(m.group(1).split()).strip(" .,;:-")


def analyze(ingredient_text, label_text="", product=""):
    """Look through the ingredients and suggest healthier swaps."""
    ing = " ".join((ingredient_text or "").split())
    if not ing:
        return None
    flags = []
    for pattern, name, level, reason in FLAGS:
        if re.search(pattern, ing, re.I):
            flags.append({"name": name, "level": level, "reason": reason})
    flags.sort(key=lambda x: LEVEL_ORDER[x["level"]])

    swaps = None
    if flags:
        hint = " ".join([product or "", label_text or "", ing])
        for kind, pattern, ideas in SWAPS:
            if re.search(pattern, hint, re.I):
                swaps = {
                    "kind": kind,
                    "ideas": [{
                        "name": n,
                        "links": [{"store": s, "url": u + quote_plus(q)} for s, u in STORES],
                    } for n, q in ideas],
                }
                break
    if flags:
        worst = flags[0]["level"]
        verdict = {"Avoid": "Not recommended", "Limit": "Eat in moderation", "Caution": "Use with care"}[worst]
    else:
        verdict = "No flagged ingredients found"
    return {"text": ing, "flags": flags, "swaps": swaps, "verdict": verdict,
            "note": "General nutrition awareness only - not medical advice. Check with a doctor or dietitian for health conditions."}