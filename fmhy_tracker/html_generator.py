"""HTML generation module for FMHY Tracker."""

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from rcssmin import cssmin
from rjsmin import jsmin

from .storage import atomic_write_text

logger = logging.getLogger(__name__)


class HTMLGenerator:
    """Generates HTML output from FMHY tracker data."""

    def __init__(self, template_dir: str = None, static_dir: str = None):
        """Initialize the HTML generator.

        Args:
            template_dir: Path to templates directory
            static_dir: Path to static files directory
        """
        base_path = Path(__file__).parent.parent
        self.template_dir = (
            Path(template_dir) if template_dir else base_path / "templates"
        )
        self.static_dir = Path(static_dir) if static_dir else base_path / "static"

    def _read_file(self, filepath: Path) -> str:
        """Read a file and return its contents.

        Args:
            filepath: Path to the file

        Returns:
            File contents as string
        """
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()

    def _get_css_content(self) -> str:
        """Get CSS content from static files.

        Returns:
            CSS content as string
        """
        css_path = self.static_dir / "styles.css"
        if css_path.exists():
            return self._read_file(css_path)
        return ""

    def _get_js_content(self) -> str:
        """Get JavaScript content from static files.

        Returns:
            JavaScript content as string
        """
        js_path = self.static_dir / "app.js"
        if js_path.exists():
            return self._read_file(js_path)
        return ""

    def _get_template(self) -> str:
        """Get HTML template content.

        Returns:
            Template content as string
        """
        template_path = self.template_dir / "index.html"
        if template_path.exists():
            return self._read_file(template_path)
        raise FileNotFoundError(f"Template not found: {template_path}")

    def _to_safe_script_json(self, data: dict) -> str:
        """Serialize JSON so it can be safely embedded in a script tag."""
        return (
            json.dumps(data, indent=2, ensure_ascii=False)
            .replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
        )

    def generate(
        self, data: dict, output_file: str = "index.html", monthly_file: str = None
    ) -> None:
        """Generate HTML file from data.

        Args:
            data: Dictionary containing tracker data
            output_file: Path to output HTML file
            monthly_file: Available archive; defaults to beside the output HTML
        """
        try:
            # Get template and static content
            template = self._get_template()
            css_content = self._get_css_content()
            js_content = self._get_js_content()

            # Content hashes let browsers reuse unchanged assets across data updates.
            output_path = Path(output_file)
            asset_urls = {}
            if "{{ css_url }}" in template or "{{ js_url }}" in template:
                asset_dir = output_path.parent / "static" / "dist"
                asset_dir.mkdir(parents=True, exist_ok=True)
                for name, extension, content in (
                    ("styles", "css", cssmin(css_content)),
                    ("app", "js", jsmin(js_content)),
                ):
                    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
                    filename = f"{name}.{digest}.{extension}"
                    atomic_write_text(asset_dir / filename, content)
                    asset_urls[extension] = f"static/dist/{filename}"

            # Embed only archive metadata so the label is useful before download.
            data = dict(data)
            data.pop("archiveMonth", None)
            archive = (
                Path(monthly_file)
                if monthly_file
                else output_path.parent / "monthly_commits.json"
            )
            if archive.is_file():
                try:
                    month = json.loads(archive.read_text(encoding="utf-8")).get("month")
                    if (
                        isinstance(month, str)
                        and datetime.strptime(month, "%Y-%m").strftime("%Y-%m") == month
                    ):
                        data["archiveMonth"] = month
                except (OSError, ValueError, AttributeError):
                    logger.warning("Could not read archive month from %s", archive)

            # Add build time to data
            data["buildTime"] = datetime.now(timezone.utc).isoformat()

            # Convert data to JSON that cannot break out of the data script.
            data_json = self._to_safe_script_json(data)

            # Replace placeholders in template
            html_content = template.replace("{{ css_content }}", css_content)
            html_content = html_content.replace("{{ js_content }}", js_content)
            html_content = html_content.replace("{{ data_json }}", data_json)
            for extension, url in asset_urls.items():
                html_content = html_content.replace("{{ " + extension + "_url }}", url)

            # Write output file
            atomic_write_text(output_path, html_content)

            if asset_urls:
                current_assets = {Path(url).name for url in asset_urls.values()}
                generated_asset = re.compile(
                    r"(?:styles|app)\.[a-f0-9]{16}\.(?:css|js)\Z"
                )
                for asset_path in asset_dir.iterdir():
                    if (
                        generated_asset.fullmatch(asset_path.name)
                        and asset_path.name not in current_assets
                    ):
                        asset_path.unlink()

            logger.info("HTML file generated successfully: %s", output_file)

        except Exception as e:
            logger.error("Error generating HTML file: %s", e)
            raise
