"""
Klarimo - Générateur de visuel de publication (Facebook / Instagram)
=====================================================================
Crée une image carrée 1080x1080 au style de klarimo.fr (bleu marine / or,
Cormorant Garamond + DM Sans) à partir d'un titre, d'un sous-titre et
d'une étiquette de catégorie.

Utilisation en ligne de commande (test) :
    python generate_visual.py "Titre du post" "Sous-titre explicatif" "FISCALITÉ" sortie.png

Utilisation en import (depuis le script d'automatisation) :
    from generate_visual import generate_visual
    generate_visual("Titre", "Sous-titre", "CATEGORIE", "sortie.png")
"""

import os
import sys
import textwrap
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")
LOGO_PATH = os.path.join(HERE, "klarimo_logo.png")

# --- Palette Klarimo (identique à klarimo.fr) ---
NAVY = (26, 43, 74)        # #1A2B4A
NAVY2 = (36, 53, 89)       # #243559 (dégradé)
GOLD = (184, 148, 42)      # #B8942A
GOLD_LIGHT = (245, 237, 216)  # #F5EDD8
OFF_WHITE = (250, 250, 248)   # #FAFAF8
SUBTLE = (185, 196, 214)      # variante claire de --text-2 pour fond sombre

W, H = 1080, 1080

FONT_TITLE = os.path.join(FONT_DIR, "CormorantGaramond-SemiBold.ttf")
FONT_SUBTITLE = os.path.join(FONT_DIR, "DMSans-Regular.ttf")
FONT_TAG = os.path.join(FONT_DIR, "DMSans-Bold.ttf")
FONT_FOOTER = os.path.join(FONT_DIR, "DMSans-Medium.ttf")


def vertical_gradient(size, top_color, bottom_color):
    w, h = size
    base = Image.new("RGB", size, top_color)
    draw = ImageDraw.Draw(base)
    for y in range(h):
        ratio = y / h
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * ratio)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * ratio)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * ratio)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return base


def wrap_text_to_width(draw, text, font, max_width):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        trial = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit_title_font(draw, text, max_width, max_height, start_size=88, min_size=44):
    size = start_size
    while size >= min_size:
        font = ImageFont.truetype(FONT_TITLE, size)
        lines = wrap_text_to_width(draw, text, font, max_width)
        line_height = int(size * 1.12)
        total_height = line_height * len(lines)
        widest = max(draw.textbbox((0, 0), l, font=font)[2] for l in lines)
        if total_height <= max_height and widest <= max_width:
            return font, lines, line_height
        size -= 2
    font = ImageFont.truetype(FONT_TITLE, min_size)
    lines = wrap_text_to_width(draw, text, font, max_width)
    return font, lines, int(min_size * 1.12)


def generate_visual(title, subtitle, category_tag, output_path):
    img = vertical_gradient((W, H), NAVY, NAVY2)
    draw = ImageDraw.Draw(img)

    pad_x = 90

    # --- Logo (haut, centré) ---
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        logo_h = 84
        ratio = logo_h / logo.height
        logo = logo.resize((int(logo.width * ratio), logo_h))
        img.paste(logo, ((W - logo.width) // 2, 78), logo)
    except FileNotFoundError:
        pass

    # --- Étiquette catégorie (pilule dorée) ---
    tag_font = ImageFont.truetype(FONT_TAG, 24)
    tag_text = category_tag.upper()
    tag_bbox = draw.textbbox((0, 0), tag_text, font=tag_font)
    tag_w = (tag_bbox[2] - tag_bbox[0]) + 56
    tag_h = 48
    tag_x = (W - tag_w) // 2
    tag_y = 205
    draw.rounded_rectangle(
        [tag_x, tag_y, tag_x + tag_w, tag_y + tag_h], radius=24, fill=GOLD_LIGHT
    )
    draw.text(
        (W / 2, tag_y + tag_h / 2),
        tag_text,
        font=tag_font,
        fill=NAVY,
        anchor="mm",
    )

    # --- Titre (Cormorant Garamond, centré) ---
    max_title_width = W - 2 * pad_x
    title_font, title_lines, line_height = fit_title_font(
        draw, title, max_title_width, max_height=420
    )
    total_title_height = line_height * len(title_lines)
    title_top = 340
    y = title_top + (420 - total_title_height) // 2
    for line in title_lines:
        draw.text((W / 2, y), line, font=title_font, fill=OFF_WHITE, anchor="ma")
        y += line_height

    # --- Ligne dorée de séparation ---
    sep_y = title_top + 420 + 20
    draw.line([(W / 2 - 40, sep_y), (W / 2 + 40, sep_y)], fill=GOLD, width=3)

    # --- Sous-titre (DM Sans, centré) ---
    sub_font = ImageFont.truetype(FONT_SUBTITLE, 30)
    sub_lines = wrap_text_to_width(draw, subtitle, sub_font, W - 2 * (pad_x + 30))
    sy = sep_y + 40
    for line in sub_lines[:3]:
        draw.text((W / 2, sy), line, font=sub_font, fill=SUBTLE, anchor="ma")
        sy += 44

    # --- Pied de page ---
    footer_font = ImageFont.truetype(FONT_FOOTER, 26)
    draw.line([(pad_x, H - 110), (W - pad_x, H - 110)], fill=(60, 76, 108), width=1)
    draw.text((pad_x, H - 80), "KLARIMO", font=footer_font, fill=GOLD, anchor="lm")
    draw.text(
        (W - pad_x, H - 80),
        "klarimo.fr",
        font=footer_font,
        fill=SUBTLE,
        anchor="rm",
    )

    img.save(output_path, "PNG")
    return output_path


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: python generate_visual.py \"Titre\" \"Sous-titre\" \"CATEGORIE\" sortie.png")
        sys.exit(1)
    _, title, subtitle, category, out = sys.argv
    path = generate_visual(title, subtitle, category, out)
    print("Image générée :", path)
