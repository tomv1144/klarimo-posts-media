"""
Klarimo - Petites illustrations dessinées localement (gratuites, sans IA externe)
====================================================================================
Remplace la génération d'illustration via l'API Gemini (qui nécessite désormais une
carte bancaire, même pour un usage minime : Google a retiré la génération d'images de
son niveau 100% gratuit). Ici, on dessine nous-mêmes, avec Pillow, une petite icône
simple et discrète adaptée au thème du post (une maison pour un sujet locatif, un
document pour la fiscalité, etc.). Résultat : zéro coût, zéro dépendance externe,
zéro quota, et toujours disponible (aucune raison technique que ça échoue).

Le style reste volontairement très simple (aplats de couleur, formes géométriques),
dans les couleurs Klarimo (fond crème, tracé bleu marine), pour s'intégrer exactement
comme avant dans le cadre arrondi à liseré doré des diapositives du Reel.

Utilisation :
    from generate_local_icon import draw_icon
    chemin = draw_icon("maison", "/chemin/vers/illustration.png")
"""

import os
from PIL import Image, ImageDraw

# Mêmes couleurs que generate_reel_visual.py, pour rester visuellement cohérent.
NAVY = (26, 43, 74)          # #1A2B4A
GOLD_LIGHT = (245, 237, 216)  # #F5EDD8

SIZE = 800  # dessiné en grand, puis réduit à l'affichage : plus net.

# Liste des icônes disponibles, une par grande thématique Klarimo. Le moteur de
# contenu choisit celle qui correspond le mieux au sujet du jour (voir icon_type
# dans klarimo_autopost.py).
ICON_TYPES = [
    "maison", "document", "parts_sci", "transmission",
    "graphique", "bouclier", "horloge", "cle",
]


def _canvas():
    img = Image.new("RGB", (SIZE, SIZE), GOLD_LIGHT)
    return img, ImageDraw.Draw(img)


def _draw_maison(draw):
    # Toit (triangle) + corps (rectangle) + petite fenêtre, sujet immobilier locatif.
    cx = SIZE // 2
    draw.polygon([(cx, 190), (170, 400), (630, 400)], fill=NAVY)
    draw.rectangle([230, 400, 570, 640], fill=NAVY)
    draw.rectangle([365, 500, 435, 640], fill=GOLD_LIGHT)


def _draw_document(draw):
    # Feuille avec coin plié + lignes de texte + une pièce, sujet fiscalité/impôts.
    draw.rectangle([230, 150, 530, 610], fill=NAVY)
    draw.polygon([(460, 150), (530, 150), (530, 220)], fill=GOLD_LIGHT)
    for y in (280, 340, 400, 460):
        draw.rectangle([275, y, 485, y + 24], fill=GOLD_LIGHT)
    draw.ellipse([460, 520, 610, 670], outline=NAVY, width=22, fill=GOLD_LIGHT)
    draw.ellipse([505, 565, 565, 625], fill=NAVY)


def _draw_parts_sci(draw):
    # Trois cercles qui se chevauchent : parts partagées d'une SCI.
    r = 190
    centers = [(300, 340), (500, 340), (400, 500)]
    for cx, cy in centers:
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=NAVY, width=26)


def _draw_transmission(draw):
    # Arbre généalogique simplifié : un noeud parent, deux enfants, sujet succession.
    draw.ellipse([340, 150, 460, 270], fill=NAVY)
    draw.ellipse([180, 470, 300, 590], fill=NAVY)
    draw.ellipse([500, 470, 620, 590], fill=NAVY)
    draw.line([(400, 270), (400, 380)], fill=NAVY, width=18)
    draw.line([(240, 380), (560, 380)], fill=NAVY, width=18)
    draw.line([(240, 380), (240, 470)], fill=NAVY, width=18)
    draw.line([(560, 380), (560, 470)], fill=NAVY, width=18)


def _draw_graphique(draw):
    # Trois barres montantes, sujet plus-value / rendement.
    bars = [(220, 470, 320, 640), (370, 380, 470, 640), (520, 250, 620, 640)]
    for x0, y0, x1, y1 in bars:
        draw.rectangle([x0, y0, x1, y1], fill=NAVY)
    draw.line([(190, 620), (650, 620)], fill=NAVY, width=14)


def _draw_bouclier(draw):
    # Bouclier simple, sujet protection / gestion des risques.
    draw.polygon(
        [(400, 150), (600, 230), (600, 420), (400, 650), (200, 420), (200, 230)],
        fill=NAVY,
    )
    draw.polygon([(400, 260), (520, 320), (400, 540), (280, 320)], fill=GOLD_LIGHT)


def _draw_horloge(draw):
    # Horloge simple, sujet délais / durée de détention.
    draw.ellipse([160, 160, 640, 640], outline=NAVY, width=32)
    draw.line([(400, 400), (400, 230)], fill=NAVY, width=24)
    draw.line([(400, 400), (520, 460)], fill=NAVY, width=24)
    draw.ellipse([375, 375, 425, 425], fill=NAVY)


def _draw_cle(draw):
    # Clé simple, sujet "clé de lecture" / accès à l'information.
    draw.ellipse([170, 170, 390, 390], outline=NAVY, width=36)
    draw.rectangle([355, 260, 640, 320], fill=NAVY)
    draw.rectangle([540, 320, 580, 390], fill=NAVY)
    draw.rectangle([600, 320, 640, 380], fill=NAVY)


_ICON_DRAWERS = {
    "maison": _draw_maison,
    "document": _draw_document,
    "parts_sci": _draw_parts_sci,
    "transmission": _draw_transmission,
    "graphique": _draw_graphique,
    "bouclier": _draw_bouclier,
    "horloge": _draw_horloge,
    "cle": _draw_cle,
}


def draw_icon(icon_type, output_path):
    """Dessine l'icône demandée (voir ICON_TYPES) et l'enregistre dans output_path.
    Si icon_type n'est pas reconnu (ex: l'IA a halluciné une valeur hors liste),
    on retombe sur 'maison' plutôt que d'échouer : l'illustration n'est jamais
    bloquante pour la publication."""
    drawer = _ICON_DRAWERS.get(icon_type, _draw_maison)
    img, draw = _canvas()
    drawer(draw)
    img.save(output_path, "PNG")
    return output_path


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(here, "icons_test")
    os.makedirs(out_dir, exist_ok=True)
    for name in ICON_TYPES:
        path = draw_icon(name, os.path.join(out_dir, f"{name}.png"))
        print("Icône générée :", path)
