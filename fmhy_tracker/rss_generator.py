"""RSS feed generation module for FMHY Tracker."""

import html
import logging
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime, timezone
from email.utils import formatdate
from typing import Dict
from urllib.parse import quote, urljoin, urlparse
from pathlib import Path

from .config import config
from .storage import atomic_write_text

logger = logging.getLogger(__name__)


class RSSGenerator:
    """Generates RSS 2.0 feed from FMHY tracker data."""

    def __init__(self, repo: str = None, runtime_config=None):
        """Initialize the RSS generator."""
        self.config = runtime_config or config
        self.title = self.config.rss_title
        self.link = self.config.rss_link
        self.description = self.config.rss_description
        self.repo = repo or self.config.repo

    def _escape_html(self, value: str) -> str:
        """Escape text for safe use in RSS HTML descriptions."""
        return html.escape(str(value or ""), quote=True)

    def _sanitize_url(self, url: str) -> str:
        """Allow only URL schemes that are safe in feed-reader HTML."""
        raw_url = str(url or "").strip()
        parsed = urlparse(raw_url)
        if parsed.scheme in {"http", "https", "mailto"}:
            return raw_url
        return ""

    def _render_bold_text(self, text: str) -> str:
        """Escape text and preserve simple markdown bold markup."""
        escaped_text = self._escape_html(text)
        return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped_text)

    def _format_rfc822_date(self, iso_date: str) -> str | None:
        """Convert ISO 8601 date string to RFC 822 format.

        Args:
            iso_date: ISO 8601 formatted date string

        Returns:
            RFC 822 formatted date string
        """
        try:
            # Parse ISO 8601 date
            if iso_date.endswith("Z"):
                iso_date = iso_date[:-1] + "+00:00"
            dt = datetime.fromisoformat(iso_date)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            # Convert to timestamp and format as RFC 822
            return formatdate(dt.timestamp(), usegmt=True)
        except (ValueError, AttributeError, OverflowError, OSError):
            return None

    def _extract_link_text(self, markdown_link: str) -> str:
        """Extract clean text from markdown link.

        Args:
            markdown_link: Markdown formatted link string

        Returns:
            Clean text without markdown formatting
        """
        # Remove leading "* " or "* ⭐ "
        text = markdown_link.strip()
        text = re.sub(r"^\*\s*", "", text)
        text = re.sub(r"^⭐\s*", "", text)

        # Remove bold formatting **text**
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)

        # Extract text from markdown links [text](url) -> text
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

        # Clean up extra whitespace
        text = " ".join(text.split())

        return text

    def _convert_markdown_to_html(self, markdown_link: str) -> str:
        """Convert markdown link to HTML with clickable links.

        Args:
            markdown_link: Markdown formatted link string

        Returns:
            HTML formatted string with clickable anchor tags
        """
        text = markdown_link.strip()
        text = re.sub(r"^\*\s*", "", text)
        text = " ".join(text.split())

        html_parts = []
        last_index = 0
        link_pattern = re.compile(r"(\*\*)?\[([^\]]+)\]\(([^)]+)\)(\*\*)?")
        for match in link_pattern.finditer(text):
            html_parts.append(self._render_bold_text(text[last_index : match.start()]))
            label_text = (
                f"**{match.group(2)}**"
                if match.group(1) and match.group(4)
                else match.group(2)
            )
            label = self._render_bold_text(label_text)
            url = self._sanitize_url(match.group(3))
            if url:
                html_parts.append(f'<a href="{self._escape_html(url)}">{label}</a>')
            else:
                html_parts.append(label)
            last_index = match.end()

        html_parts.append(self._render_bold_text(text[last_index:]))
        return "".join(html_parts)

    def _generate_item_title(self, commit: Dict) -> str:
        """Generate RSS item title from commit data.

        Args:
            commit: Commit data dictionary

        Returns:
            Formatted title string like "x added, x updated, x removed"
        """
        added = commit.get("added", [])
        removed = commit.get("removed", [])

        # Count new and updated links separately
        new_count = sum(1 for item in added if item.get("type", "new") == "new")
        updated_count = sum(1 for item in added if item.get("type") == "updated")
        removed_count = len(removed)

        # Build title parts
        parts = []
        if new_count > 0:
            parts.append(f"{new_count} added")
        if updated_count > 0:
            parts.append(f"{updated_count} updated")
        if removed_count > 0:
            parts.append(f"{removed_count} removed")

        if not parts:
            return "No changes"

        return ", ".join(parts)

    def _generate_item_description(self, commit: Dict) -> str:
        """Generate HTML description for RSS item.

        Args:
            commit: Commit data dictionary

        Returns:
            HTML formatted description string
        """
        sha = commit.get("sha", "")
        message = commit.get("message", "")
        added = commit.get("added", [])
        removed = commit.get("removed", [])

        # Separate new and updated links
        new_links = [item for item in added if item.get("type", "new") == "new"]
        updated_links = [item for item in added if item.get("type") == "updated"]

        # Build HTML content
        html_parts = []

        # Commit info
        html_parts.append(
            f"<p><strong>Commit:</strong> {self._escape_html(message)}</p>"
        )
        commit_url = f"https://github.com/{self.repo}/commit/{quote(sha, safe='')}"
        html_parts.append(
            f'<p><strong>SHA:</strong> <a href="{self._escape_html(commit_url)}">{self._escape_html(sha[:8])}</a></p>'
        )

        # Added links section (new links only)
        if new_links:
            html_parts.append(f"<h3>Added Links ({len(new_links)})</h3>")
            html_parts.append("<ul>")
            for item in new_links:
                source = item.get("source", "unknown")
                link_html = self._convert_markdown_to_html(item.get("link", ""))
                html_parts.append(f"<li>[{self._escape_html(source)}] {link_html}</li>")
            html_parts.append("</ul>")

        # Updated links section
        if updated_links:
            html_parts.append(f"<h3>Updated Links ({len(updated_links)})</h3>")
            html_parts.append("<ul>")
            for item in updated_links:
                source = item.get("source", "unknown")
                link_html = self._convert_markdown_to_html(item.get("link", ""))
                previous = item.get("relatedLink")
                changes = ""
                if previous:
                    before_html = self._convert_markdown_to_html(previous)
                    changes = (
                        f"<br/><strong>Before:</strong> {before_html}"
                        f"<br/><strong>After:</strong> {link_html}"
                    )
                html_parts.append(
                    f"<li>[{self._escape_html(source)}] {link_html}{changes}</li>"
                )
            html_parts.append("</ul>")

        # Removed links section
        if removed:
            html_parts.append(f"<h3>Removed Links ({len(removed)})</h3>")
            html_parts.append("<ul>")
            for item in removed:
                source = item.get("source", "unknown")
                link_html = self._convert_markdown_to_html(item.get("link", ""))
                html_parts.append(f"<li>[{self._escape_html(source)}] {link_html}</li>")
            html_parts.append("</ul>")

        # Handle empty commits
        if not new_links and not updated_links and not removed:
            html_parts.append("<p>No link changes in this commit.</p>")

        return "\n".join(html_parts)

    def _create_cdata(self, text: str) -> str:
        """Wrap text in CDATA section.

        Args:
            text: Text to wrap

        Returns:
            CDATA wrapped string
        """
        return f"<![CDATA[{text}]]>"

    def generate(self, data: Dict, output_file: str = "feed.xml") -> None:
        """Generate RSS feed from tracker data.

        Args:
            data: Dictionary containing tracker data
            output_file: Path to output RSS file
        """
        try:
            # Create root RSS element
            rss = ET.Element("rss", version="2.0")
            channel = ET.SubElement(rss, "channel")

            # Add channel metadata
            title_elem = ET.SubElement(channel, "title")
            title_elem.text = self.title

            link_elem = ET.SubElement(channel, "link")
            link_elem.text = self.link

            desc_elem = ET.SubElement(channel, "description")
            desc_elem.text = self.description

            atom_namespace = "http://www.w3.org/2005/Atom"
            ET.register_namespace("atom", atom_namespace)
            ET.SubElement(
                channel,
                f"{{{atom_namespace}}}link",
                href=urljoin(
                    self.link.rstrip("/") + "/", Path(self.config.rss_file).name
                ),
                rel="self",
                type="application/rss+xml",
            )

            # Last build date
            last_updated = data.get(
                "lastUpdated",
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            )
            build_date_elem = ET.SubElement(channel, "lastBuildDate")
            build_date_elem.text = self._format_rfc822_date(last_updated) or formatdate(
                usegmt=True
            )

            # Generator
            generator_elem = ET.SubElement(channel, "generator")
            generator_elem.text = "FMHY Tracker"

            # Language
            language_elem = ET.SubElement(channel, "language")
            language_elem.text = "en-us"

            # Add items for each commit
            commits = data.get("commits", [])

            def commit_timestamp(commit):
                try:
                    date = datetime.fromisoformat(
                        commit.get("date", "").replace("Z", "+00:00")
                    )
                    return (
                        date.replace(tzinfo=timezone.utc).timestamp()
                        if date.tzinfo is None
                        else date.timestamp()
                    )
                except (ValueError, TypeError, AttributeError):
                    return float("-inf")

            for commit in sorted(commits, key=commit_timestamp, reverse=True):
                item = ET.SubElement(channel, "item")

                # Title
                item_title = ET.SubElement(item, "title")
                item_title.text = self._generate_item_title(commit)

                # GUID (GitHub commit URL for uniqueness)
                sha = commit.get("sha", "")
                guid_url = (
                    f"https://github.com/{self.repo}/commit/{quote(sha, safe='')}"
                )
                item_guid = ET.SubElement(item, "guid", isPermaLink="true")
                item_guid.text = guid_url
                ET.SubElement(item, "link").text = guid_url

                # Publication date
                pub_date = commit.get("date", "")
                if pub_date:
                    formatted_date = self._format_rfc822_date(pub_date)
                    if formatted_date:
                        item_pubdate = ET.SubElement(item, "pubDate")
                        item_pubdate.text = formatted_date

                # Description (HTML in CDATA)
                description_html = self._generate_item_description(commit)
                item_desc = ET.SubElement(item, "description")
                item_desc.text = description_html

            # Generate XML string with proper formatting
            xml_string = self._generate_xml_string(rss)

            # Write to file
            atomic_write_text(Path(output_file), xml_string)

            logger.info("RSS feed generated successfully: %s", output_file)

        except Exception as e:
            logger.error("Error generating RSS feed: %s", e)
            raise

    def _generate_xml_string(self, root: ET.Element) -> str:
        """Generate a pretty-printed XML string with CDATA descriptions.

        Args:
            root: Root XML element

        Returns:
            Formatted XML string
        """
        for element in root.iter():
            if element.text is not None:
                element.text = self._remove_invalid_xml_chars(element.text)
            if element.tail is not None:
                element.tail = self._remove_invalid_xml_chars(element.tail)
            for name, value in element.attrib.items():
                element.attrib[name] = self._remove_invalid_xml_chars(value)

        document = minidom.parseString(ET.tostring(root, encoding="utf-8"))
        # Use XML nodes rather than string replacements: HTML entities must remain
        # escaped exactly once inside reader HTML, including quotes in attributes.
        for description in document.getElementsByTagName("description"):
            text = "".join(node.data for node in description.childNodes)
            for node in list(description.childNodes):
                description.removeChild(node)
            parts = text.split("]]>")
            for index, part in enumerate(parts):
                if index:
                    part = ">" + part
                if index < len(parts) - 1:
                    part += "]]"
                description.appendChild(document.createCDATASection(part))
        return document.toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")

    @staticmethod
    def _remove_invalid_xml_chars(value: str) -> str:
        """Remove characters forbidden by XML 1.0 while preserving valid Unicode."""
        return "".join(
            char
            for char in value
            if ord(char) in {0x9, 0xA, 0xD}
            or 0x20 <= ord(char) <= 0xD7FF
            or 0xE000 <= ord(char) <= 0xFFFD
            or 0x10000 <= ord(char) <= 0x10FFFF
        )
