"""
Skill Loader — Sistema dinámico de skills via archivos Markdown.

Cualquier persona puede agregar skills a TokioAI simplemente creando un
archivo .md en la carpeta `skills/`.

Formato del archivo .md:
─────────────────────────────────────────────
# Nombre del Skill

## Descripción
Texto libre explicando qué hace este skill.

## Parámetros
- param1 (requerido): Descripción del parámetro
- param2 (opcional, default: "algo"): Descripción

## Categoría
Nombre de la categoría (ej: Calendar, Productivity, Security)

## Herramientas
tool1, tool2, tool3

## Instrucciones
Instrucciones paso a paso que TokioAI debe seguir al ejecutar este skill.
Pueden incluir ejemplos, reglas, y cualquier contexto necesario.

## Ejemplos
- "hacer X" → ejecutar Y
- "consultar Z" → usar herramienta W
─────────────────────────────────────────────

El SkillLoader:
1. Escanea la carpeta skills/ al iniciar
2. Parsea cada .md extrayendo metadata
3. Registra cada skill como herramienta disponible
4. Inyecta las instrucciones en el contexto del LLM

Así, agregar un skill nuevo es tan simple como crear un .md.
"""
import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class SkillDefinition:
    """Represents a parsed skill from a .md file."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: List[Dict[str, str]],
        category: str,
        tools_used: List[str],
        instructions: str,
        examples: str,
        file_path: str,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.category = category
        self.tools_used = tools_used
        self.instructions = instructions
        self.examples = examples
        self.file_path = file_path

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "category": self.category,
            "tools_used": self.tools_used,
            "instructions": self.instructions,
            "examples": self.examples,
            "file": self.file_path,
        }


# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------

def _extract_section(md_text: str, heading: str) -> str:
    """Extract content under a ## heading until the next ## heading or EOF."""
    pattern = rf"##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##\s|\Z)"
    match = re.search(pattern, md_text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _extract_title(md_text: str) -> str:
    """Extract the top-level # title."""
    match = re.search(r"^#\s+(.+)$", md_text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _parse_params(section: str) -> List[Dict[str, str]]:
    """Parse parameter list from Markdown list items."""
    params = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        line = line.lstrip("- ").strip()

        # Format: param_name (required|optional, default: X): Description
        match = re.match(
            r"(\w+)\s*\(([^)]*)\)\s*:\s*(.*)",
            line,
        )
        if match:
            name = match.group(1)
            meta = match.group(2).lower()
            desc = match.group(3).strip()
            required = "required" in meta or "requerido" in meta
            default = None
            dm = re.search(r"default:\s*[\"']?([^\"']*)[\"']?", meta)
            if dm:
                default = dm.group(1).strip()
            params.append({
                "name": name,
                "required": required,
                "default": default,
                "description": desc,
            })
        else:
            # Simple format: param_name: description
            match2 = re.match(r"(\w+)\s*:\s*(.*)", line)
            if match2:
                params.append({
                    "name": match2.group(1),
                    "required": False,
                    "default": None,
                    "description": match2.group(2).strip(),
                })
    return params


def parse_skill_md(md_text: str, file_path: str) -> Optional[SkillDefinition]:
    """Parse a complete skill .md file into a SkillDefinition."""
    title = _extract_title(md_text)
    if not title:
        logger.warning(f"Skill file {file_path} has no # title, skipping")
        return None

    description = _extract_section(md_text, "Descripción") or _extract_section(md_text, "Description")
    params_raw = _extract_section(md_text, "Parámetros") or _extract_section(md_text, "Parameters")
    category = (_extract_section(md_text, "Categoría") or _extract_section(md_text, "Category") or "Skills").strip()
    tools_raw = _extract_section(md_text, "Herramientas") or _extract_section(md_text, "Tools")
    instructions = _extract_section(md_text, "Instrucciones") or _extract_section(md_text, "Instructions")
    examples = _extract_section(md_text, "Ejemplos") or _extract_section(md_text, "Examples")

    # Derive a slug name from the title
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")

    parameters = _parse_params(params_raw)
    tools_used = [t.strip() for t in tools_raw.split(",") if t.strip()] if tools_raw else []

    return SkillDefinition(
        name=slug,
        description=description or title,
        parameters=parameters,
        category=category,
        tools_used=tools_used,
        instructions=instructions,
        examples=examples,
        file_path=file_path,
    )


# ---------------------------------------------------------------------------
# Skill Loader
# ---------------------------------------------------------------------------

class SkillLoader:
    """Loads and manages Markdown-defined skills."""

    # Default search paths for skills
    DEFAULT_DIRS = [
        "skills",            # relative to workspace
        "tokio-cli/skills",  # relative to project root
    ]

    def __init__(self, base_dirs: Optional[List[str]] = None):
        self.base_dirs = base_dirs or []
        self.skills: Dict[str, SkillDefinition] = {}
        self._loaded = False

    def add_search_path(self, path: str):
        """Add an additional directory to search for skill .md files."""
        if path not in self.base_dirs:
            self.base_dirs.append(path)

    def load_all(self) -> int:
        """
        Scan all skill directories and load every .md file as a skill.
        Returns the number of skills loaded.
        """
        self.skills.clear()
        count = 0

        for base_dir in self.base_dirs:
            base = Path(base_dir)
            if not base.is_dir():
                continue

            for md_file in sorted(base.glob("*.md")):
                # Skip files starting with _ (templates, drafts)
                if md_file.name.startswith("_"):
                    continue
                try:
                    text = md_file.read_text(encoding="utf-8", errors="replace")
                    skill = parse_skill_md(text, str(md_file))
                    if skill:
                        self.skills[skill.name] = skill
                        count += 1
                        logger.info(f"✅ Skill cargado: {skill.name} ({skill.category}) desde {md_file.name}")
                except Exception as e:
                    logger.warning(f"⚠️ Error cargando skill {md_file}: {e}")

        self._loaded = True
        logger.info(f"📦 {count} skills cargados desde archivos .md")
        return count

    def get_skill(self, name: str) -> Optional[SkillDefinition]:
        """Get a skill by slug name."""
        return self.skills.get(name)

    def list_skills(self) -> List[Dict[str, Any]]:
        """List all loaded skills as dicts."""
        return [s.to_dict() for s in self.skills.values()]

    def build_skills_context(self) -> str:
        """
        Build a context block describing all loaded skills.
        This is injected into the LLM system prompt so TokioAI
        knows how to use each skill.
        """
        if not self.skills:
            return ""

        parts = [
            "# SKILLS DINÁMICOS (cargados desde archivos .md)\n",
            f"Tenés {len(self.skills)} skills extra disponibles:\n",
        ]

        for skill in self.skills.values():
            parts.append(f"## Skill: {skill.name}")
            parts.append(f"**Categoría**: {skill.category}")
            parts.append(f"**Descripción**: {skill.description}")

            if skill.parameters:
                param_lines = []
                for p in skill.parameters:
                    req = "(requerido)" if p.get("required") else "(opcional)"
                    default = f" [default: {p['default']}]" if p.get("default") else ""
                    param_lines.append(f"  - `{p['name']}` {req}{default}: {p.get('description', '')}")
                parts.append("**Parámetros**:")
                parts.extend(param_lines)

            if skill.tools_used:
                parts.append(f"**Herramientas que usa**: {', '.join(skill.tools_used)}")

            if skill.instructions:
                parts.append(f"**Instrucciones**:\n{skill.instructions}")

            if skill.examples:
                parts.append(f"**Ejemplos**:\n{skill.examples}")

            parts.append("")  # blank line separator

        parts.append(
            "Para ejecutar un skill, usá las herramientas listadas en cada skill "
            "siguiendo sus instrucciones. No necesitás una herramienta especial — "
            "el skill describe *cómo* usar herramientas existentes para lograr algo."
        )

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_global_loader: Optional[SkillLoader] = None


def get_skill_loader() -> SkillLoader:
    """Get or create the global skill loader instance."""
    global _global_loader
    if _global_loader is None:
        _global_loader = SkillLoader()
    return _global_loader


def init_skills(extra_dirs: Optional[List[str]] = None) -> int:
    """
    Initialize the skill system. Call once at startup.

    Args:
        extra_dirs: Additional directories to scan for .md skill files.

    Returns:
        Number of skills loaded.
    """
    loader = get_skill_loader()

    # Add default paths
    for d in SkillLoader.DEFAULT_DIRS:
        loader.add_search_path(d)

    # Add extra dirs
    if extra_dirs:
        for d in extra_dirs:
            loader.add_search_path(d)

    return loader.load_all()
