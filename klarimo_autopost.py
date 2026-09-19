"""
KLARIMO - Agent de publication automatique (Facebook + Instagram)
====================================================================
Ce script fait tout, sans intervention humaine, à chaque exécution :

  1. Trouve un angle de contenu + rédige le texte (API Claude), en respectant
     la voix éditoriale et les codes réseaux sociaux de Klarimo.
  2. Fait relire ce contenu par un second appel API qui joue le rôle de
     "relecteur critique" (accroche, structure, avocat du diable, appel à
     l'action) — s'il rejette le contenu, le script régénère une fois, puis
     abandonne la publication de ce cycle plutôt que de publier un contenu
     faible (c'est le filtre qualité qui remplace la relecture humaine).
  3. Génère un Reel vidéo Klarimo (habillage de marque + reveal progressif du
     texte, rendu tenté via l'API OpenAI puis, en secours, par un moteur local ;
     musique de fond générée par code, sans voix) plutôt qu'une simple image
     fixe : c'est nettement plus visible dans les algorithmes Facebook/Instagram
     qu'un post statique.
  4. Commit + push cette vidéo dans CE MÊME dépôt GitHub (nécessaire pour que
     l'API Instagram puisse aller la chercher via raw.githubusercontent.com).
  5. Publie le Reel sur la Page Facebook et sur le compte Instagram
     professionnel.
  6. Enregistre ce qui a été publié (commit + push) pour ne jamais répéter un
     sujet récent, même d'une exécution à l'autre.

Ce script est fait pour tourner comme "GitHub Actions workflow" planifié
(voir .github/workflows/autopost.yml) : il s'exécute sur les serveurs de
GitHub, 24h/24, sans dépendre d'un PC allumé.

Configuration : toutes les clés/identifiants sont lus depuis les variables
d'environnement (voir README / le fichier workflow pour la liste), qui
viennent des "Secrets" du dépôt GitHub. Rien de sensible n'est stocké dans
un fichier ici.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from generate_klarimo_reel import generate_klarimo_reel  # noqa: E402

HISTORY_PATH = os.path.join(HERE, "klarimo_history.json")
LOG_PATH = os.path.join(HERE, "klarimo_autopost.log")
IG_TOKEN_STATE_PATH = os.path.join(HERE, "klarimo_ig_token_state.json")

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-haiku-4-5"
ANTHROPIC_VERSION = "2023-06-01"

FB_API_VERSION = "v21.0"

TEXT_FIELDS = [
    "visual_title", "reel_point_1", "reel_point_2", "reel_share_line",
    "caption_instagram", "caption_facebook",
]


def sanitize_dashes(content):
    """Filet de sécurité : Klarimo interdit le tiret cadratin/demi-cadratin dans ses
    publications (ça sonne 'IA'). On l'interdit dans le prompt, mais on le retire aussi
    ici au niveau du code, au cas où le modèle en laisse passer un."""
    for field in TEXT_FIELDS:
        if field in content and content[field]:
            cleaned = content[field].replace(" — ", ", ").replace(" – ", ", ")
            cleaned = cleaned.replace("—", ",").replace("–", ",")
            content[field] = cleaned
    return content


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def log(message):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_config():
    """Toutes les clés viennent des variables d'environnement, injectées par le
    workflow GitHub Actions depuis les Secrets du dépôt (Settings > Secrets and
    variables > Actions)."""
    required = [
        "ANTHROPIC_API_KEY",
        "GITHUB_REPO",
        "FB_PAGE_ID",
        "FB_PAGE_ACCESS_TOKEN",
        "IG_USER_ID",
        "IG_ACCESS_TOKEN",
    ]
    cfg = {k: os.environ.get(k, "") for k in required}
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        log(f"ERREUR : variables d'environnement manquantes : {missing}")
        sys.exit(1)
    return cfg


def run_git(args):
    result = subprocess.run(["git"] + args, cwd=HERE, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Commande 'git {' '.join(args)}' a échoué : {result.stderr}")
    return result.stdout


def git_commit_and_push(paths, message):
    """Commit + push des fichiers indiqués (chemins relatifs à HERE) dans le
    dépôt courant. Ne fait rien si aucun changement réel (évite un commit vide),
    et ignore silencieusement les chemins qui n'existent pas encore sur disque."""
    existing = [p for p in paths if os.path.isfile(os.path.join(HERE, p))]
    if not existing:
        log(f"Rien à committer pour {paths} (fichier(s) introuvable(s)).")
        return
    subprocess.run(["git", "config", "user.name", "klarimo-autopost-bot"], cwd=HERE)
    subprocess.run(["git", "config", "user.email", "autopost@klarimo.fr"], cwd=HERE)
    run_git(["add"] + existing)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=HERE)
    if diff.returncode == 0:
        log(f"Rien à committer pour {paths} (aucun changement).")
        return
    run_git(["commit", "-m", message])
    run_git(["push"])
    log(f"Commit + push effectué : {message}")


def load_history():
    if os.path.isfile(HISTORY_PATH):
        with open(HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_history(history):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def http_json(url, headers, payload, method="POST"):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw_error": body}


# ---------------------------------------------------------------------------
# Étape 1 : idéation + rédaction (API Claude)
# ---------------------------------------------------------------------------

GENERATION_SYSTEM_PROMPT = """Tu écris pour Klarimo, cabinet de conseil en immobilier patrimonial indépendant,
rémunéré exclusivement sur honoraires (zéro commission, zéro conflit d'intérêts). Positionnement en une phrase :
"Je ne vends rien, j'aide à décider."

CIBLE : particuliers de 35 à 60 ans qui possèdent déjà de l'immobilier locatif (plusieurs biens, une SCI, ou un
patrimoine immobilier qui commence à peser dans leur fiscalité). Ils sont débrouillards mais dépassés par la
complexité fiscale et juridique. Ils ont souvent été mal conseillés par des interlocuteurs qui avaient leurs
propres intérêts (banquier, agent immobilier, promoteur). Ils veulent un interlocuteur qui dit la vérité, même
si ce n'est pas ce qu'ils espèrent entendre.

TON : direct, factuel, sans condescendance. Tutoiement (contenu réseaux sociaux). Ne rassure pas pour rassurer :
si quelque chose ne va pas, le dire clairement. Pédagogue sans être condescendant. Corrige les idées reçues sans
s'excuser de le faire.

HABITUDES D'ÉCRITURE :
- Commencer par un fait concret ou une observation, jamais par du contexte ("Aujourd'hui je voulais vous
  parler de..." est interdit). L'accroche doit nommer une DOULEUR CONCRÈTE (argent perdu, risque, erreur qui
  coûte cher) dès la première phrase, pas une entrée technique abstraite, pas un mot isolé du type "Attends."
  ou "Stop." sans contenu derrière.
- Utiliser "concrètement" pour introduire un exemple.
- Poser une question rhétorique pour faire réfléchir.
- Contraster deux situations ("sans ça... avec ça...").
- Tu peux nommer les choses par leur nom technique (déficit foncier, SCI IR, TMI, nue-propriété, démembrement...),
  mais la PREMIÈRE fois qu'un terme technique apparaît dans le texte, explique-le en une phrase courte séparée,
  ou avec "c'est-à-dire" / "en clair" / "autrement dit" (jamais entre tirets). Exemple : "Le démembrement, c'est
  séparer la propriété entre usufruit et nue-propriété." N'utilise jamais un terme technique sans cette
  clarification si c'est la première occurrence.
- Termine TOUJOURS par une invitation à envoyer un message directement, formulée simplement, par exemple :
  "Si ta situation ressemble à ça, envoie-moi un message." ou "Tu veux vérifier si ça te concerne ? Écris-moi en
  message privé." Jamais "c'est par ici", jamais de lien (il n'y en a pas dans ce post).

TON TRÈS IMPORTANT : écris comme un humain qui tape un post, pas comme une IA. Phrases courtes et simples,
ponctuation ordinaire (point, virgule, deux-points), pas de tournures trop léchées ou trop symétriques. Varie le
rythme des phrases. Ce n'est pas grave si une phrase commence par "Et" ou "Mais". Évite tout ce qui sonne comme
un texte généré : les formulations trop parfaites, les phrases qui s'enchaînent toutes sur le même modèle, les
transitions artificielles.

EXEMPLE DE RÉFÉRENCE (ton et niveau de précision à imiter) :
"37,6 % de taxe sur ta plus-value immobilière. C'est le taux de base en 2026, avant la surtaxe si elle dépasse
50 000 €. Mais dans une SCI à l'IR avec plusieurs associés, chaque associé n'est imposé que sur sa part. Une
plus-value de 150 000 € partagée entre 3 associés à parts égales : personne ne dépasse le seuil, la surtaxe ne
s'applique pas. Ce n'est pas de l'optimisation agressive. C'est la mécanique normale du régime. Beaucoup de
propriétaires ne le savent pas."
-> Remarque : ce chiffre (37,6 %) est un taux légal stable (IR + prélèvements sociaux), donc il peut être cité
tel quel. Un chiffre INSTABLE (barème IR par tranche, seuils réévalués chaque année, statistique de marché) ne
doit PAS être cité avec une précision fausse ; utilise plutôt une formulation qualitative ("une part significative
de ta tranche d'imposition", "selon ta situation, cela peut représenter plusieurs milliers d'euros").

INTERDITS ABSOLUS :
- Le tiret cadratin "—" ou demi-cadratin "–" est STRICTEMENT INTERDIT, dans le texte ET dans le titre/sous-titre
  du visuel, sans aucune exception. N'utilise jamais ce caractère. Pour une incise, utilise des virgules, des
  parenthèses, ou coupe en deux phrases. Utilise uniquement des points, virgules, deux-points, points
  d'interrogation, points de suspension ("...").
- Emojis.
- Superlatifs creux (incroyable, révolutionnaire, unique, exceptionnel).
- Formules creuses ("dans un monde où...", "plus que jamais...", "à l'heure où...").
- Promesses floues, non chiffrables, de rendement garanti, ou un pourcentage/chiffre présenté comme systématique
  sans nuance ("tu peux facilement voir 45 % ou plus" est interdit, trop vague ET trop affirmatif à la fois).
- Faire croire qu'une correction ou récupération fiscale est automatique alors qu'elle dépend de démarches,
  délais ou conditions : dans ce cas, le dire explicitement ("sous conditions de délai", "à vérifier avec ta
  situation").
- Jargon marketing déguisé en conseil ("solution clé en main", "accompagnement sur-mesure" sans contenu).
- Inventer une anecdote ou un cas client précis présenté comme réel (aucune fausse histoire personnelle).
- Citer un taux, seuil ou barème fiscal précis et récent sans le signaler comme "à vérifier" : en cas de doute
  sur un chiffre exact ou une règle qui change souvent, décris le mécanisme général plutôt qu'un chiffre daté
  (ex: privilégier "le déficit foncier est plafonné chaque année" plutôt qu'inventer un montant si tu n'es pas
  certain qu'il est encore d'actualité). Un chiffre juridique stable et connu (comme un taux légal fixe) peut
  être cité normalement.

ANGLES AUTORISÉS (choisis-en un, adapté au sujet) :
1. La croyance à contredire : ce que la cible pense être vrai, et qui ne l'est pas.
2. L'erreur courante : ce que même des propriétaires expérimentés font mal.
3. Le coût caché : la conséquence invisible d'une habitude banale en gestion locative/patrimoniale.
4. L'avant/après : une transformation concrète avec la méthode (générique, jamais un cas client inventé).

OBJECTIF PARTAGE (très important) : le signal le plus fort aujourd'hui pour qu'un Reel soit recommandé à plus
de monde par Facebook/Instagram, ce n'est plus juste le temps de visionnage, c'est le nombre de fois où il est
ENVOYÉ EN MESSAGE PRIVÉ à quelqu'un (déclaration publique d'Adam Mosseri, responsable Instagram). Concrètement :
en écrivant le post, pense TOUJOURS à une personne précise et concrète à qui le lecteur voudrait transférer ce
contenu (son associé de SCI, son frère ou sa soeur pour une succession, son conjoint pour une décision
immobilière commune). Ça doit rester une invitation naturelle et spécifique au sujet du jour, JAMAIS une formule
artificielle et générique du type "tague un ami" ou "partage à 3 personnes" (ce genre de procédé est pénalisé
par la plateforme).

FORMAT INSTAGRAM/FACEBOOK :
- Légende qui complète le visuel, ne le décrit pas.
- Première phrase = accroche forte qui nomme la douleur (fait ou question), visible avant "plus".
- Paragraphes très courts (1-3 lignes), lecture mobile.
- Deux appels à l'action, dans cet ordre : d'abord l'invitation à transférer le post à la personne concernée
  (voir OBJECTIF PARTAGE ci-dessus), puis l'invitation à envoyer un message privé pour son propre cas (jamais de
  lien).
- Longueur : 60 à 130 mots.
- OBLIGATOIRE : le champ hashtags ne doit JAMAIS être vide. Toujours entre 6 et 10 hashtags pertinents et
  spécifiques (immobilier, fiscalité, patrimoine, SCI, investissement locatif, transmission...), en français,
  sans espace, sans accent si besoin d'unicité. Évite les hashtags trop génériques et trop concurrentiels tout
  seuls (#immobilier utilisé seul ne sert à rien) : mélange 2-3 hashtags larges et 4-6 plus précis/de niche liés
  au sujet exact du post (ex: #deficitfoncier, #SCIfamiliale, #plusvalueimmobiliere selon le sujet traité).
- Les légendes Instagram et Facebook doivent être DIFFÉRENTES l'une de l'autre (angle d'attaque ou formulation
  distincte), pas de simple copier-coller entre les deux.

FORMAT REEL (vidéo courte, 4 scènes silencieuses avec musique de fond) : ce compte publie désormais en
Reel plutôt qu'en simple image fixe, car c'est beaucoup plus visible dans les algorithmes Facebook/Instagram.
Pour que les gens regardent jusqu'au bout (et pas seulement la première diapo), le Reel doit fonctionner comme
une BOUCLE OUVERTE : la diapo 1 lance une affirmation ou une question qui donne clairement l'impression qu'il
manque un morceau de l'histoire, et la diapo 3 apporte le dénouement qui la referme. Sans cette tension, les
gens n'ont aucune raison de rester jusqu'à la fin.
- visual_title (diapo 1, l'accroche) : formule-le pour qu'il crée cette boucle ouverte. Ne donne jamais toute
  l'information dans le titre lui-même : nomme le problème ou le chiffre choc, mais garde l'explication ou la
  nuance pour la suite. Exemple de boucle ouverte : "Ta plus-value peut être taxée à plus de 37 %." (donne envie
  de savoir pourquoi et s'il y a moyen d'y échapper) plutôt qu'une phrase qui expliquerait déjà tout.
- reel_point_1 (diapo 2, "LE MÉCANISME") : explique la raison pour laquelle l'accroche est vraie ou comment ça
  fonctionne concrètement, sans encore donner la résolution complète. Une seule phrase, 10 à 18 mots, aussi
  rigoureuse que le reste (mêmes règles sur les chiffres instables, voir INTERDITS ABSOLUS).
- reel_point_2 (diapo 3, "LA RÉPONSE") : c'est le DÉNOUEMENT qui referme la boucle ouverte de la diapo 1 : le
  chiffre, l'exception, ou la conséquence concrète que la personne attendait depuis le début. Cette diapo doit
  donner l'impression d'une vraie réponse, pas juste un détail de plus. Une seule phrase, 10 à 18 mots, mêmes
  règles.
Ces deux phrases doivent se lire vite (diapo affichée quelques secondes à l'écran), donc rester très simples,
un seul fait par phrase, jamais deux idées imbriquées.

Tu dois aussi produire reel_share_line : une courte phrase (6 à 12 mots) affichée sur la toute dernière diapo,
qui invite à transférer CE Reel précis à une personne concrète concernée par CE sujet précis (même logique que
OBJECTIF PARTAGE plus haut, mais formulée pour être lue en une seconde à l'écran, pas comme une phrase de
légende). Exemple pour un post sur les parts de SCI : "Un associé de SCI dans tes contacts ? Envoie-lui ça."
Jamais générique, toujours ancrée dans le sujet du jour.

Réponds uniquement en appelant l'outil "post_content" fourni."""

GENERATION_TOOL = {
    "name": "post_content",
    "description": "Le contenu complet d'une publication Klarimo prête à être révisée puis publiée.",
    "input_schema": {
        "type": "object",
        "properties": {
            "angle_type": {
                "type": "string",
                "enum": ["croyance_a_contredire", "erreur_courante", "cout_cache", "avant_apres"],
            },
            "sujet": {"type": "string", "description": "Résumé du sujet en une courte phrase, pour l'historique."},
            "category_tag": {
                "type": "string",
                "description": "Étiquette courte affichée sur le visuel, ex: FISCALITÉ IMMOBILIÈRE, SCI, TRANSMISSION.",
            },
            "visual_title": {"type": "string", "description": "Titre du visuel (diapo 1, l'accroche), 8 mots maximum."},
            "reel_point_1": {
                "type": "string",
                "description": "Diapo 2 du Reel : le mécanisme derrière le titre, 10 à 18 mots.",
            },
            "reel_point_2": {
                "type": "string",
                "description": "Diapo 3 du Reel (LA RÉPONSE) : le dénouement qui referme la boucle ouverte du titre, 10 à 18 mots.",
            },
            "reel_share_line": {
                "type": "string",
                "description": "Diapo 4 du Reel : courte invitation (6 à 12 mots) à transférer ce Reel précis à une personne concernée par ce sujet précis.",
            },
            "caption_instagram": {"type": "string"},
            "caption_facebook": {"type": "string"},
            "hashtags": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 6,
                "maxItems": 10,
                "description": "Jamais vide : 6 à 10 hashtags, sans le caractère #, sans espace.",
            },
        },
        "required": [
            "angle_type", "sujet", "category_tag", "visual_title",
            "reel_point_1", "reel_point_2", "reel_share_line",
            "caption_instagram", "caption_facebook", "hashtags",
        ],
    },
}

REVIEW_SYSTEM_PROMPT = """Tu es un relecteur critique externe pour Klarimo (conseil immobilier patrimonial
indépendant). Tu n'es pas là pour faire plaisir, mais tu n'es pas là non plus pour justifier ton rôle en
inventant des critiques artificielles. Si le contenu est solide, tu l'approuves franchement.

Vérifie ces 6 critères, mais NE REJETTE (approved=false) QUE si au moins un problème RÉELLEMENT BLOQUANT existe
parmi ceux-ci :
- Accroche tellement molle ou creuse qu'elle ne donne AUCUNE raison de continuer la lecture (un simple manque de
  punch n'est pas bloquant, une accroche vide de sens l'est).
- Un chiffre, taux ou statistique instable/non vérifiable est présenté comme un fait certain et systématique
  (ex: "tu peux facilement voir 45 % ou plus").
- Une promesse floue, un rendement garanti, ou une régularisation présentée comme automatique alors qu'elle est
  conditionnelle.
- Un terme technique central au post n'est pas du tout expliqué, rendant le post incompréhensible pour un lecteur
  non initié.
- Non-conformité grave à la marque : emoji, superlatif creux, fausse anecdote client présentée comme réelle,
  vouvoiement au lieu du tutoiement.
- Appel à l'action absent, ou un lien/bouton est mentionné alors qu'il n'y en a pas dans ce post (l'action doit
  toujours être "envoyer un message privé", jamais un lien).
- Le texte contient un tiret cadratin/demi-cadratin ("—" ou "–"), ou sonne artificiel/trop léché pour un post
  écrit par un humain (phrases toutes construites sur le même modèle, transitions trop parfaites).
- La liste de hashtags est vide, contient moins de 5 hashtags, ou n'a aucun rapport avec le sujet traité.
- reel_point_1 ou reel_point_2 sont manquants, trop longs pour tenir sur une diapo (plus de 20 mots), disent la
  même chose l'un que l'autre, ou contiennent un chiffre instable présenté comme certain (même règle que pour
  les légendes).
- reel_point_2 ne referme pas vraiment ce que reel_point_1/le titre laissaient en suspens (pas de vrai
  dénouement), ou reel_share_line est une formule générique de type "tague un ami"/"partage à 3 personnes" au
  lieu d'être ancrée dans le sujet précis du jour.

Les remarques de style, de longueur, de répétition entre les deux légendes, ou les préférences personnelles de
formulation vont dans "issues" pour information, MAIS NE DOIVENT JAMAIS À ELLES SEULES FAIRE PASSER approved À
false. En cas de doute entre approuver et rejeter sur un point non listé ci-dessus comme bloquant, APPROUVE.

Si tu rejettes, propose SYSTÉMATIQUEMENT une légende Instagram et une légende Facebook corrigées qui règlent
précisément le ou les points bloquants (garde tout le reste du texte identique). Réponds uniquement en appelant
l'outil "content_review" fourni."""

REVIEW_TOOL = {
    "name": "content_review",
    "description": "Verdict de relecture qualité avant publication.",
    "input_schema": {
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "issues": {"type": "array", "items": {"type": "string"}},
            "corrected_caption_instagram": {"type": "string"},
            "corrected_caption_facebook": {"type": "string"},
            "corrected_hashtags": {"type": "array", "items": {"type": "string"}},
            "corrected_reel_point_1": {"type": "string"},
            "corrected_reel_point_2": {"type": "string"},
            "corrected_reel_share_line": {"type": "string"},
        },
        "required": ["approved", "issues"],
    },
}


def call_claude(api_key, system_prompt, user_message, tool):
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 1500,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": tool["name"]},
    }
    status, resp = http_json(ANTHROPIC_API_URL, headers, payload)
    if status != 200:
        raise RuntimeError(f"Erreur API Claude ({status}) : {resp}")
    for block in resp.get("content", []):
        if block.get("type") == "tool_use":
            return block["input"]
    raise RuntimeError(f"Réponse API Claude sans tool_use : {resp}")


def generate_content(api_key, recent_topics):
    avoid = "\n".join(f"- {t}" for t in recent_topics) or "(aucun sujet récent)"
    user_message = (
        "Rédige une nouvelle publication Klarimo (Facebook + Instagram).\n\n"
        f"Sujets déjà traités récemment, à ÉVITER de répéter :\n{avoid}\n\n"
        "Choisis un sujet différent, toujours dans le champ de l'immobilier patrimonial "
        "(fiscalité locative, SCI, transmission, arbitrage garder/vendre, structuration du patrimoine)."
    )
    return call_claude(api_key, GENERATION_SYSTEM_PROMPT, user_message, GENERATION_TOOL)


def review_content(api_key, content):
    hashtags_preview = ", ".join(content.get("hashtags") or []) or "(AUCUN, champ vide)"
    user_message = (
        "Voici le contenu à relire avant publication :\n\n"
        f"Titre visuel (diapo 1, l'accroche) : {content['visual_title']}\n\n"
        f"Diapo 2 du Reel (mécanisme) : {content.get('reel_point_1', '')}\n"
        f"Diapo 3 du Reel (la réponse, dénouement de la boucle ouverte du titre) : {content.get('reel_point_2', '')}\n"
        f"Diapo 4 du Reel (invitation à transférer) : {content.get('reel_share_line', '')}\n\n"
        f"Légende Instagram :\n{content['caption_instagram']}\n\n"
        f"Légende Facebook :\n{content['caption_facebook']}\n\n"
        f"Hashtags proposés : {hashtags_preview}"
    )
    return call_claude(api_key, REVIEW_SYSTEM_PROMPT, user_message, REVIEW_TOOL)


# ---------------------------------------------------------------------------
# Étape 1c : jeton Instagram longue durée -> renouvellement automatique
# ---------------------------------------------------------------------------

def get_fresh_ig_token(config_token):
    """Renvoie un jeton Instagram valide, en le renouvelant automatiquement.

    Meta impose de renouveler un jeton longue durée Instagram avant ses 60
    jours d'existence. On le renouvelle ici à CHAQUE exécution (Meta autorise
    le renouvellement dès 24h après la dernière émission) pour ne jamais
    avoir à refaire la procédure d'autorisation manuellement. Le nouveau
    jeton est mémorisé dans klarimo_ig_token_state.json et prime sur celui
    de klarimo_config.env dès qu'il existe.
    """
    current_token = config_token
    if os.path.isfile(IG_TOKEN_STATE_PATH):
        with open(IG_TOKEN_STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
        current_token = state.get("access_token", config_token)

    url = (
        "https://graph.instagram.com/refresh_access_token"
        f"?grant_type=ig_refresh_token&access_token={urllib.parse.quote(current_token)}"
    )
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        new_token = data.get("access_token")
        if new_token:
            with open(IG_TOKEN_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "access_token": new_token,
                        "refreshed_at": datetime.now().isoformat(timespec="seconds"),
                        "expires_in_seconds": data.get("expires_in"),
                    },
                    f,
                    indent=2,
                )
            log("Jeton Instagram renouvelé avec succès (valable ~60 jours de plus).")
            return new_token
    except urllib.error.HTTPError as e:
        log(
            "AVERTISSEMENT : échec du renouvellement du jeton Instagram "
            f"({e.code}) : {e.read().decode('utf-8', errors='ignore')}. "
            "On continue avec le jeton actuel ; s'il a expiré, la publication "
            "Instagram échouera plus bas et il faudra refaire l'autorisation manuelle."
        )
    except Exception as exc:  # noqa: BLE001
        log(f"AVERTISSEMENT : échec du renouvellement du jeton Instagram : {exc}")

    return current_token


# ---------------------------------------------------------------------------
# Étape 2 : hébergement de la vidéo (commit direct dans le dépôt, via git)
# ---------------------------------------------------------------------------

def publish_video_and_get_url(repo, relative_path):
    """Commit + push la vidéo (déjà écrite sur disque à HERE/relative_path), puis
    renvoie son URL publique raw.githubusercontent.com. On attend un peu après
    le push pour laisser le CDN de GitHub servir le fichier avant que
    Facebook/Instagram n'essaient de le télécharger."""
    git_commit_and_push([relative_path], f"Nouveau Reel : {relative_path}")
    raw_url = f"https://raw.githubusercontent.com/{repo}/main/{relative_path}"
    time.sleep(6)
    return raw_url


# ---------------------------------------------------------------------------
# Étape 3 : publication Facebook + Instagram (Reel vidéo)
# ---------------------------------------------------------------------------

def _ig_wait_until_finished(creation_id, ig_token, label, max_attempts=20, sleep_seconds=3):
    """Interroge Instagram jusqu'à ce que le conteneur (image ou vidéo) soit marqué
    FINISHED. Le traitement d'une vidéo est nettement plus lourd que celui d'une image
    et peut occasionnellement prendre plusieurs minutes (transcodage pour le flux
    Reels) : c'est pour ça qu'on lui passe un délai bien plus long qu'à une image
    (leçon apprise sur le compte On Est Tous d'Accord, dont le premier Reel avait
    timeout avec seulement 1 minute d'attente)."""
    status_url = (
        f"https://graph.instagram.com/{FB_API_VERSION}/{creation_id}"
        f"?fields=status_code&access_token={urllib.parse.quote(ig_token)}"
    )
    for attempt in range(max_attempts):
        time.sleep(sleep_seconds)
        req = urllib.request.Request(status_url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp_raw:
                status_data = json.loads(resp_raw.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Erreur vérification statut ({label}) : {e.read().decode('utf-8', errors='ignore')}")
        code = status_data.get("status_code")
        log(f"Statut {label} ({attempt + 1}/{max_attempts}) : {code}")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Le traitement de {label} a échoué : {status_data}")
    raise RuntimeError(f"{label} n'était toujours pas prêt après l'attente maximale.")


def publish_facebook_video(page_id, page_token, video_url, description):
    """Publie une vidéo sur la Page via une URL déjà hébergée. Les vidéos
    verticales courtes sont généralement traitées comme des Reels par
    Facebook automatiquement."""
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}/videos"
    payload = {
        "file_url": video_url,
        "description": description,
        "access_token": page_token,
        "published": "true",
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Erreur publication vidéo Facebook : {e.read().decode('utf-8', errors='ignore')}")


def publish_instagram_reel(ig_user_id, ig_token, video_url, caption):
    # Ce compte utilise la connexion directe "Instagram business login" (pas une Page
    # Facebook liée) : le jeton IGAA... n'est valide que sur l'hôte graph.instagram.com,
    # PAS sur graph.facebook.com (qui renverrait "Invalid OAuth access token").
    status, resp = http_json(
        f"https://graph.instagram.com/{FB_API_VERSION}/{ig_user_id}/media",
        {"Content-Type": "application/json"},
        {"media_type": "REELS", "video_url": video_url, "caption": caption, "access_token": ig_token},
    )
    if status != 200 or "id" not in resp:
        raise RuntimeError(f"Erreur création conteneur Reel Instagram ({status}) : {resp}")
    creation_id = resp["id"]

    # Une vidéo met beaucoup plus longtemps à être traitée qu'une image : jusqu'à 10
    # minutes d'attente (60 tentatives de 10 secondes) avant d'abandonner.
    _ig_wait_until_finished(creation_id, ig_token, "Reel Instagram", max_attempts=60, sleep_seconds=10)

    status, resp = http_json(
        f"https://graph.instagram.com/{FB_API_VERSION}/{ig_user_id}/media_publish",
        {"Content-Type": "application/json"},
        {"creation_id": creation_id, "access_token": ig_token},
    )
    if status != 200:
        raise RuntimeError(f"Erreur publication Reel Instagram ({status}) : {resp}")
    return resp


# ---------------------------------------------------------------------------
# Programme principal
# ---------------------------------------------------------------------------

def main():
    log("=" * 70)
    log("KLARIMO AUTOPOST - démarrage")
    cfg = load_config()
    history = load_history()
    recent_topics = [h["sujet"] for h in history[-15:]]

    ig_token = get_fresh_ig_token(cfg["IG_ACCESS_TOKEN"])
    # On committe tout de suite le nouveau jeton (s'il a changé) : sur GitHub
    # Actions chaque exécution part d'un dossier neuf, donc si on ne le
    # sauvegarde pas ici, il serait perdu à la fin de cette exécution.
    git_commit_and_push([os.path.basename(IG_TOKEN_STATE_PATH)], "Renouvellement jeton Instagram")

    # --- Étape 1a : génération ---
    log("Génération du contenu (API Claude)...")
    content = sanitize_dashes(generate_content(cfg["ANTHROPIC_API_KEY"], recent_topics))
    log(f"Sujet proposé : {content['sujet']} (angle: {content['angle_type']})")

    # --- Étape 1b : relecture qualité ---
    max_attempts = 3
    approved = False
    for attempt in range(max_attempts):
        log(f"Relecture qualité (tentative {attempt + 1}/{max_attempts})...")
        review = review_content(cfg["ANTHROPIC_API_KEY"], content)
        if review.get("approved"):
            log("Contenu approuvé.")
            approved = True
            break

        log(f"Contenu rejeté : {review.get('issues')}")
        has_corrections = bool(
            review.get("corrected_caption_instagram")
            or review.get("corrected_caption_facebook")
            or review.get("corrected_hashtags")
            or review.get("corrected_reel_point_1")
            or review.get("corrected_reel_point_2")
            or review.get("corrected_reel_share_line")
        )
        if review.get("corrected_caption_instagram"):
            content["caption_instagram"] = review["corrected_caption_instagram"]
        if review.get("corrected_caption_facebook"):
            content["caption_facebook"] = review["corrected_caption_facebook"]
        if review.get("corrected_hashtags"):
            content["hashtags"] = review["corrected_hashtags"]
        if review.get("corrected_reel_point_1"):
            content["reel_point_1"] = review["corrected_reel_point_1"]
        if review.get("corrected_reel_point_2"):
            content["reel_point_2"] = review["corrected_reel_point_2"]
        if review.get("corrected_reel_share_line"):
            content["reel_share_line"] = review["corrected_reel_share_line"]

        if attempt == max_attempts - 1:
            break

        if not has_corrections:
            # Le relecteur n'a proposé aucune correction concrète -> on repart sur un sujet différent
            content = generate_content(cfg["ANTHROPIC_API_KEY"], recent_topics + [content["sujet"]])
        content = sanitize_dashes(content)
        # Si des corrections ont été appliquées, la prochaine itération relit la version corrigée.

    if not approved:
        log("Contenu toujours rejeté après plusieurs tentatives -> ABANDON de ce cycle, rien n'est publié.")
        return

    # --- Étape 2 : Reel vidéo (rendu tenté via l'API OpenAI, sinon moteur local) ---
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    relative_dir = f"posts/{stamp}"
    out_dir = os.path.join(HERE, relative_dir)
    os.makedirs(out_dir, exist_ok=True)

    log("Génération du Reel (rendu OpenAI, avec repli automatique sur le moteur local)...")
    video_path = generate_klarimo_reel(
        content["category_tag"], content["visual_title"],
        content["reel_point_1"], content["reel_point_2"],
        content.get("reel_share_line"),
        out_dir=out_dir, seed=abs(hash(content["sujet"])) % 1000,
    )

    # --- Étape 3 : hébergement de la vidéo (commit + push dans ce même dépôt) ---
    log("Publication du Reel dans le dépôt GitHub...")
    relative_video_path = os.path.relpath(video_path, HERE)
    video_url = publish_video_and_get_url(cfg["GITHUB_REPO"], relative_video_path)
    log(f"Vidéo publique : {video_url}")

    # Filet de sécurité : quoi qu'il arrive (modèle qui oublie le champ, ancienne
    # version du contenu, etc.), un post Klarimo ne part JAMAIS sans hashtags,
    # ça fait perdre énormément de portée sur Facebook/Instagram.
    DEFAULT_HASHTAGS = [
        "immobilier", "patrimoine", "fiscaliteimmobiliere", "investissementlocatif",
        "sci", "gestionlocative", "immobilierpatrimonial", "conseilimmobilier",
    ]
    if not content.get("hashtags") or len(content["hashtags"]) < 5:
        log(
            f"AVERTISSEMENT : hashtags manquants ou insuffisants ({content.get('hashtags')}) "
            "-> utilisation de la liste de secours."
        )
        content["hashtags"] = DEFAULT_HASHTAGS

    hashtags_str = " ".join(f"#{h.lstrip('#')}" for h in content["hashtags"])

    # --- Étape 4 : publication Facebook ---
    log("Publication du Reel sur Facebook...")
    fb_caption = content["caption_facebook"] + "\n\n" + hashtags_str
    fb_result = publish_facebook_video(cfg["FB_PAGE_ID"], cfg["FB_PAGE_ACCESS_TOKEN"], video_url, fb_caption)
    log(f"Facebook OK : {fb_result}")

    # --- Étape 5 : publication Instagram ---
    log("Publication du Reel sur Instagram...")
    ig_caption = content["caption_instagram"] + "\n\n" + hashtags_str
    ig_result = publish_instagram_reel(cfg["IG_USER_ID"], ig_token, video_url, ig_caption)
    log(f"Instagram OK : {ig_result}")

    # --- Étape 6 : historique ---
    history.append({
        "date": datetime.now().isoformat(timespec="seconds"),
        "sujet": content["sujet"],
        "angle_type": content["angle_type"],
        "category_tag": content["category_tag"],
        "facebook_reel_video_id": fb_result.get("id"),
        "instagram_reel_media_id": ig_result.get("id"),
    })
    save_history(history)
    git_commit_and_push([os.path.basename(HISTORY_PATH)], f"Historique : {content['sujet'][:60]}")
    log("Terminé avec succès.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        log(f"ERREUR NON GÉRÉE : {exc}")
        sys.exit(1)
