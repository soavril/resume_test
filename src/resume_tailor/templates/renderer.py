from pathlib import Path

from jinja2 import Environment, FileSystemLoader

HTML_TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent / "html_templates"


def render_to_html(markdown_content: str, title: str = "이력서") -> str:
    """Render resume markdown content to styled HTML."""
    env = Environment(loader=FileSystemLoader(str(HTML_TEMPLATES_DIR)))
    template = env.get_template("resume.html")
    return template.render(content=markdown_content, title=title)


def save_html(html_content: str, output_path: str) -> Path:
    """Save HTML content to file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_content, encoding="utf-8")
    return path
