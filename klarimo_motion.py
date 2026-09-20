"""
Klarimo - Moteur de rendu "reveal progressif" pour le Reel
==========================================================================================
Habillage de marque qui reste PERSISTANT a l'ecran (bandeau KLARIMO + categorie en
haut, barre de progression, pied de page), et un contenu qui se REVELE progressivement
scene par scene (le titre apparait ligne par ligne, puis "LE MECANISME", puis "LA
REPONSE", puis l'invitation a transferer), inspire d'une demonstration produite avec
ChatGPT ("Le calcul incomplet"). Le mouvement porte enfin du sens (une information de
plus apparait a chaque etape) au lieu d'etre juste cosmetique.

Accepte optionnellement une illustration de fond par scene principale (voir
background_paths dans render_reel_video / build_keyframes), generee ailleurs par
generate_scene_illustrations.py (API OpenAI) : l'image est melangee au degrade navy de
marque et assombrie sur les bords (vignette) pour que le texte blanc/dore reste
lisible par-dessus. Sans illustration fournie (parametre absent, ou generation
IA indisponible ce cycle-la), le rendu retombe automatiquement sur le degrade navy uni.

Ce fichier est volontairement autonome (aucun import du reste du projet Klarimo autre
que ses polices/logo) : il sert a la fois de moteur de secours local (voir
generate_klarimo_reel.py) ET de modele de reference envoye a l'API OpenAI (voir
generate_video_openai.py), pour que le rendu produit par OpenAI et le rendu de secours
se ressemblent toujours, avec ou sans illustrations.

Utilisation en import :
    from klarimo_motion import render_reel_video
    video_path = render_reel_video(category_tag, title, point_1, point_2, share_line,
                                    out_path, background_paths={"hook": "...", ...})
"""

import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")
LOGO_PATH = os.path.join(HERE, "klarimo_logo.png")

# --- Palette Klarimo (identique au reste du projet) ---
NAVY = (26, 43, 74)          # #1A2B4A
NAVY2 = (36, 53, 89)         # #243559
GOLD = (184, 148, 42)        # #B8942A
GOLD_LIGHT = (245, 237, 216)  # #F5EDD8
OFF_WHITE = (250, 250, 248)   # #FAFAF8
SUBTLE = (185, 196, 214)
BAR_TRACK = (46, 62, 96)

W, H = 1080, 1920
FPS = 30

FONT_TITLE = os.path.join(FONT_DIR, "CormorantGaramond-SemiBold.ttf")
FONT_SUBTITLE = os.path.join(FONT_DIR, "DMSans-Regular.ttf")
FONT_TAG = os.path.join(FONT_DIR, "DMSans-Bold.ttf")
FONT_FOOTER = os.path.join(FONT_DIR, "DMSans-Medium.ttf")

_MEASURE_IMG = Image.new("RGB", (10, 10))
_MEASURE_DRAW = ImageDraw.Draw(_MEASURE_IMG)


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


def apply_vignette(img):
    """Assombrit le haut et le bas de l'image (la ou vivent le bandeau de marque et
    le pied de page) pour garder le texte lisible par-dessus une illustration de
    fond, tout en laissant la bande centrale plus claire."""
    w, h = img.size
    overlay = Image.new("L", (w, h), 0)
    odraw = ImageDraw.Draw(overlay)
    top_h = int(h * 0.40)
    bottom_h = int(h * 0.32)
    for y in range(top_h):
        alpha = int(190 * (1 - y / top_h))
        odraw.line([(0, y), (w, y)], fill=alpha)
    for y in range(bottom_h):
        yy = h - 1 - y
        alpha = int(190 * (1 - y / bottom_h))
        odraw.line([(0, yy), (w, yy)], fill=alpha)
    dark = Image.new("RGB", (w, h), (10, 16, 28))
    return Image.composite(dark, img, overlay)


def draw_background(background_path):
    """Fond plein cadre a partir d'une illustration generee par IA (voir
    generate_scene_illustrations.py), melangee avec le degrade navy de marque puis
    assombrie sur les bords (vignette) pour que le texte blanc/dore reste lisible
    par-dessus. Renvoie None si l'image ne peut pas etre chargee (fichier absent,
    corrompu...) : l'appelant retombe alors sur le degrade navy uni, jamais bloquant."""
    try:
        img = Image.open(background_path).convert("RGB")
    except Exception:
        return None
    img = ImageOps.fit(img, (W, H), method=Image.LANCZOS)
    gradient = vertical_gradient((W, H), NAVY, NAVY2)
    blended = Image.blend(img, gradient, alpha=0.45)
    return apply_vignette(blended)


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


def fit_font(text, font_path, max_width, max_height, start_size=88, min_size=44):
    size = start_size
    while size >= min_size:
        font = ImageFont.truetype(font_path, size)
        lines = wrap_text_to_width(_MEASURE_DRAW, text, font, max_width)
        line_height = int(size * 1.15)
        total_height = line_height * len(lines)
        widest = max(_MEASURE_DRAW.textbbox((0, 0), l, font=font)[2] for l in lines)
        if total_height <= max_height and widest <= max_width:
            return font, lines, line_height
        size -= 2
    font = ImageFont.truetype(font_path, min_size)
    lines = wrap_text_to_width(_MEASURE_DRAW, text, font, max_width)
    return font, lines, int(min_size * 1.15)


def draw_tag_pill(draw, text, center_x, top_y):
    tag_font = ImageFont.truetype(FONT_TAG, 30)
    tag_text = text.upper()
    bbox = draw.textbbox((0, 0), tag_text, font=tag_font)
    tag_w = (bbox[2] - bbox[0]) + 64
    tag_h = 56
    tag_x = center_x - tag_w // 2
    draw.rounded_rectangle([tag_x, top_y, tag_x + tag_w, top_y + tag_h], radius=28, fill=GOLD_LIGHT)
    draw.text((center_x, top_y + tag_h / 2), tag_text, font=tag_font, fill=NAVY, anchor="mm")
    return top_y + tag_h


def draw_chrome(draw, category_tag):
    """Habillage persistant (identique sur TOUTE la video, contrairement au contenu
    central qui change de scene en scene) : marque + categorie en haut, pied de page en
    bas. Reprend le principe vu dans la demonstration ChatGPT : un cadre de marque fixe
    qui donne un repere stable pendant que le contenu se construit au centre."""
    pad_x = 90
    brand_font = ImageFont.truetype(FONT_TAG, 34)
    cat_font = ImageFont.truetype(FONT_FOOTER, 26)
    draw.text((pad_x, 70), "KLARIMO", font=brand_font, fill=GOLD, anchor="lm")
    draw.text((pad_x, 130), category_tag.upper(), font=cat_font, fill=SUBTLE, anchor="lm")
    draw.line([(pad_x, 175), (W - pad_x, 175)], fill=(60, 76, 108), width=1)

    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        logo_h = 56
        ratio = logo_h / logo.height
        logo_resized = logo.resize((int(logo.width * ratio), logo_h))
    except FileNotFoundError:
        logo_resized = None

    footer_font = ImageFont.truetype(FONT_FOOTER, 26)
    tagline_font = ImageFont.truetype(FONT_FOOTER, 24)
    draw.text((W // 2, H - 165), "COMPRENDRE AVANT DE DECIDER", font=tagline_font,
              fill=(120, 132, 158), anchor="mm")
    draw.line([(pad_x, H - 100), (W - pad_x, H - 100)], fill=(60, 76, 108), width=1)
    draw.text((pad_x, H - 70), "KLARIMO", font=footer_font, fill=GOLD, anchor="lm")
    draw.text((W - pad_x, H - 70), "klarimo.fr", font=footer_font, fill=SUBTLE, anchor="rm")
    return logo_resized


def new_canvas(category_tag, background_path=None):
    img = None
    if background_path:
        img = draw_background(background_path)
    if img is None:
        img = vertical_gradient((W, H), NAVY, NAVY2)
    draw = ImageDraw.Draw(img)
    logo = draw_chrome(draw, category_tag)
    if logo is not None:
        img.paste(logo, ((W - logo.width) // 2, H - 145), logo)
    return img, draw


# ---------------------------------------------------------------------------
# Construction des "etats cles" (keyframes) : chaque etat est une image complete
# (canvas + habillage + contenu revele jusque-la). La video finale est obtenue en
# tenant chaque etat quelques images, puis en fondu-enchaine vers l'etat suivant :
# c'est ce fondu qui rend le mouvement porteur de sens (une info de plus apparait)
# plutot que decoratif (un zoom qui ne raconte rien).
# ---------------------------------------------------------------------------

CONTENT_TOP = 420
CONTENT_MAX_W = W - 220


HOLD_STEP = 0.42       # temps d'affichage d'une etape intermediaire (avant que la ligne suivante n'arrive)
TRANS = 0.22           # duree du fondu-enchaine entre deux etapes
LABEL_HOLD = 0.40      # temps ou la petite etiquette (ex: "LE MECANISME") est seule affichee
BASE_FINAL_HOLD = 1.3  # temps de lecture mini une fois TOUT le texte de la scene affiche
READ_HOLD_PER_LINE = 0.85  # temps de lecture supplementaire par ligne de texte (scenes plus longues = tenues plus longtemps)


def _reveal_stages(category_tag, label, lines, font, line_h, color, top_y=CONTENT_TOP,
                    background_path=None):
    """Construit les etats cles d'une scene : d'abord l'etiquette seule (si fournie),
    puis le texte qui apparait ligne par ligne, avec un temps de lecture final
    proportionnel a la longueur du texte (un texte plus long reste plus longtemps a
    l'ecran, plutot qu'une duree fixe qui irait trop vite pour les posts plus denses)."""
    stages = []
    n_total = len(lines)
    final_hold = BASE_FINAL_HOLD + READ_HOLD_PER_LINE * n_total

    if label:
        img, draw = new_canvas(category_tag, background_path=background_path)
        draw_tag_pill(draw, label, W // 2, top_y)
        stages.append((img, LABEL_HOLD, 0.15))

    for n in range(1, n_total + 1):
        img, draw = new_canvas(category_tag, background_path=background_path)
        y = top_y
        if label:
            y = draw_tag_pill(draw, label, W // 2, y) + 60
        for line in lines[:n]:
            draw.text((W // 2, y), line, font=font, fill=color, anchor="ma")
            y += line_h
        hold = final_hold if n == n_total else HOLD_STEP
        trans = TRANS if (n > 1 or label) else 0.15
        stages.append((img, hold, trans))
    return stages


def _scene_hook(category_tag, title, background_path=None):
    font, lines, line_h = fit_font(title, FONT_TITLE, CONTENT_MAX_W, max_height=460,
                                    start_size=92, min_size=54)
    return _reveal_stages(category_tag, None, lines, font, line_h, OFF_WHITE, top_y=CONTENT_TOP,
                           background_path=background_path)


def _scene_point(category_tag, label, text, background_path=None):
    font, lines, line_h = fit_font(text, FONT_SUBTITLE, CONTENT_MAX_W, max_height=380,
                                    start_size=58, min_size=38)
    return _reveal_stages(category_tag, label, lines, font, line_h, OFF_WHITE, top_y=CONTENT_TOP + 40,
                           background_path=background_path)


CTA_SHARE_READ_BONUS = 0.35   # temps de lecture supplementaire par ligne pour la phrase de partage
CTA_OUTRO_BONUS = 0.9         # temps supplementaire pour l'etape finale (outro), qui doit rester
                              # plus longtemps a l'ecran pour laisser le temps de lire l'appel a
                              # l'action complet et, le cas echeant, de faire l'action (transferer)


def _scene_cta(category_tag, share_line, background_path=None):
    """Meme logique de reveal que _reveal_stages (etapes intermediaires courtes, etape
    finale tenue proportionnellement a la quantite de texte a lire), mais geree a la main
    ici car la scene CTA empile plusieurs elements de nature differente (titre, phrase de
    partage doree, sous-titre d'invitation) plutot qu'une simple liste de lignes."""
    stages = []
    title_font, title_lines, title_lh = fit_font(
        "Tu veux savoir si ca te concerne ?", FONT_TITLE, W - 220, max_height=260,
        start_size=72, min_size=46,
    )
    share_font, share_lines, share_lh = None, [], 0
    if share_line:
        share_font, share_lines, share_lh = fit_font(
            share_line, FONT_TAG, W - 240, max_height=140, start_size=36, min_size=26,
        )
    sub_font = ImageFont.truetype(FONT_SUBTITLE, 36)
    sub_text = "Envoie-moi un message en prive."

    n_title = len(title_lines)

    # Etape 1..N : titre revele ligne par ligne (encore une etape a venir ensuite :
    # la phrase de partage et/ou le sous-titre, donc tenue courte comme dans _reveal_stages).
    for n in range(1, n_title + 1):
        img, draw = new_canvas(category_tag, background_path=background_path)
        y = CONTENT_TOP + 60
        for line in title_lines[:n]:
            draw.text((W // 2, y), line, font=title_font, fill=OFF_WHITE, anchor="ma")
            y += title_lh
        stages.append((img, HOLD_STEP, TRANS if n > 1 else 0.15))

    base_y = CONTENT_TOP + 60 + title_lh * n_title + 30

    # Etape suivante : la phrase de partage (doree) apparait, tenue un peu plus longtemps
    # (c'est une information a part entiere, pas juste une ligne de titre de plus).
    if share_lines:
        img, draw = new_canvas(category_tag, background_path=background_path)
        y = CONTENT_TOP + 60
        for line in title_lines:
            draw.text((W // 2, y), line, font=title_font, fill=OFF_WHITE, anchor="ma")
            y += title_lh
        y = base_y
        for line in share_lines:
            draw.text((W // 2, y), line, font=share_font, fill=GOLD, anchor="ma")
            y += share_lh
        share_hold = HOLD_STEP + CTA_SHARE_READ_BONUS * len(share_lines)
        stages.append((img, share_hold, TRANS))
        base_y = y + 20

    # Etape finale : le sous-titre d'invitation apparait. C'est l'outro de tout le Reel :
    # tenue la plus longue, proportionnelle a la quantite totale de texte affiche a l'ecran
    # a ce moment-la (titre + partage + sous-titre), pour laisser le temps de tout lire.
    img, draw = new_canvas(category_tag, background_path=background_path)
    y = CONTENT_TOP + 60
    for line in title_lines:
        draw.text((W // 2, y), line, font=title_font, fill=OFF_WHITE, anchor="ma")
        y += title_lh
    if share_lines:
        y += 30
        for line in share_lines:
            draw.text((W // 2, y), line, font=share_font, fill=GOLD, anchor="ma")
            y += share_lh
        y += 20
    draw.text((W // 2, y), sub_text, font=sub_font, fill=SUBTLE, anchor="ma")

    n_read_lines = n_title + len(share_lines) + 1  # +1 pour le sous-titre
    final_hold = BASE_FINAL_HOLD + READ_HOLD_PER_LINE * n_read_lines + CTA_OUTRO_BONUS
    stages.append((img, final_hold, TRANS))

    return stages


def build_keyframes(category_tag, title, point_1, point_2, share_line, background_paths=None):
    """background_paths (optionnel) : dict {"hook": chemin, "mechanism": chemin,
    "answer": chemin}, une illustration par scene principale (voir
    generate_scene_illustrations.py). Une cle absente ou a None retombe simplement
    sur le degrade navy uni pour cette scene-la. La scene CTA finale reutilise
    l'illustration "answer" (pas de 4e image generee separement)."""
    background_paths = background_paths or {}
    keyframes = []
    keyframes += _scene_hook(category_tag, title, background_path=background_paths.get("hook"))
    keyframes += _scene_point(category_tag, "LE MECANISME", point_1,
                               background_path=background_paths.get("mechanism"))
    keyframes += _scene_point(category_tag, "LA REPONSE", point_2,
                               background_path=background_paths.get("answer"))
    keyframes += _scene_cta(category_tag, share_line, background_path=background_paths.get("answer"))
    # La toute premiere image de la video ne doit pas fondre depuis rien.
    if keyframes:
        img0, hold0, _ = keyframes[0]
        keyframes[0] = (img0, hold0, 0.0)
    return keyframes


def _expand_to_frames(keyframes, fps=FPS):
    """Transforme les etats cles en liste de frames PIL, avec fondu-enchaine entre
    chaque etat. Renvoie aussi la duree totale (secondes), necessaire pour dessiner la
    barre de progression en continu (voir render_reel_video)."""
    frames = []
    prev_img = None
    for img, hold_s, trans_s in keyframes:
        if prev_img is not None and trans_s > 0:
            n_trans = max(1, int(fps * trans_s))
            for i in range(1, n_trans + 1):
                alpha = i / n_trans
                frames.append(Image.blend(prev_img, img, alpha))
        n_hold = max(1, int(fps * hold_s))
        for _ in range(n_hold):
            frames.append(img)
        prev_img = img
    return frames


def render_reel_video(category_tag, title, point_1, point_2, share_line, out_path,
                       fps=FPS, background_paths=None):
    """Fabrique la video silencieuse (sans musique : ajoutee ensuite par
    generate_klarimo_reel.py) du Reel Klarimo, dans le style "reveal progressif",
    avec ou sans illustrations de fond (voir background_paths dans build_keyframes).
    Renvoie out_path. Ne masque pas les erreurs : c'est a l'appelant de decider quoi
    faire en cas d'echec (voir le mecanisme de secours dans generate_klarimo_reel.py)."""
    keyframes = build_keyframes(category_tag, title, point_1, point_2, share_line,
                                 background_paths=background_paths)
    frames = _expand_to_frames(keyframes, fps=fps)
    total_duration = len(frames) / fps

    with tempfile.TemporaryDirectory() as tmp:
        frames_dir = os.path.join(tmp, "frames")
        os.makedirs(frames_dir, exist_ok=True)
        bar_h = 6
        for idx, frame in enumerate(frames):
            frame = frame.copy()
            draw = ImageDraw.Draw(frame)
            progress = min(1.0, (idx / fps) / total_duration) if total_duration else 0
            draw.rectangle([0, 0, W, bar_h], fill=BAR_TRACK)
            draw.rectangle([0, 0, int(W * progress), bar_h], fill=GOLD)
            frame.save(os.path.join(frames_dir, f"frame_{idx:05d}.png"), "PNG")

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        cmd = [
            "ffmpeg", "-y", "-framerate", str(fps),
            "-i", os.path.join(frames_dir, "frame_%05d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    return out_path


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    path = render_reel_video(
        "FISCALITE IMMOBILIERE",
        "Ta plus-value peut etre taxee a plus de 37 %.",
        "L'exoneration totale n'arrive qu'apres 30 ans de detention, pas 22.",
        "A 22 ans, tu es exonere d'impot sur le revenu, mais pas encore des prelevements sociaux.",
        "Un proche encore impose apres 22 ans ? Envoie-lui ce post.",
        os.path.join(here, "motion_test", "reel_silent.mp4"),
    )
    print("Video silencieuse generee :", path)
