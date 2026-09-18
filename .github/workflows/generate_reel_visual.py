"""
Klarimo - Générateur des diapositives du Reel (format vertical 9:16)
=======================================================================
Crée les 4 images qui composent le Reel Klarimo, dans le même style que le
visuel de post classique (bleu marine / or, Cormorant Garamond + DM Sans) :
  1. Accroche : petite illustration + étiquette catégorie + titre (le "hook")
  2. Point 1 : petite illustration + premier complément d'info (le mécanisme)
  3. Point 2 : petite illustration + second complément d'info (le chiffre)
  4. CTA : petite illustration + rappel de la marque + invitation à écrire

La petite illustration (générée par IA, voir generate_image.py) est la même
sur les 4 diapositives : un visuel discret et cohérent qui accompagne le
sujet du jour, sans jamais prendre le pas sur le texte qui reste l'élément
principal de la marque Klarimo. Si aucune illustration n'a pu être générée
(quota gratuit dépassé, coupure réseau...), les diapositives sont générées
normalement sans elle : ce n'est jamais bloquant pour la publication.

Format 1080x1920 (9:16), le format vertical plein écran utilisé pour les
Reels Facebook/Instagram.

Utilisation en import (depuis generate_klarimo_reel.py) :
    from generate_reel_visual import generate_reel_frames
    frames = generate_reel_frames(category_tag, title, point_1, point_2, out_dir,
                                   illustration_path=chemin_ou_None)
"""

import os
from PIL import Image, ImageDraw, ImageFont, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")
LOGO_PATH = os.path.join(HERE, "klarimo_logo.png")

# --- Palette Klarimo (identique à generate_visual.py / klarimo.fr) ---
NAVY = (26, 43, 74)          # #1A2B4A
NAVY2 = (36, 53, 89)         # #243559 (dégradé)
GOLD = (184, 148, 42)        # #B8942A
GOLD_LIGHT = (245, 237, 216)  # #F5EDD8
OFF_WHITE = (250, 250, 248)   # #FAFAF8
SUBTLE = (185, 196, 214)

W, H = 1080, 1920
FOOTER_SAFE_TOP = H - 230  # au-delà, on empiète sur le logo/pied de page

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
    lines, current = [], ""
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


def fit_font(draw, text, font_path, max_width, max_height, start_size=88, min_size=44):
    size = start_size
    while size >= min_size:
        font = ImageFont.truetype(font_path, size)
        lines = wrap_text_to_width(draw, text, font, max_width)
        line_height = int(size * 1.15)
        total_height = line_height * len(lines)
        widest = max(draw.textbbox((0, 0), l, font=font)[2] for l in lines)
        if total_height <= max_height and widest <= max_width:
            return font, lines, line_height
        size -= 2
    font = ImageFont.truetype(font_path, min_size)
    lines = wrap_text_to_width(draw, text, font, max_width)
    return font, lines, int(min_size * 1.15)


def draw_illustration(base, illustration_path, center_x, top_y, size=240):
    """Colle la petite illustration (carrée, coins arrondis, fin liseré doré)
    centrée horizontalement. Renvoie le y juste en dessous de l'illustration,
    ou top_y inchangé si aucune illustration n'est disponible pour ce cycle."""
    if not illustration_path or not os.path.isfile(illustration_path):
        return top_y

    illustration = Image.open(illustration_path).convert("RGB")
    illustration = ImageOps.fit(illustration, (size, size), Image.LANCZOS)

    radius = 32
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size, size], radius=radius, fill=255)

    base.paste(illustration, (center_x - size // 2, top_y), mask)

    ring = ImageDraw.Draw(base)
    ring.rounded_rectangle(
        [center_x - size // 2, top_y, center_x + size // 2, top_y + size],
        radius=radius, outline=GOLD, width=3,
    )
    return top_y + size


def place_illustration_below(base, illustration_path, center_x, content_bottom_y,
                              max_size=320, min_size=160, min_gap=50):
    """Colle l'illustration SOUS le texte, centrée dans l'espace restant avant le
    pied de page, plutôt que de la coller en haut avec un grand vide en dessous.
    La taille s'adapte à la place réellement disponible (texte plus long = photo
    un peu plus petite), pour ne jamais empiéter sur le logo."""
    if not illustration_path or not os.path.isfile(illustration_path):
        return

    available = FOOTER_SAFE_TOP - content_bottom_y - min_gap
    if available < min_size:
        return  # vraiment pas assez de place (texte très long) : on saute l'illustration

    size = max(min_size, min(max_size, available))
    top_y = content_bottom_y + min_gap + max(0, (available - size) // 2)
    draw_illustration(base, illustration_path, center_x, top_y=int(top_y), size=int(size))


def draw_tag(draw, text, center_x, top_y):
    tag_font = ImageFont.truetype(FONT_TAG, 30)
    tag_text = text.upper()
    bbox = draw.textbbox((0, 0), tag_text, font=tag_font)
    tag_w = (bbox[2] - bbox[0]) + 64
    tag_h = 56
    tag_x = center_x - tag_w // 2
    draw.rounded_rectangle([tag_x, top_y, tag_x + tag_w, top_y + tag_h], radius=28, fill=GOLD_LIGHT)
    draw.text((center_x, top_y + tag_h / 2), tag_text, font=tag_font, fill=NAVY, anchor="mm")
    return top_y + tag_h


def draw_footer(base, draw):
    pad_x = 90
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        logo_h = 64
        ratio = logo_h / logo.height
        logo = logo.resize((int(logo.width * ratio), logo_h))
        base.paste(logo, ((W - logo.width) // 2, H - 190), logo)
    except FileNotFoundError:
        pass
    footer_font = ImageFont.truetype(FONT_FOOTER, 28)
    draw.line([(pad_x, H - 100), (W - pad_x, H - 100)], fill=(60, 76, 108), width=1)
    draw.text((pad_x, H - 70), "KLARIMO", font=footer_font, fill=GOLD, anchor="lm")
    draw.text((W - pad_x, H - 70), "klarimo.fr", font=footer_font, fill=SUBTLE, anchor="rm")


def slide_hook(category_tag, title, output_path, illustration_path=None):
    img = vertical_gradient((W, H), NAVY, NAVY2)
    draw = ImageDraw.Draw(img)
    pad_x = 100
    center_x = W // 2

    tag_bottom = draw_tag(draw, category_tag, center_x, top_y=270)

    max_w = W - 2 * pad_x
    font, lines, line_h = fit_font(draw, title, FONT_TITLE, max_w, max_height=460, start_size=96, min_size=52)
    y = tag_bottom + 60
    for line in lines:
        draw.text((center_x, y), line, font=font, fill=OFF_WHITE, anchor="ma")
        y += line_h

    draw.line([(center_x - 50, y + 30), (center_x + 50, y + 30)], fill=GOLD, width=3)
    content_bottom = y + 30

    place_illustration_below(img, illustration_path, center_x, content_bottom, max_size=320)

    draw_footer(img, draw)
    img.save(output_path, "PNG")
    return output_path


def slide_point(label, point_text, output_path, illustration_path=None):
    img = vertical_gradient((W, H), NAVY, NAVY2)
    draw = ImageDraw.Draw(img)
    pad_x = 110
    center_x = W // 2

    tag_bottom = draw_tag(draw, label, center_x, top_y=290)

    max_w = W - 2 * pad_x
    font, lines, line_h = fit_font(draw, point_text, FONT_SUBTITLE, max_w, max_height=380,
                                    start_size=64, min_size=40)
    y = tag_bottom + 70
    for line in lines:
        draw.text((center_x, y), line, font=font, fill=OFF_WHITE, anchor="ma")
        y += line_h
    content_bottom = y

    place_illustration_below(img, illustration_path, center_x, content_bottom, max_size=300)

    draw_footer(img, draw)
    img.save(output_path, "PNG")
    return output_path


def slide_cta(output_path, illustration_path=None):
    img = vertical_gradient((W, H), NAVY, NAVY2)
    draw = ImageDraw.Draw(img)
    center_x = W // 2

    cta_font, cta_lines, cta_line_h = fit_font(
        draw, "Tu veux savoir si ça te concerne ?", FONT_TITLE,
        W - 200, max_height=260, start_size=76, min_size=48,
    )
    y = 350
    for line in cta_lines:
        draw.text((center_x, y), line, font=cta_font, fill=OFF_WHITE, anchor="ma")
        y += cta_line_h

    sub_font = ImageFont.truetype(FONT_SUBTITLE, 36)
    draw.text((center_x, y + 30), "Envoie-moi un message en privé.", font=sub_font, fill=SUBTLE, anchor="ma")
    content_bottom = y + 30 + 44

    place_illustration_below(img, illustration_path, center_x, content_bottom, max_size=320)

    draw_footer(img, draw)
    img.save(output_path, "PNG")
    return output_path


def generate_reel_frames(category_tag, title, point_1, point_2, out_dir, illustration_path=None):
    os.makedirs(out_dir, exist_ok=True)
    p1 = slide_hook(category_tag, title, os.path.join(out_dir, "reel_1.png"), illustration_path)
    p2 = slide_point("LE MÉCANISME", point_1, os.path.join(out_dir, "reel_2.png"), illustration_path)
    p3 = slide_point("CONCRÈTEMENT", point_2, os.path.join(out_dir, "reel_3.png"), illustration_path)
    p4 = slide_cta(os.path.join(out_dir, "reel_4.png"), illustration_path)
    return [p1, p2, p3, p4]


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    frames = generate_reel_frames(
        "FISCALITÉ IMMOBILIÈRE",
        "Ta plus-value peut être taxée à plus de 37 %.",
        "L'exonération totale n'arrive qu'après 30 ans de détention, pas 22.",
        "À 22 ans, tu es exonéré d'impôt sur le revenu, mais pas encore des prélèvements sociaux.",
        os.path.join(here, "reel_visual_test"),
    )
    print("Diapositives générées :", frames)
