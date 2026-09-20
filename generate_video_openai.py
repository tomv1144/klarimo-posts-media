"""
Klarimo - Rendu du Reel par l'API OpenAI (code interpreter)
====================================================================================
Envoie a l'API OpenAI (modele gpt-6-astra, outil "code_interpreter") le contenu du
jour (titre, mecanisme, reponse, phrase de partage) ainsi que les polices, le logo
et un exemple de gabarit (klarimo_motion.py) donnes comme REFERENCE, pas comme
moule obligatoire. La consigne envoyee au modele lui laisse volontairement la main
sur la mise en scene (illustrations, photos stylisees, animations...), a
l'image des Reels Klarimo qu'il a deja produits ("Le calcul incomplet") : seules
la palette de couleurs, les polices, la presence du logo et le texte du contenu
sont imposes, pas le style visuel.

POURQUOI passer par OpenAI plutot que de simplement executer klarimo_motion.py
localement : Tom a explicitement demande que ce soit l'IA d'OpenAI qui "realise"
les videos, avec une vraie liberte creative sur le rendu (le travail de
recherche/fact-checking reste, lui, inchange sur Claude). klarimo_motion.py n'est
QUE le moteur de secours local (voir plus bas) : il ne doit pas etre presente a
OpenAI comme la cible a reproduire, sinon on perd tout l'interet de lui laisser
"realiser" la video.

IMPORTANT (fiabilite) : ce mecanisme est EXPERIMENTAL. La documentation d'OpenAI
elle-meme decrit la recuperation des fichiers produits par le code interpreter
comme pouvant echouer ponctuellement, d'ou les tentatives multiples ci-dessous.
Ce module ne leve JAMAIS d'exception : en cas de probleme (cle absente, panne,
quota, timeout, reponse inattendue, echec de recuperation du fichier...), il
renvoie None, et c'est generate_klarimo_reel.py qui bascule alors automatiquement
sur le moteur de secours local (klarimo_motion.render_reel_video), qui produit un
Reel avec EXACTEMENT le meme style visuel. Le Reel du jour est donc toujours
publie, quoi qu'il arrive cote OpenAI.

Cout approximatif par Reel : quelques centimes a environ 1 dollar (tokens du
modele + session de container OpenAI, facturee par tranche de 20 minutes selon la
memoire allouee). Voir la documentation OpenAI "code interpreter" pour le detail.

Utilisation :
    from generate_video_openai import generate_video_openai
    chemin = generate_video_openai(category_tag, title, point_1, point_2,
                                    share_line, "/chemin/vers/reel_silent.mp4")
    # chemin vaut None si la generation a echoue (jamais d'exception)
"""

import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")
LOGO_PATH = os.path.join(HERE, "klarimo_logo.png")
TEMPLATE_PATH = os.path.join(HERE, "klarimo_motion.py")

API_BASE = "https://api.openai.com/v1"
OPENAI_VIDEO_MODEL = "gpt-6-astra"

# Fichiers de reference envoyes a OpenAI a chaque appel, pour que son rendu suive
# fidelement le meme habillage de marque que le moteur de secours local.
ASSET_FILES = [
    os.path.join(FONT_DIR, "CormorantGaramond-SemiBold.ttf"),
    os.path.join(FONT_DIR, "DMSans-Regular.ttf"),
    os.path.join(FONT_DIR, "DMSans-Bold.ttf"),
    os.path.join(FONT_DIR, "DMSans-Medium.ttf"),
    LOGO_PATH,
    TEMPLATE_PATH,
]

# La documentation OpenAI ne precise pas explicitement quelle valeur de "purpose"
# utiliser pour des fichiers destines a un container code_interpreter : on essaie
# "user_data" (le type generique le plus recent) puis, si refuse, "assistants"
# (l'ancienne valeur historiquement utilisee pour ce genre d'usage).
UPLOAD_PURPOSES_TO_TRY = ("user_data", "assistants")


def _multipart_body(fields, file_field_name, file_path):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        parts.append(f"{value}\r\n".encode("utf-8"))

    filename = os.path.basename(file_path)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(
        (
            f'Content-Disposition: form-data; name="{file_field_name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return boundary, b"".join(parts)


def _upload_file(path, api_key, timeout):
    """Televerse un fichier vers l'API Files d'OpenAI et renvoie son file_id.
    Essaie plusieurs valeurs de "purpose" (voir UPLOAD_PURPOSES_TO_TRY ci-dessus),
    car la doc ne precise pas laquelle utiliser pour le code interpreter."""
    last_error = None
    for purpose in UPLOAD_PURPOSES_TO_TRY:
        boundary, body = _multipart_body({"purpose": purpose}, "file", path)
        req = urllib.request.Request(
            f"{API_BASE}/files", data=body, method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["id"]
        except urllib.error.HTTPError as e:
            last_error = f"{e.code} : {e.read().decode('utf-8', errors='ignore')}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
    raise RuntimeError(f"Echec televersement de {os.path.basename(path)} : {last_error}")


def _upload_all_assets(api_key, timeout):
    return [_upload_file(path, api_key, timeout) for path in ASSET_FILES]


def _build_instructions(category_tag, title, point_1, point_2, share_line):
    return f"""
Tu es en charge de la realisation creative d'un Reel pour Klarimo, cabinet
independant de conseil en immobilier patrimonial (France). Utilise ton outil
code_interpreter (Python, avec Pillow et ffmpeg disponibles) pour produire UNE
video verticale (1080x1920, format mp4, SANS SON) a partir du contenu ci-dessous.

C'est TOI qui decides de la mise en scene : illustrations, photos stylisees,
formes animees, melange de texte et d'elements visuels... tout est possible,
dans le meme esprit que les Reels Klarimo que tu as deja realises par le passe
("Le calcul incomplet" par exemple). Tu n'es surtout pas oblige de te limiter a
du texte seul sur fond uni : une video plus vivante, avec de vraies illustrations
ou photos stylisees en plus du texte, est encouragee si tu penses que ca sert
mieux le sujet du jour.

Contraintes de marque a respecter (les seules obligatoires) :
- Palette : bleu marine profond, or/dore, blanc casse (coherent avec le logo et
  les polices joints).
- Si tu affiches du texte, utilise les polices jointes (CormorantGaramond-SemiBold
  pour les titres/accroches, la famille DMSans pour le reste).
- Le logo Klarimo joint doit apparaitre au moins une fois dans la video (par
  exemple en pied de page ou en marque d'eau discrete).
- Jamais de texte, chiffre ou logo illisible ou deforme genere par erreur dans
  une image que tu generes toi-meme.
- Ton sobre, soigne et professionnel : c'est une marque de conseil patrimonial
  haut de gamme, pas une publicite criarde.
- Le texte du contenu ci-dessous doit apparaitre a l'ecran tel quel (ne le
  reformule pas), mais TU choisis comment, quand et avec quels visuels il
  apparait.

Si tu veux un point de depart technique rapide, un fichier klarimo_motion.py est
joint : il contient un exemple deja utilise par Klarimo (bandeau de marque
persistant + texte qui apparait progressivement). Tu peux t'en inspirer, l'adapter,
ou t'en eloigner completement si tu as une meilleure idee pour ce sujet precis :
ce n'est qu'une reference parmi d'autres, pas un moule a repliquer.

Contenu du jour :
Categorie : {category_tag}
Titre (accroche) : {title}
Le mecanisme : {point_1}
La reponse : {point_2}
Phrase de partage / CTA finale : {share_line}

Une fois la video produite, elle doit etre le seul fichier .mp4 present dans ton
repertoire de sortie, pour que je puisse la recuperer automatiquement ensuite.
""".strip()


def _find_output_file(response_json):
    """Cherche, dans la reponse de l'API, une annotation container_file_citation
    qui pointe vers un fichier .mp4 produit par le code interpreter. Renvoie
    (container_id, file_id) ou None si rien trouve."""
    try:
        for item in response_json.get("output", []):
            for content in item.get("content", []) or []:
                for annotation in content.get("annotations", []) or []:
                    if annotation.get("type") != "container_file_citation":
                        continue
                    filename = annotation.get("filename", "") or ""
                    if filename.lower().endswith(".mp4"):
                        return annotation.get("container_id"), annotation.get("file_id")
        return None
    except (AttributeError, TypeError):
        return None


def _retrieve_container_file(container_id, file_id, api_key, out_path, timeout,
                              attempts=4, wait_between=8):
    """La recuperation de fichiers produits par le code interpreter est documentee
    par OpenAI comme pouvant echouer ponctuellement (probleme cote OpenAI, pas
    cote Klarimo) : on retente donc plusieurs fois avant d'abandonner."""
    url = f"{API_BASE}/containers/{container_id}/files/{file_id}/content"
    last_error = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                file_bytes = resp.read()
            if file_bytes:
                os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
                with open(out_path, "wb") as f:
                    f.write(file_bytes)
                return out_path
            last_error = "reponse vide"
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        if attempt < attempts:
            time.sleep(wait_between)
    print(f"AVERTISSEMENT : echec recuperation du fichier video OpenAI apres {attempts} essais : {last_error}")
    return None


def generate_video_openai(category_tag, title, point_1, point_2, share_line, out_path,
                           api_key=None, timeout=600):
    """Tente de faire produire le Reel silencieux par l'API OpenAI. Ne leve JAMAIS
    d'exception : renvoie out_path en cas de succes, None en cas d'echec (cle
    absente, panne, quota, reponse inattendue, timeout...). L'appelant doit alors
    basculer sur le moteur de secours local (voir klarimo_motion.render_reel_video
    et generate_klarimo_reel.py)."""
    api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("Rendu video OpenAI : pas de OPENAI_API_KEY configuree, on saute cette etape.")
        return None

    try:
        file_ids = _upload_all_assets(api_key, timeout=60)
    except Exception as exc:  # noqa: BLE001
        print(f"AVERTISSEMENT : echec televersement des fichiers de reference vers OpenAI : {exc}")
        return None

    instructions = _build_instructions(category_tag, title, point_1, point_2, share_line)
    payload = {
        "model": OPENAI_VIDEO_MODEL,
        "input": instructions,
        "tools": [
            {"type": "code_interpreter", "container": {"type": "auto", "file_ids": file_ids}}
        ],
    }
    req = urllib.request.Request(
        f"{API_BASE}/responses",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"AVERTISSEMENT : echec appel API OpenAI (responses, {e.code}) : {body}")
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"AVERTISSEMENT : echec appel API OpenAI (responses) : {exc}")
        return None

    found = _find_output_file(data)
    if not found or not all(found):
        print("AVERTISSEMENT : aucun fichier .mp4 identifiable dans la reponse OpenAI.")
        return None
    container_id, file_id = found

    return _retrieve_container_file(container_id, file_id, api_key, out_path, timeout=90)


if __name__ == "__main__":
    result = generate_video_openai(
        "FISCALITE IMMOBILIERE",
        "Ta plus-value peut etre taxee a plus de 37 %.",
        "L'exoneration totale n'arrive qu'apres 30 ans de detention, pas 22.",
        "A 22 ans, tu es exonere d'impot sur le revenu, mais pas encore des prelevements sociaux.",
        "Un proche encore impose apres 22 ans ? Envoie-lui ce post.",
        os.path.join(HERE, "openai_test", "reel_openai.mp4"),
    )
    print("Resultat :", result)
