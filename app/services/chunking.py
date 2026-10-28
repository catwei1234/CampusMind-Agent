from __future__ import annotations

from dataclasses import dataclass
import re


HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True)
class Chunk:
    content: str
    heading_path: str = ""


def chunk_plain_text(content: str, size: int, overlap: int) -> list[str]:
    text = re.sub(r"\s+", " ", content or "").strip()
    if not text:
        return []
    chunks = []
    start = 0
    step = max(1, size - overlap)
    while start < len(text):
        chunks.append(text[start:start + size])
        start += step
    return chunks


def chunk_markdown_structured(content: str, size: int, overlap: int, source: str = "") -> list[str]:
    sections = parse_markdown_sections(content)
    if not sections:
        return chunk_plain_text(content, size, overlap)

    chunks: list[str] = []
    for section in sections:
        for body in split_section_body(section.content, size, overlap):
            chunk = format_structured_chunk(body, section.heading_path, source)
            if chunk.strip():
                chunks.append(chunk)
    return chunks


def parse_markdown_sections(content: str) -> list[Chunk]:
    lines = (content or "").splitlines()
    heading_stack: list[tuple[int, str]] = []
    current_lines: list[str] = []
    current_heading = ""
    sections: list[Chunk] = []

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append(Chunk(content=body, heading_path=current_heading))

    for line in lines:
        match = HEADING_PATTERN.match(line.strip())
        if match:
            flush()
            current_lines = []
            level = len(match.group(1))
            title = match.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            current_heading = " > ".join(title for _, title in heading_stack)
            continue
        current_lines.append(line)

    flush()
    return sections


def split_section_body(content: str, size: int, overlap: int) -> list[str]:
    text = normalize_markdown_body(content)
    if not text:
        return []
    if len(text) <= size:
        return [text]

    blocks = split_blocks(text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for block in blocks:
        if len(block) > size:
            if current:
                chunks.append("\n\n".join(current).strip())
                current = []
                current_len = 0
            chunks.extend(chunk_plain_text(block, size, overlap))
            continue

        separator_len = 2 if current else 0
        if current and current_len + separator_len + len(block) > size:
            chunks.append("\n\n".join(current).strip())
            current = overlap_tail(current, overlap)
            current_len = sum(len(item) for item in current) + max(0, len(current) - 1) * 2

        current.append(block)
        current_len += separator_len + len(block)

    if current:
        chunks.append("\n\n".join(current).strip())
    return [chunk for chunk in chunks if chunk.strip()]


def split_blocks(text: str) -> list[str]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if len(blocks) > 1:
        return blocks
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines or [text]


def overlap_tail(blocks: list[str], overlap: int) -> list[str]:
    if overlap <= 0 or not blocks:
        return []
    kept: list[str] = []
    total = 0
    for block in reversed(blocks):
        kept.insert(0, block)
        total += len(block)
        if total >= overlap:
            break
    return kept


def normalize_markdown_body(content: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in (content or "").splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def format_structured_chunk(content: str, heading_path: str, source: str = "") -> str:
    metadata = []
    if source:
        metadata.append(f"Source: {source}")
    if heading_path:
        metadata.append(f"Section: {heading_path}")
    prefix = "\n".join(metadata).strip()
    body = content.strip()
    return f"{prefix}\n\n{body}".strip() if prefix else body
