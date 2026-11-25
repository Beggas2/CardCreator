"""Representação textual de cards para auditores e varreduras (AUD-001: sem autoavaliação do criador)."""

from __future__ import annotations

from typing import Any

from cardfactory.validation.html import normalized_text, validate_field


def is_v2(content: dict[str, Any]) -> bool:
    return isinstance(content.get("front"), dict)


def front_plain(content: dict[str, Any]) -> str:
    if is_v2(content):
        return "".join(s["text"] for s in content["front"]["segments"])
    return validate_field(content.get("front_html", "")).text


def block_texts(content: dict[str, Any]) -> list[tuple[str, str]]:
    """(camada, texto) por item; tabelas viram 'célula | célula'."""
    if not is_v2(content):
        return [("legacy", validate_field(content.get("back_html", "")).text)]
    out = []
    for b in content["answer"]:
        if b["title"]:
            out.append((b["role"], b["title"]))
        for it in b["items"]:
            if it["cells"]:
                out.append((b["role"], " | ".join("".join(sg["text"] for sg in c["segments"]) for c in it["cells"])))
            else:
                out.append((b["role"], "".join(sg["text"] for sg in it["segments"])))
    return out


def back_plain(content: dict[str, Any]) -> str:
    return "\n".join(t for _, t in block_texts(content))


def for_auditor(content: dict[str, Any]) -> str:
    """Texto entregue aos auditores: frente, camadas, regra de combinação e referência. Sem validação prévia."""
    lines = [f"Frente: {front_plain(content)}"]
    if is_v2(content):
        lines.append(f"Tipo {content['cognitive_type']} · layout {content['layout']} · deck "
                     f"{'::'.join(content['deck_path'])}")
        for b in content["answer"]:
            rule = f" (regra: {b['combination_rule']}{' ' + str(b['combination_n']) if b['combination_n'] else ''})" \
                if b["combination_rule"] else ""
            lines.append(f"[{b['role']}]{rule}")
            if b["title"]:
                lines.append(f"  título: {b['title']}")
            if b["header"]:
                lines.append("  colunas: " + " | ".join(b["header"]))
            for it in b["items"]:
                if it["cells"]:
                    lines.append("  - " + " | ".join("".join(sg["text"] for sg in c["segments"]) for c in it["cells"]))
                else:
                    lines.append("  - " + "".join(sg["text"] for sg in it["segments"]))
        ref = content.get("short_reference")
        if ref:
            lines.append(f"Referência curta: {ref['display']}")
    else:
        lines.append(f"Verso (legado): {back_plain(content)}")
    return "\n".join(lines)


def normalized(content: dict[str, Any]) -> str:
    return normalized_text(front_plain(content) + " " + back_plain(content))
