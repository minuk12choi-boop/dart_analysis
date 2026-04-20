from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any
import zipfile
import xml.etree.ElementTree as ET


class DocumentXMLInspectionError(RuntimeError):
    """Raised when XML entry exists but XML parsing fails."""


@dataclass(slots=True)
class DocumentXMLInspector:
    def inspect(self, payload: bytes) -> dict[str, Any]:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            xml_entries = [name for name in archive.namelist() if name.lower().endswith(".xml")]
            if not xml_entries:
                return {
                    "parsing_succeeded": False,
                    "selected_entry_is_xml": False,
                    "selected_entry_name": None,
                    "root_tag": None,
                    "namespace_uri": None,
                    "top_level_child_tags": [],
                    "top_level_child_count": 0,
                    "message": "ZIP 내 XML 엔트리를 찾지 못했습니다.",
                }

            selected_entry = xml_entries[0]
            xml_bytes = archive.read(selected_entry)

        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            raise DocumentXMLInspectionError(f"XML 파싱 실패: {exc}") from exc

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
            "message": "XML 구조 메타데이터 추출에 성공했습니다.",
        }

    def _split_namespace(self, tag: str) -> tuple[str | None, str]:
        if tag.startswith("{") and "}" in tag:
            namespace, local = tag[1:].split("}", 1)
            return namespace, local
        return None, tag
