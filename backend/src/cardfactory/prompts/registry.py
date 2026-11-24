"""Registro de prompts versionado (PRM-002/003/005/006, MNT-004, SEC-002).

Arquivos em `prompts/` são a origem; o banco guarda versões imutáveis. Editar cria versão nova.
Os documentos normativos em `docs/normative/` são só lidos, nunca alterados.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy import func, select

from cardfactory.db import Database
from cardfactory.db.models import Prompt, PromptVersion

REQ_RE = re.compile(r"<!--\s*req:\s*([^>]*?)\s*-->")
VARIANTS = ("specialized", "full")


class PromptError(Exception):
    pass


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def annotated_req_ids(text: str) -> list[str]:
    """IDs anotados em `<!-- req: A, B -->`, na ordem, sem repetição. `-` indica bloco sem requisito."""
    out: list[str] = []
    for m in REQ_RE.finditer(text):
        for rid in re.split(r"[,\s]+", m.group(1)):
            if rid and rid != "-" and rid not in out:
                out.append(rid)
    return out


def wrap_untrusted(doc_id: str, text: str) -> str:
    """Delimita conteúdo externo como dado (SEC-002). Neutraliza tentativas de fechar o delimitador."""
    safe_id = re.sub(r"[^A-Za-z0-9_.:-]", "_", doc_id)[:80]
    body = re.sub(r"</?\s*untrusted_document", "&lt;untrusted_document", text, flags=re.IGNORECASE)
    return f'<untrusted_document id="{safe_id}">\n{body}\n</untrusted_document>'


@dataclass
class RoleSpec:
    name: str
    policies: list[str]
    normative: str | None
    contract: str
    required: list[str]


@dataclass
class Manifest:
    roles: dict[str, RoleSpec]

    @classmethod
    def load(cls, path: Path) -> Manifest:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        roles = {name: RoleSpec(name, list(r.get("policies") or []), r.get("normative"), r["contract"],
                                list(r.get("required") or []))
                 for name, r in (data.get("roles") or {}).items()}
        return cls(roles)


@dataclass
class ComposedPrompt:
    role: str
    variant: str
    text: str
    hash: str
    version_ids: list[str]
    req_ids: list[str]
    contract: str
    missing_required: list[str] = field(default_factory=list)


class PromptRegistry:
    def __init__(self, db: Database, prompts_dir: Path, normative_dir: Path):
        self.db = db
        self.dir = prompts_dir
        self.normative_dir = normative_dir
        self.manifest = Manifest.load(prompts_dir / "manifest.yaml")

    # ------------------------------------------------------------ importação
    def _library_files(self) -> dict[str, tuple[str, Path]]:
        files: dict[str, tuple[str, Path]] = {}
        for kind, sub in (("POLICY", "policies"), ("ROLE", "roles")):
            for f in sorted((self.dir / sub).glob("*.md")):
                files[f"{kind.lower()}:{f.stem}"] = (kind, f)
        return files

    def import_library(self, author: str = "import") -> dict[str, int]:
        """Sincroniza arquivos → banco. Só cria versão nova quando o conteúdo mudou."""
        created = unchanged = 0
        for key, (kind, path) in self._library_files().items():
            body = path.read_text(encoding="utf-8")
            if self._import_one(key, kind, body, author, note=f"importado de {path.name}"):
                created += 1
            else:
                unchanged += 1
        return {"created": created, "unchanged": unchanged}

    def _import_one(self, key: str, kind: str, body: str, author: str, note: str) -> bool:
        with self.db.write() as s:
            p = s.execute(select(Prompt).where(Prompt.key == key)).scalar_one_or_none()
            if p is None:
                p = Prompt(key=key, kind=kind)
                s.add(p)
                s.flush()
            if p.active_version_id:
                active = s.get(PromptVersion, p.active_version_id)
                if active and active.content_hash == sha256(body):
                    return False
            self._new_version(s, p, body, author, note)
            return True

    @staticmethod
    def _new_version(s, p: Prompt, body: str, author: str, note: str) -> PromptVersion:
        n = s.execute(select(func.coalesce(func.max(PromptVersion.version), 0))
                      .where(PromptVersion.prompt_id == p.id)).scalar_one()
        v = PromptVersion(prompt_id=p.id, version=n + 1, body=body, req_ids=annotated_req_ids(body),
                          parent_version_id=p.active_version_id, content_hash=sha256(body), created_by=author,
                          note=note)
        s.add(v)
        s.flush()
        p.active_version_id = v.id
        return v

    # ------------------------------------------------------------ edição (PRM-006)
    def _prompt(self, s, key: str) -> Prompt:
        p = s.execute(select(Prompt).where(Prompt.key == key)).scalar_one_or_none()
        if p is None:
            raise PromptError(f"prompt '{key}' não existe")
        return p

    def edit(self, key: str, body: str, author: str, note: str = "") -> str:
        if not author:
            raise PromptError("edição exige autor")
        with self.db.write() as s:
            p = self._prompt(s, key)
            active = s.get(PromptVersion, p.active_version_id) if p.active_version_id else None
            if active and active.content_hash == sha256(body):
                return active.id
            return self._new_version(s, p, body, author, note).id

    def restore(self, key: str, version_id: str, author: str) -> str:
        """Restaurar = nova versão com o conteúdo antigo (o histórico nunca é reescrito)."""
        with self.db.write() as s:
            p = self._prompt(s, key)
            old = s.get(PromptVersion, version_id)
            if old is None or old.prompt_id != p.id:
                raise PromptError("versão não pertence a este prompt")
            return self._new_version(s, p, old.body, author, f"restaurado da versão {old.version}").id

    def duplicate(self, key: str, new_key: str, author: str) -> str:
        with self.db.write() as s:
            src = self._prompt(s, key)
            if s.execute(select(Prompt).where(Prompt.key == new_key)).scalar_one_or_none():
                raise PromptError(f"prompt '{new_key}' já existe")
            body = s.get(PromptVersion, src.active_version_id).body
            p = Prompt(key=new_key, kind=src.kind, description=f"cópia de {key}")
            s.add(p)
            s.flush()
            return self._new_version(s, p, body, author, f"duplicado de {key}").id

    def activate(self, key: str, version_id: str) -> None:
        with self.db.write() as s:
            p = self._prompt(s, key)
            v = s.get(PromptVersion, version_id)
            if v is None or v.prompt_id != p.id:
                raise PromptError("versão não pertence a este prompt")
            p.active_version_id = v.id

    def diff(self, version_a: str, version_b: str) -> str:
        with self.db.session() as s:
            a, b = s.get(PromptVersion, version_a), s.get(PromptVersion, version_b)
            if a is None or b is None:
                raise PromptError("versão inexistente")
            return "".join(difflib.unified_diff(a.body.splitlines(True), b.body.splitlines(True),
                                                f"v{a.version}", f"v{b.version}"))

    # ------------------------------------------------------------ consulta
    def list_prompts(self) -> list[dict]:
        with self.db.session() as s:
            out = []
            for p in s.execute(select(Prompt).order_by(Prompt.key)).scalars():
                v = s.get(PromptVersion, p.active_version_id) if p.active_version_id else None
                out.append({"key": p.key, "kind": p.kind, "description": p.description,
                            "active_version_id": p.active_version_id, "version": v.version if v else None,
                            "hash": v.content_hash if v else None, "req_ids": v.req_ids if v else []})
            return out

    def versions(self, key: str) -> list[dict]:
        with self.db.session() as s:
            p = self._prompt(s, key)
            rows = s.execute(select(PromptVersion).where(PromptVersion.prompt_id == p.id)
                             .order_by(PromptVersion.version.desc())).scalars()
            return [{"id": v.id, "version": v.version, "hash": v.content_hash, "created_by": v.created_by,
                     "created_at": v.created_at.isoformat() if v.created_at else None, "note": v.note,
                     "req_ids": v.req_ids, "active": v.id == p.active_version_id, "body": v.body} for v in rows]

    # ------------------------------------------------------------ composição
    def compose(self, role: str, variant: str = "specialized") -> ComposedPrompt:
        if variant not in VARIANTS:
            raise PromptError(f"variante '{variant}' não suportada (disponíveis: {', '.join(VARIANTS)})")
        spec = self.manifest.roles.get(role)
        if spec is None:
            raise PromptError(f"papel '{role}' não está no manifesto")
        parts: list[str] = []
        version_ids: list[str] = []
        with self.db.session() as s:
            for key in [f"policy:{p}" for p in spec.policies] + [f"role:{role}"]:
                p = self._prompt(s, key)
                v = s.get(PromptVersion, p.active_version_id)
                parts.append(v.body.strip())
                version_ids.append(v.id)
        if variant == "full":
            if not spec.normative:
                raise PromptError(f"papel '{role}' não tem documento normativo integral")
            doc = (self.normative_dir / spec.normative).read_bytes().decode("utf-8")
            parts.append(f"# Documento normativo integral: {spec.normative}\n\n{doc}")
        text = "\n\n---\n\n".join(parts) + "\n"
        reqs = annotated_req_ids(text)
        missing = [r for r in spec.required if r not in reqs]
        return ComposedPrompt(role, variant, text, sha256(text), version_ids, reqs, spec.contract, missing)

    def coverage_report(self) -> dict[str, list[str]]:
        """Requisitos obrigatórios ausentes por papel (vazio = cobertura completa)."""
        return {role: self.compose(role).missing_required for role in self.manifest.roles}
