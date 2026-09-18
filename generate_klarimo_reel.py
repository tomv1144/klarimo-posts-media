"""
Klarimo - Générateur de Reel (vidéo courte, sans voix)
=========================================================
Prend les 4 diapositives générées par generate_reel_visual.py, les enchaîne
avec un léger effet de zoom ("Ken Burns"), ajoute une petite musique de fond
générée par code (aucune voix, aucun échantillon audio existant utilisé,
donc aucun risque de droit d'auteur), et exporte une vidéo verticale prête à
poster comme Reel sur Facebook et Instagram.

Même mécanisme, déjà validé en production, que le Reel du compte "On Est
Tous d'Accord" (generate_reel.py) : uniquement la mise en image change.

Utilisation en import (depuis klarimo_autopost.py) :
    from generate_klarimo_reel import generate_klarimo_reel
    video_path = generate_klarimo_reel(category_tag, title, point_1, point_2, out_dir, seed=3)
"""

import os
import subprocess
import tempfile

from generate_reel_visual import generate_reel_frames
from generate_music import generate_background_music

FPS = 30
SLIDE_DURATION = 4.0  # secondes par diapo (un peu plus long que les blagues :
                       # le contenu Klarimo est plus dense à lire)
ZOOM_END = 1.10


def _make_zoom_clip(image_path, duration, out_path, fps=FPS, zoom_end=ZOOM_END):
    n_frames = int(fps * duration)
    # x/y explicites : sans ça, zoompan zoome par défaut depuis le coin haut-gauche
    # (x=0, y=0), ce qui fait dériver l'image vers le bas-droit au lieu de zoomer
    # bien au centre. Ces deux expressions recentrent la fenêtre de zoom à chaque
    # frame, quel que soit le niveau de zoom atteint.
    #
    # Pré-agrandissement à 6x (avec un filtre lanczos, meilleure qualité) AVANT le
    # zoompan : sans ça, zoompan recadre/rescale directement depuis une image de la
    # taille finale (1080x1920), et comme le point de recadrage se décale d'une
    # fraction de pixel à chaque frame, le texte "scintille"/tremble légèrement
    # d'une frame à l'autre (artefact bien connu du filtre zoompan). En partant
    # d'une image beaucoup plus grande, le ré-échantillonnage a bien plus de détail
    # à interpoler et ce tremblement disparaît presque entièrement (mesuré : la
    # variation de netteté du texte d'une frame à l'autre est divisée par 2 à 3).
    vf = (
        f"scale=6480:11520:flags=lanczos,"
        f"zoompan=z='min(zoom+{(zoom_end - 1) / n_frames:.6f},{zoom_end})':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={n_frames}:s=1080x1920:fps={fps}"
    )
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", image_path,
        "-vf", vf, "-t", str(duration),
        "-pix_fmt", "yuv420p", out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def generate_klarimo_reel(category_tag, title, point_1, point_2, out_dir, seed=0, illustration_path=None):
    """Ne laisse dans out_dir QUE la vidéo finale (reel.mp4) : les images
    intermédiaires par diapo sont fabriquées dans un dossier temporaire et
    supprimées ensuite, pour ne pas alourdir inutilement le dépôt GitHub.

    illustration_path : chemin vers la petite illustration IA à afficher sur
    les 4 diapositives (voir generate_image.py). Optionnel : si None (ou si
    la génération a échoué en amont), les diapositives sont produites
    normalement, juste sans illustration."""
    os.makedirs(out_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        frames_dir = os.path.join(tmp, "frames")
        frames = generate_reel_frames(
            category_tag, title, point_1, point_2, frames_dir,
            illustration_path=illustration_path,
        )
        total_duration = SLIDE_DURATION * len(frames)

        clip_paths = []
        for i, frame_path in enumerate(frames):
            clip_path = os.path.join(tmp, f"clip_{i}.mp4")
            _make_zoom_clip(frame_path, SLIDE_DURATION, clip_path)
            clip_paths.append(clip_path)

        concat_list = os.path.join(tmp, "concat.txt")
        with open(concat_list, "w") as f:
            for c in clip_paths:
                f.write(f"file '{c}'\n")

        silent_video = os.path.join(tmp, "silent.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
             "-c", "copy", silent_video],
            check=True, capture_output=True,
        )

        music_path = os.path.join(tmp, "music.wav")
        generate_background_music(duration_sec=total_duration, output_path=music_path, seed=seed)

        final_path = os.path.join(out_dir, "reel.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-i", silent_video, "-i", music_path,
             "-c:v", "libx264", "-c:a", "aac", "-b:a", "128k",
             "-shortest", "-pix_fmt", "yuv420p", final_path],
            check=True, capture_output=True,
        )

    return final_path


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    path = generate_klarimo_reel(
        "FISCALITÉ IMMOBILIÈRE",
        "Ta plus-value peut être taxée à plus de 37 %.",
        "L'exonération totale n'arrive qu'après 30 ans de détention, pas 22.",
        "À 22 ans, tu es exonéré d'impôt sur le revenu, mais pas encore des prélèvements sociaux.",
        os.path.join(here, "reel_test"),
        seed=2,
        illustration_path="/tmp/test_illustration.png",
    )
    print("Reel Klarimo généré :", path)
