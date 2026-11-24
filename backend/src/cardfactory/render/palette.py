"""Paleta oficial (C§17.1; VIS-002) e paleta clara equivalente só para o preview (AMB-01; VIS-017)."""

from __future__ import annotations

from dataclasses import dataclass

TEXT_COLORS = frozenset({"#7DD3FC", "#FCD34D", "#FCA5A5", "#E5E7EB", "#94A3B8"})
STRUCTURE_COLORS = frozenset({"#30343B", "#101114", "#000000"})
OFFICIAL = TEXT_COLORS | STRUCTURE_COLORS


@dataclass(frozen=True)
class Palette:
    name: str
    background: str   # só usado pelo preview; o renderizador nunca fixa o fundo (VIS-010)
    text: str
    complement: str
    blue: str
    amber: str
    red: str
    separator: str

    def semantic(self, semantic: str) -> str | None:
        """Cor por natureza semântica (VIS-003). None = herda a cor do tema (texto neutro)."""
        return {"concept": self.blue, "conduct": self.blue, "diagnosis": self.blue, "value": self.amber,
                "divergence": self.amber, "risk": self.red, "complement": self.complement,
                "reference": self.complement}.get(semantic)


DARK = Palette("dark", "#101114", "#E5E7EB", "#94A3B8", "#7DD3FC", "#FCD34D", "#FCA5A5", "#30343B")
# Equivalentes semânticos para fundo branco, todos com contraste ≥ 4,5:1 (conferido em teste).
LIGHT = Palette("light", "#FFFFFF", "#1F2937", "#475569", "#0369A1", "#92400E", "#B91C1C", "#CBD5E1")
PALETTES = {"dark": DARK, "light": LIGHT}


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(fg: str, bg: str) -> float:
    """Razão de contraste WCAG 2.x."""
    a, b = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)
