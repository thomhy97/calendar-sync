from jinja2 import FileSystemLoader, Environment
from starlette.templating import Jinja2Templates

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def date_fr(dt) -> str:
    return f"{JOURS[dt.weekday()]} {dt.day:02d} {MOIS[dt.month - 1]} {dt.year}"


def time_fr(dt) -> str:
    return dt.strftime("%H:%M")


# cache_size=0 contourne un bug Python 3.14 / Jinja2 (tuple unhashable dans LRUCache)
_env = Environment(loader=FileSystemLoader("app/templates"), cache_size=0)
_env.filters["date_fr"] = date_fr
_env.filters["time_fr"] = time_fr
templates = Jinja2Templates(env=_env)
