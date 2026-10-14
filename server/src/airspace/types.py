"""Shared data shapes. This module is the contract between the indexer, the admission engine and the hooks."""

from dataclasses import dataclass, field
from typing import Literal

SymbolKind = Literal["function", "method", "class"]


@dataclass(frozen=True)
class SymbolFact:
    qualname: str  # "utils.text.slugify", "blog.models.Post.save"
    name: str  # "slugify", "save"
    kind: SymbolKind
    file: str  # repo-relative POSIX path, "utils/text.py"
    lineno: int
    end_lineno: int
    signature: str  # "slugify(value, allow_unicode=False)"
    sig_hash: str  # sha1(signature)[:12]
    is_test: bool  # file under tests/ or name starts with "test_"


@dataclass(frozen=True)
class CallFact:
    caller: str  # qualname of the enclosing function or method
    target: str  # dotted name as written: "slugify", "text.slugify", "self.save", "Tag.save"
    lineno: int
    nargs: int = 0  # positional arguments, not counting *args
    kwargs: tuple[str, ...] = ()  # keyword names, not counting **kwargs
    star: bool = False  # the call unpacks *args or **kwargs
    via_instance: bool = False  # the receiver is a constructed instance: Tag(name).save()
    text: str = field(default="", compare=False)  # the call as source, on one line: "slugify(post.title, True)"


@dataclass
class ModuleFacts:
    module: str  # "utils.text"
    file: str  # "utils/text.py"
    symbols: list[SymbolFact]
    calls: list[CallFact]
    imports: dict[str, str]  # local name -> dotted target
    bases: list[tuple[str, str]]  # (class qualname, base name as written)


@dataclass(frozen=True)
class SignatureChange:
    qualname: str
    old_signature: str
    new_signature: str
    # For a removal that is really a rename: the new qualname and its signature.
    renamed_to: str = ""
    renamed_signature: str = ""


@dataclass(frozen=True)
class Briefing:
    id: str
    symbol: str  # qualname
    old_signature: str
    new_signature: str  # "" when the symbol was renamed or removed
    from_agent: str
    caller: str | None = None  # the caller whose call no longer fits, when one is known


VerdictKind = Literal["cleared", "hold"]


@dataclass
class Verdict:
    kind: VerdictKind
    reason: str  # factual text shown to the agent
    path: list[str] = field(default_factory=list)  # qualnames, dependent -> dependency
    other_agent: str | None = None
    collision_id: str | None = None
    briefings: list[Briefing] = field(default_factory=list)


@dataclass(frozen=True)
class CallSite:
    """The shape of one call as written, for checking it against a signature."""

    caller: str  # qualname of the calling function or method
    nargs: int  # positional arguments, not counting *args
    kwargs: tuple[str, ...]  # keyword names, not counting **kwargs
    star: bool  # unpacks *args or **kwargs
    bound: bool  # called through an instance (or a constructor checked against __init__): the first parameter is filled
    text: str = field(default="", compare=False)  # the call as source, when known


@dataclass
class EditAnalysis:
    file: str  # repo-relative
    touched: list[str]  # qualnames whose body the edit changes, in the new source
    new_calls: list[tuple[str, str]]  # (caller qualname, resolved callee qualname) new or reshaped by the edit
    parse_ok: bool
    call_shapes: dict[str, list[CallSite]] = field(default_factory=dict)  # callee -> sites of the new calls
    signature_changes: list[SignatureChange] = field(default_factory=list)  # new_signature "" for a removal
