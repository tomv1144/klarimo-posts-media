"""
Klarimo - Choix et generation des illustrations du Reel (API OpenAI)
====================================================================================
Avant de demander a OpenAI d'assembler la video (voir generate_video_openai.py),
cette etape genere jusqu'a 3 illustrations reelles, une par scene principale
(accroche / mecanisme / reponse), pour que le Reel ressemble a la demonstration
ChatGPT que Tom a partagee (illustration + texte), plutot qu'a du texte seul sur
fond uni.

POURQUOI EN DEUX ETAPES SEPAREES (et pas tout en un seul appel "code_interpreter") :
l'outil "code_interpreter" d'OpenAI tourne dans un bac a sable SANS ACCES INTERNET
(verifie dans la documentation OpenAI le 20/09/2026) : il peut dessiner avec du code
(formes, degrades, texte), mais il est physiquement incapable de generer une
illustration ou une photo a partir de rien. Pour avoir de vraies illustrations, il
faut donc appeler l'API de generation d'image d'OpenAI (gpt-image-2) nous-memes,
AVANT de passer au code_interpreter, puis lui fournir les images deja generees
comme fichiers a assembler (voir image_paths dans generate_video_openai.py) et/ou
les utiliser directement dans le moteur de secours local (voir background_paths
dans klarimo_motion.py).

Etape 1 : on demande a un modele OpenAI (texte seul, sans outil de code) de choisir
les 3 descriptions d'illustration (une par scene), adaptees precisement au sujet du
jour -- c'est OpenAI qui decide de la mise en scene visuelle, pas Claude, conformement
a la demande de Tom.
Etape 2 : on genere chaque image via generate_ai_illustration.py (deja utilise par
le projet, cout mesure ~0,04-0,05 $ par image en qualite "medium").

Ne leve JAMAIS d'exception : renvoie un dictionnaire {"hook": chemin_ou_None,
"mechanism": chemin_ou_None, "answer": chemin_ou_None}. Une ou plusieurs valeurs
peuvent etre None si cette etape echoue partiellement (cle absente, panne, filtre
de securite OpenAI...) ; l'appelant (generate_klarimo_reel.py) doit gerer ce cas
sans jamais bloquer la publication : klarimo_motion.py retombe automatiquement sur
un fond navy uni pour toute scene dont l'illustration vaut None.

Utilisation :
    from generate_scene_illustrations import generate_scene_illustrations
    images = generate_scene_illustrations(category_tag, title, point_1, point_2,
                                           share_line, out_dir)
    # images["hook"], images["mechanism"], images["answer"] : chemin ou None
"""

import json
import os
import urllib.error
import urllib.request

from generate_ai_illustration import generate_ai_illustration

API_BASE = "https://api.openai.com/v1"
OPENAI_TEXT_MODEL = "gpt-6-astra"

SCENE_KEYS = ("hook", "mechanism", "answer")

PROMPT_TOOL = {
    "type": "function",
    "name": "scene_image_prompts",
    "description": (
        "Trois descriptions d'illustration (en anglais), une pour chaque scene "
        "d'un Reel Klarimo, adaptees precisement au sujet du jour."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "hook_image_prompt": {
                "type": "string",
                "description": (
                    "Scene ou objet symbolique concret (en anglais, 1-2 phrases) pour "
                    "illustrer l'accroche. Pas de texte/chiffre/logo dans l'image, pas "
                    "de visage reconnaissable en gros plan."
                ),
            },
            "mechanism_image_prompt": {
                "type": "string",
                "description": "Memes regles, pour illustrer la scene 'LE MECANISME'.",
            },
            "answer_image_prompt": {
                "type": "string",
                "description": "Memes regles, pour illustrer la scene 'LA REPONSE'.",
            },
        },
        "required": ["hook_image_prompt", "mechanism_image_prompt", "answer_image_prompt"],
        "additionalProperties": False,
    },
    "strict": True,
}


def _ask_image_prompts(category_tag, title, point_1, point_2, api_key, timeout):
    instructions = f"""
Tu choisis la direction artistique d'un Reel Klarimo (cabinet independant de
conseil en immobilier patrimonial, France). Pour le sujet du jour ci-dessous,
propose 3 descriptions d'illustration precises et concretes (une par scene), en
anglais, chacune liee exactement au contenu de sa scene, jamais un decor generique
interchangeable d'un post a l'autre. Melange photographie realiste et illustration
editoriale soignee. Jamais de texte, chiffre ou logo a faire apparaitre dans
l'image. Jamais de visage humain reconnaissable en gros plan (silhouettes, mains ou
objets uniquement si une personne doit etre suggeree).

Categorie : {category_tag}
Accroche (scene 1) : {title}
Mecanisme (scene 2) : {point_1}
Reponse (scene 3) : {point_2}
""".strip()

    payload = {
        "model": OPENAI_TEXT_MODEL,
        "input": instructions,
        "tools": [PROMPT_TOOL],
        "tool_choice": "required",
    }
    req = urllib.request.Request(
        f"{API_BASE}/responses",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    for item in data.get("output", []):
        if item.get("type") == "function_call" and item.get("name") == "scene_image_prompts":
            return json.loads(item["arguments"])
    raise RuntimeError(f"Pas d'appel de fonction dans la reponse OpenAI : {data}")


def generate_scene_illustrations(category_tag, title, point_1, point_2, share_line,
                                  out_dir, api_key=None, timeout=90):
    """Renvoie {"hook": chemin|None, "mechanism": chemin|None, "answer": chemin|None}.
    Ne leve jamais d'exception (voir docstring du module)."""
    results = {key: None for key in SCENE_KEYS}

    api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("Illustrations de scene : pas de OPENAI_API_KEY configuree, on saute cette etape.")
        return results

    try:
        prompts = _ask_image_prompts(category_tag, title, point_1, point_2, api_key, timeout)
    except Exception as exc:  # noqa: BLE001
        print(f"AVERTISSEMENT : echec choix des prompts d'illustration ({exc}). Aucune illustration ce cycle.")
        return results

    prompt_by_key = {
        "hook": prompts.get("hook_image_prompt"),
        "mechanism": prompts.get("mechanism_image_prompt"),
        "answer": prompts.get("answer_image_prompt"),
    }

    os.makedirs(out_dir, exist_ok=True)
    for key in SCENE_KEYS:
        prompt = prompt_by_key.get(key)
        if not prompt:
            continue
        try:
            results[key] = generate_ai_illustration(
                prompt, os.path.join(out_dir, f"illustration_{key}.png"), api_key=api_key,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"AVERTISSEMENT : echec generation illustration '{key}' ({exc}).")
            results[key] = None

    return results


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    out = generate_scene_illustrations(
        "FISCALITE IMMOBILIERE",
        "Ta plus-value peut etre taxee a plus de 37 %.",
        "L'exoneration totale n'arrive qu'apres 30 ans de detention, pas 22.",
        "A 22 ans, tu es exonere d'impot sur le revenu, mais pas encore des prelevements sociaux.",
        "Un proche encore impose apres 22 ans ? Envoie-lui ce post.",
        os.path.join(here, "illustrations_test"),
    )
    print("Illustrations :", out)
