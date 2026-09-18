"""
Génération d'illustration IA (Google Gemini / "Nano Banana")
================================================================
Génère une image à partir d'un image_prompt rédigé par le moteur de contenu,
via l'API Gemini de Google (modèle gemini-2.5-flash-image). Module partagé
entre plusieurs comptes (Ça Alors !, Klarimo...), seul le prompt/style change
d'un appelant à l'autre.

Pourquoi Gemini plutôt qu'un autre service : il propose un vrai niveau
gratuit accessible avec une simple clé API (pas de carte bancaire requise),
largement suffisant pour quelques images par jour (la limite gratuite
courante est de l'ordre de plusieurs centaines d'images par jour, très loin
de nos besoins). À vérifier de temps en temps sur https://aistudio.google.com/rate-limit
car Google ajuste occasionnellement ce quota gratuit.

Aucune image ne contient de texte : le texte est ajouté séparément par le
compositeur de visuel de chaque compte (plus fiable qu'un texte généré par
l'IA image, qui peut contenir des fautes ou des lettres déformées).
"""

import base64
import json
import urllib.request
import urllib.error

GEMINI_MODEL = "gemini-2.5-flash-image"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


def generate_illustration(api_key, image_prompt, output_path,
                           style_suffix="High quality, vertical portrait orientation."):
    """Appelle l'API Gemini pour générer une image à partir d'un prompt texte,
    et l'enregistre dans output_path. Lève une erreur explicite si l'API ne
    renvoie aucune image (ex: quota gratuit dépassé pour la journée).
    style_suffix permet à chaque compte d'ajuster le format attendu (portrait
    plein cadre pour un fond de post, illustration carrée pour une petite
    icône décorative, etc.)."""
    full_prompt = (
        f"{image_prompt}. No text, no letters, no watermark, no logo anywhere in the image. "
        f"{style_suffix}"
    )
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(GEMINI_API_URL, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Erreur API Gemini (image) : {e.read().decode('utf-8', errors='ignore')}")

    for candidate in body.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data and inline_data.get("data"):
                image_bytes = base64.b64decode(inline_data["data"])
                with open(output_path, "wb") as f:
                    f.write(image_bytes)
                return output_path

    raise RuntimeError(f"Aucune image renvoyée par Gemini : {body}")
