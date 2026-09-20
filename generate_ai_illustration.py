"""
Klarimo - Illustration de fond generee par IA (API OpenAI)
====================================================================================
Remplace le fond navy uni (et la petite icone dessinee localement, gardee comme
filet de secours) par une illustration generee par l'API OpenAI, pensee pour habiller
TOUTE la diapositive : c'est ce qui donne enfin du relief et de la vie au Reel, au lieu
d'un pictogramme minuscule dans un coin sur un fond plat.

IMPORTANT (a bien comprendre avant de configurer quoi que ce soit) : l'abonnement
ChatGPT Plus/Pro (l'application de conversation) NE DONNE AUCUN acces gratuit a cette
API. Il faut un compte separe sur platform.openai.com, avec une carte bancaire
enregistree (facturation a l'usage, rien a voir avec l'abonnement ChatGPT). Cout reel
mesure : environ 0,04 a 0,05 dollar par image en qualite "medium" et taille portrait
1024x1536, soit environ 1 dollar par mois pour un post par jour ouvre. Modele utilise :
gpt-image-2 (modele d'image le plus recent d'OpenAI au moment ou ce fichier a ete
ecrit ; si OpenAI le remplace un jour, un message d'erreur "model not found" dans le
journal GitHub Actions sera le signal qu'il faut mettre a jour OPENAI_IMAGE_MODEL
ci-dessous).

Comme pour l'ancienne tentative avec Gemini, cette etape n'est JAMAIS bloquante pour
la publication : en cas d'echec (cle absente, panne reseau, quota depasse, contenu
refuse par le filtre de securite d'OpenAI...), la fonction renvoie None sans jamais
lever d'exception, et klarimo_autopost.py retombe alors sur l'icone locale classique
(voir generate_local_icon.py) plutot que de bloquer toute la publication.

Utilisation :
    from generate_ai_illustration import generate_ai_illustration
    chemin = generate_ai_illustration(image_prompt, "/chemin/vers/illustration.png")
    # chemin vaut None si la generation a echoue (jamais d'exception)
"""

import base64
import json
import os
import urllib.error
import urllib.request

OPENAI_API_URL = "https://api.openai.com/v1/images/generations"
OPENAI_IMAGE_MODEL = "gpt-image-2"

# Ajoute systematiquement au prompt du jour (ecrit par l'IA de redaction, voir
# klarimo_autopost.py) pour garder un style cohérent sur tous les posts, dans les
# couleurs de la marque, et eviter les pieges classiques de la generation d'image
# (texte illisible genere dans l'image, visages qui sonnent faux, etc.).
STYLE_SUFFIX = (
    "Style: editorial illustration blended with soft realistic photographic lighting "
    "and depth, sophisticated, calm and professional, in the mood of a high-end "
    "independent wealth management and real estate advisory brand. Color palette: deep "
    "muted navy blue, warm gold, cream off-white highlights. Strictly no readable text, "
    "no letters, no numbers, no logos anywhere in the image. No close-up recognizable "
    "human faces (silhouettes, hands, or objects only if a person is implied). Vertical "
    "portrait composition, main visual interest concentrated in the middle of the frame."
)


def generate_ai_illustration(image_prompt, output_path, api_key=None, size="1024x1536",
                              quality="medium", timeout=90):
    """Genere une illustration via l'API OpenAI et l'enregistre dans output_path.
    Renvoie output_path en cas de succes, None en cas d'echec. Ne leve jamais
    d'exception : cette illustration n'est qu'un plus visuel, jamais une condition
    pour publier le Reel du jour."""
    api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("Illustration IA : pas de OPENAI_API_KEY configuree, on saute cette etape.")
        return None
    if not image_prompt:
        print("Illustration IA : pas de image_prompt fourni, on saute cette etape.")
        return None

    full_prompt = f"{image_prompt.strip()} {STYLE_SUFFIX}"
    payload = {
        "model": OPENAI_IMAGE_MODEL,
        "prompt": full_prompt,
        "size": size,
        "quality": quality,
        "n": 1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(
        OPENAI_API_URL, data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"AVERTISSEMENT : echec generation illustration IA ({e.code}) : {body}")
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"AVERTISSEMENT : echec generation illustration IA : {exc}")
        return None

    try:
        item = data["data"][0]
    except (KeyError, IndexError, TypeError):
        print(f"AVERTISSEMENT : reponse API OpenAI inattendue (pas de champ data) : {data}")
        return None

    try:
        # Selon la version de l'API / du modele, l'image revient soit encodee en
        # base64 directement, soit sous forme d'URL a telecharger : on gere les deux
        # pour ne pas dependre d'un format precis qui pourrait changer.
        if item.get("b64_json"):
            image_bytes = base64.b64decode(item["b64_json"])
        elif item.get("url"):
            with urllib.request.urlopen(item["url"], timeout=timeout) as img_resp:
                image_bytes = img_resp.read()
        else:
            print(f"AVERTISSEMENT : ni b64_json ni url dans la reponse OpenAI : {item}")
            return None
    except Exception as exc:  # noqa: BLE001
        print(f"AVERTISSEMENT : echec lecture/telechargement de l'image OpenAI : {exc}")
        return None

    with open(output_path, "wb") as f:
        f.write(image_bytes)
    return output_path


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    result = generate_ai_illustration(
        "A warm lamplit family home at dusk seen from the street, symbolizing "
        "inherited real estate passed down between generations",
        os.path.join(here, "test_ai_illustration.png"),
    )
    print("Resultat :", result)
