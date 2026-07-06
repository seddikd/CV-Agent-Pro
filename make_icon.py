"""Génère static/app.ico — icône de l'application (enveloppe sur fond dégradé).

Outil de build uniquement (nécessite Pillow). Reproductible :
    .venv\\Scripts\\python.exe make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "static" / "app.ico"
S = 256  # résolution de rendu (haute qualité, downscalée ensuite)

# Palette (indigo -> bleu), cohérente avec l'esprit "📨 CV Agent".
TOP = (58, 91, 199)      # #3A5BC7
BOTTOM = (37, 99, 235)   # #2563EB
WHITE = (255, 255, 255, 255)


def _rounded_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def _vertical_gradient(size: int, top, bottom) -> Image.Image:
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        grad.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return grad.resize((size, size))


def build() -> None:
    # Fond dégradé arrondi
    base = _vertical_gradient(S, TOP, BOTTOM).convert("RGBA")
    base.putalpha(_rounded_mask(S, radius=56))

    draw = ImageDraw.Draw(base)

    # Enveloppe blanche centrée
    ew, eh = int(S * 0.60), int(S * 0.42)
    ex0 = (S - ew) // 2
    ey0 = (S - eh) // 2 + 6
    ex1, ey1 = ex0 + ew, ey0 + eh
    r = 14

    # Corps de l'enveloppe
    draw.rounded_rectangle([ex0, ey0, ex1, ey1], radius=r, fill=WHITE)

    # Rabat (V) — deux traits des coins supérieurs vers le centre-bas
    cx = S // 2
    flap_bottom = ey0 + int(eh * 0.46)
    line_w = max(6, S // 36)
    draw.line([(ex0 + 4, ey0 + 6), (cx, flap_bottom)], fill=BOTTOM + (255,), width=line_w)
    draw.line([(ex1 - 4, ey0 + 6), (cx, flap_bottom)], fill=BOTTOM + (255,), width=line_w)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base.save(OUT, format="ICO", sizes=sizes)
    print(f"[✓] Icône générée : {OUT}  (tailles : {[s[0] for s in sizes]})")


if __name__ == "__main__":
    build()
