from dataclasses import dataclass
from re import sub


@dataclass(frozen=True)
class ConstructionProject:
    number: str
    code: str
    name: str
    aliases: tuple[str, ...]


# MVP stand-in for the partner-app lookup. Later this should call the
# central project source instead of keeping aliases in code.
PROJECTS = (
    ConstructionProject(
        number="25-00008",
        code="Wewe20",
        name="Weseler Weg 20",
        aliases=("Weseler Weg 20, 22045 Hamburg", "Weseler Weg 20"),
    ),
    ConstructionProject(
        number="2026-00007",
        code="Hk92",
        name="Heukoppel 92",
        aliases=("Heukoppel 92, 22179 Hamburg", "Heukoppel 92"),
    ),
)


def find_project_by_address(delivery_address: str | None) -> ConstructionProject | None:
    if not delivery_address:
        return None

    normalized_address = _normalize(delivery_address)
    for project in PROJECTS:
        if any(_normalize(alias) in normalized_address for alias in project.aliases):
            return project
    return None


def _normalize(value: str) -> str:
    return sub(r"\s+", " ", value).strip().casefold()
