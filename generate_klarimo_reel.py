"""
Klarimo - Générateur de Reel (vidéo courte, sans voix)
=========================================================
Fabrique la vidéo verticale finale (habillage de marque persistant + reveal
progressif du texte, voir klarimo_motion.py) et y ajoute une petite musique de
fond générée par code (aucune voix, aucun échantillon audio existant utilisé,
donc aucun risque de droit d'auteur).

Le rendu de la partie silencieuse (image + texte + mouvement) est tenté d'abord
via l'API OpenAI (voir generate_video_openai.py), à la demande explicite de Tom :
c'est OpenAI qui "réalise" la vidéo. Si ce n'est pas possible ce jour-là (clé
absente, panne, quota, timeout, réponse inattendue...), on bascule
automatiquement sur le moteur de rendu local (klarimo_motion.py), qui produit
EXACTEMENT le même style visuel. Dans les deux cas, la musique de fond est
ajoutée ensuite de la même façon : la publication n'est donc jamais bloquée par
une panne côté OpenAI.

Utilisation en import (depuis klarimo_autopost.py) :
    from generate_klarimo_reel import generate_klarimo_reel
    video_path = generate_klarimo_reel(category_tag, title, point_1, point_2,
                                        share_line, out_dir, seed=3)
"""

import os
import subprocess
import tempfile

from generate_video_openai import generate_video_openai
from generate_scene_illustrations import generate_scene_illustrations
from klarimo_motion import render_reel_video
from generate_music import generate_background_music


def generate_klarimo_reel(category_tag, title, point_1, point_2, share_line, out_dir, seed=0):
    """Ne laisse dans out_dir QUE la vidéo finale (reel.mp4) : les fichiers
    intermédiaires (vidéo silencieuse, musique, illustrations) sont fabriqués
    dans un dossier temporaire et supprimés ensuite, pour ne pas alourdir
    inutilement le dépôt GitHub.

    share_line : courte phrase affichée sur la dernière scène qui invite à
    transférer le Reel à une personne concernée (voir klarimo_motion._scene_cta).

    Avant le rendu, on tente de générer jusqu'à 3 illustrations réelles (une par
    scène) via l'API OpenAI (voir generate_scene_illustrations.py). Si cette
    étape échoue partiellement ou totalement (pas de clé, panne...), les scènes
    concernées retombent simplement sur le fond navy uni habituel : la
    publication n'est jamais bloquée par cette étape."""
    os.makedirs(out_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        silent_video = os.path.join(tmp, "silent.mp4")
        images_dir = os.path.join(tmp, "illustrations")

        image_paths = {}
        try:
            image_paths = generate_scene_illustrations(
                category_tag, title, point_1, point_2, share_line, images_dir,
            )
        except Exception as exc:  # noqa: BLE001 - jamais bloquant, voir docstring du module
            print(f"AVERTISSEMENT : génération des illustrations a levé une exception inattendue ({exc}).")
            image_paths = {}

        rendered = None
        try:
            rendered = generate_video_openai(
                category_tag, title, point_1, point_2, share_line, silent_video,
                image_paths=image_paths,
            )
        except Exception as exc:  # noqa: BLE001 - jamais bloquant, voir docstring du module
            print(f"AVERTISSEMENT : rendu OpenAI a levé une exception inattendue ({exc}). Repli local.")
            rendered = None

        if rendered:
            print("Reel rendu par l'API OpenAI.")
        else:
            print("Rendu OpenAI indisponible ce cycle -> rendu local (klarimo_motion.py).")
            render_reel_video(
                category_tag, title, point_1, point_2, share_line, silent_video,
                background_paths=image_paths,
            )

        # Durée réelle de la vidéo silencieuse (nécessaire pour caler la musique),
        # qu'elle vienne d'OpenAI ou du moteur local : on la lit directement dans
        # le fichier plutôt que de la recalculer, pour rester correct dans les deux cas.
        total_duration = _probe_duration(silent_video)

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


def _probe_duration(video_path, default=20.0):
    """Lit la durée réelle d'une vidéo via ffprobe. En cas d'échec (fichier
    corrompu, ffprobe absent...), renvoie une durée par défaut raisonnable plutôt
    que de bloquer toute la génération du Reel."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True, check=True,
        )
        return max(1.0, float(result.stdout.strip()))
    except Exception as exc:  # noqa: BLE001
        print(f"AVERTISSEMENT : impossible de lire la durée de la vidéo ({exc}), valeur par défaut utilisée.")
        return default


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    path = generate_klarimo_reel(
        "FISCALITÉ IMMOBILIÈRE",
        "Ta plus-value peut être taxée à plus de 37 %.",
        "L'exonération totale n'arrive qu'après 30 ans de détention, pas 22.",
        "À 22 ans, tu es exonéré d'impôt sur le revenu, mais pas encore des prélèvements sociaux.",
        "Un proche encore imposé après 22 ans ? Envoie-lui ce post.",
        os.path.join(here, "reel_test"),
        seed=2,
    )
    print("Reel Klarimo généré :", path)
