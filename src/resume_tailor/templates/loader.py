from pathlib import Path

import yaml
from pydantic import BaseModel


class TemplateField(BaseModel):
    id: str
    label: str
    required: bool = True
    fields: list[str] | None = None
    max_length: int | None = None
    content_type: str | None = None  # "paragraph", "entries", "categorized_list"
    sort_order: str | None = None


class ResumeTemplate(BaseModel):
    name: str
    sections: list[TemplateField]


TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent / "templates"


def load_template(name: str) -> ResumeTemplate:
    """Load a template by name from the templates directory."""
    path = TEMPLATES_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {name}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return ResumeTemplate(**data)


def list_templates() -> list[str]:
    """List available template names."""
    return [p.stem for p in TEMPLATES_DIR.glob("*.yaml")]
