"""
CrazyLabs Amazon Strategy — Restyle Script
- Lightens all dark teal fills to CrazyLabs bright palette
- Slide 7: dark teal bg → white; white text flipped to dark
- All font sizes scaled +20%
"""
import re, shutil, zipfile
from pathlib import Path

SRC = Path(r"C:\Users\RotemE\Downloads\CrazyLabs_Amazon_Strategy (1).pptx")
DST = Path(r"C:\Users\RotemE\Downloads\CrazyLabs_Amazon_Strategy_Restyled.pptx")

# ── Color palette ────────────────────────────────────────────────────────────
# Global substitutions applied to all slides:
#   006D7A (darkest teal)  → 007D8F   (lighter teal, Flexion accent)
#   0097A7 (mid teal)      → 00B4C8   (primary CrazyLabs teal, unifies Mamboo)
#   00838F (deco ellipse)  → D6F5F8   (barely-there teal tint)
# Slide 7 only:
#   bg 006D7A              → FFFFFF   (flip to white first)
#   FFFFFF title text      → 00B4C8   (bright teal headline)
#   FFFFFF body ask text   → 1C3A3F   (dark readable body)
GLOBAL_SUBS = [
    ("00838F", "D6F5F8"),   # decorative ellipse → near-white
    ("0097A7", "00B4C8"),   # mid teal → primary (Mamboo header, Works-with labels)
    ("006D7A", "007D8F"),   # dark teal → lighter (Flexion header/name text)
]

# Slide 7 shape IDs to flip from white → dark
S7_TITLE_IDS  = {162}           # title "What We're Asking For" → 00B4C8
S7_BODY_IDS   = {165, 168, 171, 174}  # ask item sentences → 1C3A3F
# IDs 164,167,170,173 = number bullets on teal circles → keep white
# ID  176 = text on teal bottom bar → keep white


# ── Font size helpers ────────────────────────────────────────────────────────
def _scale_sz(m):
    return f'sz="{round(int(m.group(1)) * 1.2)}"'

def _scale_pts(m):
    return f'<a:buSzPts val="{round(int(m.group(1)) * 1.2)}"'


# ── Per-shape text-color flip (slide 7) ─────────────────────────────────────
def flip_slide7_text(xml: str) -> str:
    """Flip white text to dark in specific shape IDs on slide 7."""

    def process_sp(m):
        sp = m.group(0)
        id_m = re.search(r'<p:cNvPr id="(\d+)"', sp)
        if not id_m:
            return sp
        sid = int(id_m.group(1))
        if sid in S7_TITLE_IDS:
            sp = sp.replace('val="FFFFFF"', 'val="00B4C8"')
        elif sid in S7_BODY_IDS:
            sp = sp.replace('val="FFFFFF"', 'val="1C3A3F"')
        return sp

    # Match each <p:sp>...</p:sp> block
    return re.sub(r"<p:sp>.*?</p:sp>", process_sp, xml, flags=re.DOTALL)


# ── Main ─────────────────────────────────────────────────────────────────────
shutil.copy(SRC, DST)
with zipfile.ZipFile(DST) as z:
    data = {n: z.read(n) for n in z.namelist()}

for name in list(data):
    if not (name.startswith("ppt/slides/slide") and name.endswith(".xml")):
        continue

    xml = data[name].decode("utf-8")
    snum = int(re.search(r"slide(\d+)", name).group(1))

    # ── Slide 7: flip dark bg → white BEFORE global subs ──
    if snum == 7:
        # Replace only the <p:bg> block's solidFill
        xml = re.sub(
            r"(<p:bgPr>\s*<a:solidFill>\s*<a:srgbClr val=\")006D7A(\")",
            r"\1FFFFFF\2",
            xml, flags=re.DOTALL
        )
        # Flip content text colors per shape
        xml = flip_slide7_text(xml)

    # ── Global color substitutions ──
    for old, new in GLOBAL_SUBS:
        xml = re.sub(old, new, xml, flags=re.IGNORECASE)

    # ── Scale font sizes +20% ──
    xml = re.sub(r'\bsz="(\d+)"', _scale_sz, xml)
    xml = re.sub(r"<a:buSzPts val=\"(\d+)\"", _scale_pts, xml)

    data[name] = xml.encode("utf-8")

with zipfile.ZipFile(DST, "w", zipfile.ZIP_DEFLATED) as z:
    for name, content in data.items():
        z.writestr(name, content)

print(f"Saved: {DST}")
print()
print("Changes applied:")
print("  [OK] Slide 7: dark teal bg -> white; title in CL teal; ask text dark")
print("  [OK] Card headers: mid/dark teal -> bright CrazyLabs teal")
print("  [OK] Decorative ellipses: dark -> near-white tint")
print("  [OK] Font sizes: +20% across all 7 slides")
