from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
import re
from typing import Any
import zipfile
import xml.etree.ElementTree as ET


class _TolerantMarkupCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.opening_tags_in_order: list[str] = []
        self.unique_tag_names: list[str] = []
        self.shallow_tag_sequence: list[str] = []
        self.tag_counts: dict[str, int] = {}
        self.heading_candidates: list[dict[str, Any]] = []
        self.heading_like_tag_names_used: list[str] = []
        self._seen: set[str] = set()
        self._stack: list[str] = []
        self._heading_capture_stack: list[dict[str, Any]] = []
        self._heading_like_tags = {"title", "cover-title", "document-name"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.opening_tags_in_order.append(tag)
        self.tag_counts[tag] = self.tag_counts.get(tag, 0) + 1
        if tag not in self._seen:
            self._seen.add(tag)
            self.unique_tag_names.append(tag)

        self._stack.append(tag)
        if len(self._stack) <= 2:
            self.shallow_tag_sequence.append(tag)
        if tag in self._heading_like_tags:
            self._heading_capture_stack.append({"tag": tag, "chunks": []})
            if tag not in self.heading_like_tag_names_used:
                self.heading_like_tag_names_used.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.opening_tags_in_order.append(tag)
        self.tag_counts[tag] = self.tag_counts.get(tag, 0) + 1
        if tag not in self._seen:
            self._seen.add(tag)
            self.unique_tag_names.append(tag)

        if len(self._stack) <= 1:
            self.shallow_tag_sequence.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._heading_capture_stack and self._heading_capture_stack[-1]["tag"] == tag:
            capture = self._heading_capture_stack.pop()
            text = self._normalize_text("".join(capture["chunks"]))
            if text:
                self.heading_candidates.append(
                    {
                        "source_tag": capture["tag"],
                        "text": text,
                        "text_length": len(text),
                    }
                )
        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._heading_capture_stack:
            self._heading_capture_stack[-1]["chunks"].append(data)

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()


class DocumentXMLInspectionError(RuntimeError):
    """Raised when XML entry exists but XML/fallback/markup parsing all fail."""

    def __init__(
        self,
        message: str,
        diagnostics: dict[str, Any],
        fallback_inspection: dict[str, Any] | None = None,
        markup_fallback_inspection: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.diagnostics = diagnostics
        self.fallback_inspection = fallback_inspection
        self.markup_fallback_inspection = markup_fallback_inspection


@dataclass(slots=True)
class DocumentXMLInspector:
    def inspect(self, payload: bytes) -> dict[str, Any]:
        selected_entry, xml_bytes = self._select_xml_entry(payload)
        if selected_entry is None or xml_bytes is None:
            return {
                "parsing_succeeded": False,
                "selected_entry_is_xml": False,
                "selected_entry_name": None,
                "root_tag": None,
                "namespace_uri": None,
                "top_level_child_tags": [],
                "top_level_child_count": 0,
                "xml_parse_diagnostics": None,
                "xml_fallback_inspection": None,
                "markup_fallback_inspection": None,
                "message": "ZIP 내 XML 엔트리를 찾지 못했습니다.",
            }

        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            diagnostics = self._build_parse_diagnostics(
                selected_entry_name=selected_entry,
                xml_bytes=xml_bytes,
                parse_error=exc,
            )
            fallback_inspection = self._attempt_fallback_inspection(
                selected_entry_name=selected_entry,
                xml_bytes=xml_bytes,
                diagnostics=diagnostics,
            )

            if fallback_inspection["fallback_parsing_succeeded"]:
                return {
                    "parsing_succeeded": False,
                    "selected_entry_is_xml": True,
                    "selected_entry_name": selected_entry,
                    "root_tag": None,
                    "namespace_uri": None,
                    "top_level_child_tags": [],
                    "top_level_child_count": 0,
                    "xml_parse_diagnostics": diagnostics,
                    "xml_fallback_inspection": fallback_inspection,
                    "markup_fallback_inspection": None,
                    "message": "엄격 XML 파싱은 실패했지만 보수적 XML fallback 검사에는 성공했습니다.",
                }

            markup_fallback_inspection = self._attempt_markup_fallback_inspection(
                selected_entry_name=selected_entry,
                xml_bytes=xml_bytes,
                diagnostics=diagnostics,
            )

            if markup_fallback_inspection["markup_fallback_succeeded"]:
                return {
                    "parsing_succeeded": False,
                    "selected_entry_is_xml": True,
                    "selected_entry_name": selected_entry,
                    "root_tag": None,
                    "namespace_uri": None,
                    "top_level_child_tags": [],
                    "top_level_child_count": 0,
                    "xml_parse_diagnostics": diagnostics,
                    "xml_fallback_inspection": fallback_inspection,
                    "markup_fallback_inspection": markup_fallback_inspection,
                    "message": "엄격 XML 파싱과 XML fallback은 실패했지만 markup 구조 fallback 검사에는 성공했습니다.",
                }

            raise DocumentXMLInspectionError(
                f"XML 파싱 실패: {exc}",
                diagnostics=diagnostics,
                fallback_inspection=fallback_inspection,
                markup_fallback_inspection=markup_fallback_inspection,
            ) from exc

        namespace_uri, root_tag = self._split_namespace(root.tag)
        top_level_child_tags = [self._split_namespace(child.tag)[1] for child in list(root)]

        return {
            "parsing_succeeded": True,
            "selected_entry_is_xml": True,
            "selected_entry_name": selected_entry,
            "root_tag": root_tag,
            "namespace_uri": namespace_uri,
            "top_level_child_tags": top_level_child_tags,
            "top_level_child_count": len(top_level_child_tags),
            "xml_parse_diagnostics": None,
            "xml_fallback_inspection": None,
            "markup_fallback_inspection": None,
            "message": "XML 구조 메타데이터 추출에 성공했습니다.",
        }

    def _select_xml_entry(self, payload: bytes) -> tuple[str | None, bytes | None]:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            xml_entries = [name for name in archive.namelist() if name.lower().endswith(".xml")]
            if not xml_entries:
                return None, None
            selected_entry = xml_entries[0]
            return selected_entry, archive.read(selected_entry)

    def _build_parse_diagnostics(
        self,
        *,
        selected_entry_name: str,
        xml_bytes: bytes,
        parse_error: ET.ParseError,
    ) -> dict[str, Any]:
        line_no, col_no = getattr(parse_error, "position", (None, None))
        declaration_text, detected_encoding_declaration = self._extract_xml_declaration(xml_bytes)
        suspicious_control_char_count = sum(
            1 for b in xml_bytes if b < 32 and b not in {9, 10, 13}
        )

        utf8_decode_error = None
        try:
            decoded_for_excerpt = xml_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            utf8_decode_error = str(exc)
            decoded_for_excerpt = xml_bytes.decode("utf-8", errors="replace")

        excerpt = self._safe_excerpt(decoded_for_excerpt, line_no=line_no, col_no=col_no)

        return {
            "selected_entry_name": selected_entry_name,
            "parser_error_message": str(parse_error),
            "parser_line": line_no,
            "parser_column": col_no,
            "xml_declaration_exists": declaration_text is not None,
            "xml_declaration_text": declaration_text,
            "detected_encoding_declaration": detected_encoding_declaration,
            "utf8_decode_error": utf8_decode_error,
            "suspicious_control_char_count": suspicious_control_char_count,
            "sanitized_excerpt": excerpt,
        }

    def _extract_xml_declaration(self, xml_bytes: bytes) -> tuple[str | None, str | None]:
        text_preview = xml_bytes[:400].decode("latin-1", errors="ignore")
        decl_match = re.search(r"<\?xml[^>]*\?>", text_preview, flags=re.IGNORECASE)
        if decl_match is None:
            return None, None

        declaration_text = decl_match.group(0)
        enc_match = re.search(r"encoding\s*=\s*['\"]([^'\"]+)['\"]", declaration_text, flags=re.IGNORECASE)
        return declaration_text, enc_match.group(1) if enc_match else None

    def _attempt_fallback_inspection(
        self,
        *,
        selected_entry_name: str,
        xml_bytes: bytes,
        diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        line_no = diagnostics.get("parser_line")
        col_no = diagnostics.get("parser_column")
        declaration_text = diagnostics.get("xml_declaration_text")
        encoding_declaration = diagnostics.get("detected_encoding_declaration")

        decoded_text = xml_bytes.decode("utf-8", errors="replace")
        raw_excerpt = self._safe_excerpt(decoded_text, line_no=line_no, col_no=col_no)

        # XML 1.0에서 허용되지 않는 제어문자(U+0000~U+001F 중 TAB/LF/CR 제외)만 공백으로 치환
        invalid_control_char_pattern = r"[\x00-\x08\x0B\x0C\x0E-\x1F]"
        sanitized_text, removed_control_char_count = re.subn(
            invalid_control_char_pattern,
            " ",
            decoded_text,
        )

        sanitization_applied = removed_control_char_count > 0
        rules_applied: list[dict[str, Any]] = []
        if sanitization_applied:
            rules_applied.append(
                {
                    "rule_id": "replace_invalid_xml_control_chars",
                    "description": "XML 1.0 비허용 제어문자(U+0000~U+001F 중 TAB/LF/CR 제외)를 공백으로 치환",
                    "replacements": removed_control_char_count,
                }
            )

        result: dict[str, Any] = {
            "selected_entry_name": selected_entry_name,
            "fallback_attempted": True,
            "fallback_strategy": "strict_parse_failure_then_minimal_sanitization_retry",
            "xml_declaration_text": declaration_text,
            "detected_encoding_declaration": encoding_declaration,
            "raw_excerpt_near_error": raw_excerpt,
            "sanitization_applied": sanitization_applied,
            "sanitization_rules_applied": rules_applied,
            "fallback_parsing_succeeded": False,
            "fallback_error_message": None,
            "root_tag": None,
            "namespace_uri": None,
            "top_level_child_tags": [],
            "top_level_child_count": 0,
        }

        if not sanitization_applied:
            result["fallback_error_message"] = "적용 가능한 최소 sanitize 규칙이 없어 fallback 재파싱을 수행하지 않았습니다."
            return result

        try:
            fallback_root = ET.fromstring(sanitized_text)
        except ET.ParseError as fallback_exc:
            result["fallback_error_message"] = str(fallback_exc)
            return result

        namespace_uri, root_tag = self._split_namespace(fallback_root.tag)
        top_level_child_tags = [self._split_namespace(child.tag)[1] for child in list(fallback_root)]

        result["fallback_parsing_succeeded"] = True
        result["root_tag"] = root_tag
        result["namespace_uri"] = namespace_uri
        result["top_level_child_tags"] = top_level_child_tags
        result["top_level_child_count"] = len(top_level_child_tags)
        return result

    def _attempt_markup_fallback_inspection(
        self,
        *,
        selected_entry_name: str,
        xml_bytes: bytes,
        diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        line_no = diagnostics.get("parser_line")
        col_no = diagnostics.get("parser_column")
        decoded_text = xml_bytes.decode("utf-8", errors="replace")
        raw_excerpt = self._safe_excerpt(decoded_text, line_no=line_no, col_no=col_no)

        max_tags = 30
        collector = _TolerantMarkupCollector()
        try:
            collector.feed(decoded_text)
            collector.close()
        except Exception as exc:
            return {
                "selected_entry_name": selected_entry_name,
                "markup_fallback_attempted": True,
                "markup_fallback_succeeded": False,
                "parser_mode": "html.parser.HTMLParser",
                "document_appears_markup_like": False,
                "first_unique_tag_names": [],
                "first_opening_tags": [],
                "shallow_tag_sequence": [],
                "tag_counts": {},
                "heading_like_tag_names_used": [],
                "heading_candidates": [],
                "raw_excerpt_near_error": raw_excerpt,
                "markup_fallback_error_message": str(exc),
            }

        first_opening_tags = collector.opening_tags_in_order[:max_tags]
        first_unique_tag_names = collector.unique_tag_names[:max_tags]
        shallow_tag_sequence = collector.shallow_tag_sequence[:max_tags]
        appears_markup_like = len(first_opening_tags) > 0

        if not appears_markup_like:
            return {
                "selected_entry_name": selected_entry_name,
                "markup_fallback_attempted": True,
                "markup_fallback_succeeded": False,
                "parser_mode": "html.parser.HTMLParser",
                "document_appears_markup_like": False,
                "first_unique_tag_names": [],
                "first_opening_tags": [],
                "shallow_tag_sequence": [],
                "tag_counts": {},
                "heading_like_tag_names_used": [],
                "heading_candidates": [],
                "raw_excerpt_near_error": raw_excerpt,
                "markup_fallback_error_message": "문서가 markup 형태로 보이지 않아 구조 fallback을 확정할 수 없습니다.",
            }

        return {
            "selected_entry_name": selected_entry_name,
            "markup_fallback_attempted": True,
            "markup_fallback_succeeded": True,
            "parser_mode": "html.parser.HTMLParser",
            "document_appears_markup_like": True,
            "first_unique_tag_names": first_unique_tag_names,
            "first_opening_tags": first_opening_tags,
            "shallow_tag_sequence": shallow_tag_sequence,
            "tag_counts": collector.tag_counts,
            "heading_like_tag_names_used": collector.heading_like_tag_names_used,
            "heading_candidates": collector.heading_candidates[:30],
            "raw_excerpt_near_error": raw_excerpt,
            "markup_fallback_error_message": None,
        }

    def _safe_excerpt(self, text: str, *, line_no: int | None, col_no: int | None) -> str:
        if line_no is None or col_no is None:
            target_index = min(len(text), 120)
        else:
            lines = text.splitlines(keepends=True)
            if line_no <= 0 or line_no > len(lines):
                target_index = min(len(text), 120)
            else:
                target_index = sum(len(lines[i]) for i in range(line_no - 1)) + max(0, col_no)

        start = max(0, target_index - 80)
        end = min(len(text), target_index + 80)
        excerpt = text[start:end]

        sanitized = "".join(
            ch if ch in {"\n", "\t"} or ord(ch) >= 32 else " "
            for ch in excerpt
        )
        return sanitized

    def _split_namespace(self, tag: str) -> tuple[str | None, str]:
        if tag.startswith("{") and "}" in tag:
            namespace, local = tag[1:].split("}", 1)
            return namespace, local
        return None, tag
