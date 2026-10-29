"""Sistema de habilidades (skills) plugáveis.

Uma skill é uma ferramenta assíncrona, sem estado de conversa, que um agente pode invocar:
scrapers, geradores de JSON-LD, validadores, conectores de API financeira etc.

Registro dinâmico:
  * todas as skills em `app/skills/builtin/` são descobertas automaticamente;
  * módulos extras podem ser injetados via env `EXTRA_SKILL_MODULES=meu_pacote.skills,outro.mod`
    ou colocando arquivos `.py` em `./plugins/` (útil para novos nichos sem tocar no core).

Para criar uma skill: herde de `Skill`, defina `name`, `description` e implemente `run(**kwargs)`.
"""

from __future__ import annotations

import abc
import importlib
import importlib.util
import inspect
import logging
import os
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.core.office import Office

log = logging.getLogger(__name__)


class SkillError(Exception):
    pass


class Skill(abc.ABC):
    name: str = ""
    description: str = ""
    # Setores que podem usar a skill por padrão ("*" = todos)
    sectors: tuple[str, ...] = ("*",)

    def __init__(self, office: Office | None = None) -> None:
        self.office = office

    @abc.abstractmethod
    async def run(self, **kwargs: Any) -> dict[str, Any]: ...

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "sectors": list(self.sectors)}


class SkillRegistry:
    def __init__(self, office: Office | None = None) -> None:
        self.office = office
        self._skills: dict[str, Skill] = {}

    def register(self, skill_cls: type[Skill]) -> None:
        if not skill_cls.name:
            raise SkillError(f"{skill_cls.__name__} sem atributo name")
        self._skills[skill_cls.name] = skill_cls(self.office)
        log.debug("skill registrada: %s", skill_cls.name)

    def _register_module(self, module: Any) -> None:
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Skill) and obj is not Skill and not inspect.isabstract(obj) and obj.__module__ == module.__name__:
                self.register(obj)

    def discover(self, plugins_dir: str | Path = "plugins") -> SkillRegistry:
        from app.skills import builtin

        for info in pkgutil.iter_modules(builtin.__path__):
            self._register_module(importlib.import_module(f"{builtin.__name__}.{info.name}"))

        for mod_name in filter(None, (m.strip() for m in os.getenv("EXTRA_SKILL_MODULES", "").split(","))):
            try:
                self._register_module(importlib.import_module(mod_name))
            except Exception:
                log.exception("falha ao carregar módulo de skill %s", mod_name)

        pdir = Path(plugins_dir)
        if pdir.is_dir():
            for path in sorted(pdir.glob("*.py")):
                spec = importlib.util.spec_from_file_location(f"plugins.{path.stem}", path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    try:
                        spec.loader.exec_module(module)
                        self._register_module(module)
                    except Exception:
                        log.exception("falha ao carregar plugin %s", path)
        return self

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError as e:
            raise SkillError(f"skill não registrada: {name}") from e

    def for_sector(self, sector: str) -> list[Skill]:
        return [s for s in self._skills.values() if "*" in s.sectors or sector in s.sectors]

    def names(self) -> list[str]:
        return sorted(self._skills)

    def catalog(self) -> list[dict[str, Any]]:
        return [s.describe() for s in sorted(self._skills.values(), key=lambda s: s.name)]
