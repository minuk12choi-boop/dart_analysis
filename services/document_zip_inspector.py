from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
from typing import Any
import zipfile


class DocumentZipInspectionError(RuntimeError):
    """Raised when original document payload is not a valid ZIP archive."""


@dataclass(slots=True)
class DocumentZipInspector:
    def inspect(self, payload: bytes) -> dict[str, Any]:
        if not payload:
            raise DocumentZipInspectionError("원문 payload가 비어 있습니다.")

        try:
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                entries = []
                for info in archive.infolist():
                    entries.append(
                        {
                            "name": info.filename,
                            "compressed_size": info.compress_size,
                            "uncompressed_size": info.file_size,
                            "file_type_hint": self._file_type_hint(info.filename),
                        }
                    )
        except zipfile.BadZipFile as exc:
            raise DocumentZipInspectionError("원문 payload가 유효한 ZIP 형식이 아닙니다.") from exc

        return {
            "is_zip": True,
            "entry_count": len(entries),
            "entries": entries,
        }

    def _file_type_hint(self, filename: str) -> str:
        _, ext = os.path.splitext(filename.lower())
        if ext in {".xml", ".xbrl"}:
            return "structured_document"
        if ext in {".htm", ".html"}:
            return "html_document"
        if ext in {".txt"}:
            return "text_document"
        if ext in {".pdf"}:
            return "pdf_document"
        if ext in {".jpg", ".jpeg", ".png", ".gif"}:
            return "image"
        return "unknown"
