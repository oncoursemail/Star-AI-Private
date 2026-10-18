"""Audited file tools confined to a user-selected workspace. Never a shell escape hatch."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

MAX_READ_BYTES = 250_000
MAX_WRITE_BYTES = 250_000
DENIED_NAMES = {'.env', '.git', '.github', '.ssh', '.aws', '.npmrc', '.pypirc', 'id_rsa', 'id_ed25519',
                '.netrc', '.git-credentials'}
DENIED_SUFFIXES = {'.pem', '.p12', '.pfx', '.key'}
# `.env.local`, `.env.production` ... hold the same secrets as `.env`; these few are templates.
_ENV_TEMPLATES = {'.env.example', '.env.sample', '.env.template'}
# Windows device names (also with an extension: `nul.txt` opens the device).
# Windows also treats the superscript digits COM¹-³/LPT¹-³ and the console names as devices.
_RESERVED = {'con', 'prn', 'aux', 'nul', 'conin$', 'conout$',
             *(f'{dev}{i}' for dev in ('com', 'lpt') for i in (*range(1, 10), '¹', '²', '³'))}


def _bad_component(part: str) -> str:
    """Why one path component is refused, or ''.

    Windows drops trailing dots and spaces when it opens a path, so `.git./config` would write
    `.git/config` and `.env.` would write `.env`; `name:stream` opens an NTFS alternate data
    stream. These spellings are refused on every platform, so the protected-name checks always
    see the name the file system uses.
    """
    if part in ('.', '..'):
        return ''
    if part != part.rstrip('. '):
        return 'Path parts may not end with a dot or a space'
    if any(ord(ch) < 32 or ch in '<>:"|?*' for ch in part):
        return 'Path contains a character Windows does not allow'
    if part.split('.', 1)[0].strip().lower() in _RESERVED:
        return 'Windows device names are not files'
    return ''


def _protected(part: str) -> bool:
    name = part.rstrip('. ').lower()
    return name in DENIED_NAMES or (name.startswith('.env.') and name not in _ENV_TEMPLATES)

TOOLS = [
    {"name": "workspace_list", "description": "List files and folders relative to the selected workspace. Does not read outside it.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "default": "."}}, "additionalProperties": False}},
    {"name": "workspace_read", "description": "Read a UTF-8 text file in the selected workspace (not secrets or binary files).",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
    {"name": "workspace_search", "description": "Read-only scoped code navigation: text search, mode=symbols, or mode=map for a compact dependency-ranked project map.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"},
                                                "mode": {"type": "string", "enum": ["text", "symbols", "map"], "default": "text"}},
                     "required": ["query"], "additionalProperties": False}},
    {"name": "workspace_write", "description": "Create or update a UTF-8 text file inside the selected workspace. Requires workspace edit mode.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                     "required": ["path", "content"], "additionalProperties": False}},
    {"name": "workspace_edit", "description": "Replace old_string with new_string in one existing UTF-8 text file in the selected workspace. old_string must identify exactly one place (copy it from workspace_read); a different indentation is tolerated. Requires workspace edit mode.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "old_string": {"type": "string"},
                                                "new_string": {"type": "string"}, "replace_all": {"type": "boolean", "default": False}},
                     "required": ["path", "old_string", "new_string"], "additionalProperties": False}},
    {"name": "workspace_binary_triage", "description": "Identify and SHA-256 fingerprint an explicitly selected PE/ELF/Mach-O/WASM binary for approved REA/Ghidra investigations. Does not execute or disassemble it.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}},
                     "required": ["path"], "additionalProperties": False}},
    {"name": "workspace_asset_audit", "description": "Audit a selected .gltf/.glb 3D asset's meshes, triangle budget, materials, skins and animations without running Blender or reading external assets.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "target": {"type": "string", "enum": ["general", "roblox", "godot", "unity", "unreal"]},
         "triangle_budget": {"type": "integer", "minimum": 1000, "maximum": 10000000}},
         "required": ["path"], "additionalProperties": False}},
    {"name": "workspace_game_graph", "description": "Trace bounded static Godot res:// or Unity YAML GUID dependencies with source/line evidence. Unreal reports approved manifest plugins only; no editor or arbitrary binary runs.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}},
                     "required": ["path"], "additionalProperties": False}},
    {"name": "workspace_game_discover", "description": "Discover Godot, Unity, and Unreal game projects in this selected workspace; read-only, bounded scan.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "default": "."}}, "additionalProperties": False}},
    {"name": "workspace_game_inspect", "description": "Inspect one Godot, Unity, or Unreal project: engine metadata, languages, sample scenes and export presets. Read-only.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
    {"name": "workspace_game_plan", "description": "Preview an engine-specific validation, import, test or export command. Never executes code or launches an editor.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "action": {"type": "string", "enum": ["validate", "import", "test", "export"]},
         "preset": {"type": "string"}, "output": {"type": "string"}},
         "required": ["path", "action"], "additionalProperties": False}},
    {"name": "workspace_minecraft_audit",
     "description": "Inspect Minecraft Java resource-pack folder/ZIP or Blockbench .bbmodel inside the selected workspace. Offline read-only validation: manifests, models, references, textures, unsafe ZIP entries and animation structure. Does not launch Minecraft or install anything.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"},
         "target_version": {"type": "string", "enum": ["1.21.4", "1.21.5", "1.21.6", "1.21.7", "1.21.8", "1.21.9", "1.21.10", "1.21.11", "26.1", "26.2", "26.3"], "default": "26.3"}},
         "required": ["path"], "additionalProperties": False}},
    {"name": "workspace_minecraft_package",
     "description": "Build a deterministic ZIP from a validated Minecraft Java resource-pack folder in the selected workspace. Requires owner-enabled workspace editing. Does not deploy or overwrite an existing archive unless explicitly requested.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "output": {"type": "string"},
         "target_version": {"type": "string", "enum": ["1.21.4", "1.21.5", "1.21.6", "1.21.7", "1.21.8", "1.21.9", "1.21.10", "1.21.11", "26.1", "26.2", "26.3"]},
         "replace": {"type": "boolean", "default": False}},
         "required": ["path", "output", "target_version"], "additionalProperties": False}},
    {"name": "workspace_minecraft_inspect",
     "description": "Read-only, offline inspection of an owner's Minecraft server/project folder: plugin and mod JAR metadata, Velocity/Paper/Fabric family hints, resource-pack managers, and a tiny safe allowlist of server properties. No JAR execution, credentials, server commands or live-state claims.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "default": "."}},
                     "additionalProperties": False}},
    {"name": "workspace_minecraft_item_scaffold",
     "description": "Create a valid version-pinned Java custom 2D item resource pack from an owner's existing PNG texture. Generates pack.mcmeta, modern item model definition, referenced model and texture. Requires owner-enabled workspace editing; output folder must be new. No placeholder art, builds, server changes or deployment.",
     "inputSchema": {"type": "object", "properties": {
         "output_dir": {"type": "string"}, "namespace": {"type": "string"}, "item_id": {"type": "string"},
         "texture_path": {"type": "string"},
         "target_version": {"type": "string", "enum": ["1.21.4", "1.21.5", "1.21.6", "1.21.7", "1.21.8", "1.21.9", "1.21.10", "1.21.11", "26.1", "26.2", "26.3"]},
         "description": {"type": "string", "maxLength": 140}},
         "required": ["output_dir", "namespace", "item_id", "texture_path", "target_version"],
         "additionalProperties": False}},
]
TOOL_NAMES = {t['name'] for t in TOOLS}
WRITE_TOOLS = frozenset({'workspace_write', 'workspace_edit', 'workspace_minecraft_package',
                         'workspace_minecraft_item_scaffold'})


class Workspace:
    def __init__(self, root: Path):
        root = root.expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError('Workspace must be an existing directory')
        self.root = root

    def resolve(self, relative: str, *, allow_missing: bool = False) -> Path:
        if not relative or len(relative) > 500:
            raise ValueError('Invalid file path')
        value = Path(relative)
        if value.is_absolute() or value.drive or value.root:
            raise PermissionError('Absolute paths are blocked')
        for part in value.parts:
            problem = _bad_component(part)
            if problem:
                raise PermissionError(problem)
            if _protected(part):
                raise PermissionError('Private/credential directories and files are protected')
        candidate = (self.root / value).resolve(strict=not allow_missing)
        if not candidate.is_relative_to(self.root):
            raise PermissionError('Path escapes the selected workspace')
        # The resolved file too: a link may point at a protected one.
        if any(_protected(part) for part in candidate.relative_to(self.root).parts):
            raise PermissionError('Private/credential directories and files are protected')
        if any(Path(name.rstrip('. ')).suffix.lower() in DENIED_SUFFIXES for name in (value.name, candidate.name)):
            raise PermissionError('Sensitive file type blocked')
        return candidate

    def call(self, name: str, args: dict[str, Any], *, allow_write: bool = False) -> dict[str, Any]:
        if name not in TOOL_NAMES:
            raise ValueError('Unknown workspace tool')
        if not isinstance(args, dict):
            raise ValueError('Arguments must be an object')
        from jsonschema import validate, ValidationError
        schema = next(t['inputSchema'] for t in TOOLS if t['name'] == name)
        try:
            validate(args, schema)
        except ValidationError:
            raise ValueError('Invalid workspace tool arguments') from None
        if name == 'workspace_minecraft_inspect':
            from . import minecraft_server_inventory
            return minecraft_server_inventory.inspect(self, args.get('path', '.'))
        if name == 'workspace_minecraft_audit':
            from . import minecraft_assets
            return minecraft_assets.audit(self, args['path'], target_version=args.get('target_version', '26.3'))
        if name == 'workspace_minecraft_item_scaffold':
            if not allow_write:
                raise PermissionError('Workspace editing is switched off')
            from . import minecraft_assets
            return minecraft_assets.scaffold_item(self, args['output_dir'],
                                                  namespace=args['namespace'],
                                                  item_id=args['item_id'],
                                                  texture_path=args['texture_path'],
                                                  target_version=args['target_version'],
                                                  description=args.get('description', 'Minecraft custom items'))
        if name == 'workspace_minecraft_package':
            if not allow_write:
                raise PermissionError('Workspace editing is switched off')
            from . import minecraft_assets
            return minecraft_assets.package(self, args['path'], args['output'],
                                            target_version=args['target_version'],
                                            replace=args.get('replace', False))
        if name == 'workspace_binary_triage':
            from . import binary_evidence
            return binary_evidence.triage(self, args['path'])
        if name == 'workspace_asset_audit':
            from . import artifact_intelligence
            return artifact_intelligence.audit(self, args['path'], target=args.get('target', 'general'),
                                               triangle_budget=args.get('triangle_budget', 100_000))
        if name == 'workspace_game_graph':
            from . import engine_evidence
            return engine_evidence.inspect(self, args['path'])
        if name in {'workspace_game_discover', 'workspace_game_inspect', 'workspace_game_plan'}:
            from . import game_projects
            if name == 'workspace_game_discover':
                return game_projects.discover(self, args.get('path', '.'))
            if name == 'workspace_game_inspect':
                return game_projects.inspect(self, args['path'])
            return game_projects.plan(self, args['path'], args['action'],
                                      preset=args.get('preset', ''), output=args.get('output', ''))
        if name == 'workspace_list':
            path = self.resolve(args.get('path', '.'))
            if not path.is_dir():
                raise ValueError('Not a directory')
            items = []
            for p in sorted(path.iterdir(), key=lambda p: p.name.lower()):
                try:
                    self.resolve(p.relative_to(self.root).as_posix())
                except (PermissionError, OSError, ValueError):
                    continue
                items.append({'name': p.name, 'type': 'directory' if p.is_dir() else 'file'})
                if len(items) >= 150:
                    break
            return {'path': path.relative_to(self.root).as_posix(), 'items': items}
        if name == 'workspace_read':
            path = self.resolve(args['path'])
            if not path.is_file() or path.stat().st_size > MAX_READ_BYTES:
                raise ValueError('Not a small text file')
            return {'path': args['path'], 'content': path.read_text(encoding='utf-8')}
        if name == 'workspace_search':
            from .code_navigation import search_workspace
            return search_workspace(self, args['query'], mode=args.get('mode', 'text'))
        if not allow_write:
            raise PermissionError('Workspace editing is switched off')
        if name == 'workspace_edit':
            from .edit_match import apply_edit
            path = self.resolve(args['path'])
            if not path.is_file() or path.stat().st_size > MAX_READ_BYTES:
                raise ValueError('Not a small text file')
            with path.open(encoding='utf-8', newline='') as handle:
                edited = apply_edit(handle.read(), args['old_string'], args['new_string'],
                                    replace_all=args.get('replace_all', False))
            result = self._replace(path, edited.text.encode('utf-8'))
            result.update({'replacements': edited.count, 'match': edited.strategy})
            return _with_lint(result, path, edited.text)
        path = self.resolve(args['path'], allow_missing=True)
        result = self._replace(path, args['content'].encode('utf-8'))
        return _with_lint(result, path, args['content'])

    def _replace(self, path: Path, data: bytes) -> dict[str, Any]:
        if len(data) > MAX_WRITE_BYTES:
            raise ValueError('File exceeds write limit')
        if path.exists() and not path.is_file():
            raise ValueError('Target is not a regular file')
        path.parent.mkdir(parents=True, exist_ok=True)
        # Unique temp file in the same directory avoids symlink replacement attacks
        # against a predictable .star-tmp filename.
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(prefix='.star-write-', dir=path.parent,
                                             delete=False) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(data)
            os.replace(tmp_path, path)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
        return {'path': path.relative_to(self.root).as_posix(), 'bytes_written': len(data)}


LINTED_SUFFIXES = frozenset({'.lua', '.luau'})
MAX_LINT_FINDINGS = 8


def _with_lint(result: dict[str, Any], path: Path, text: str) -> dict[str, Any]:
    """Lint-on-edit: a written Luau file comes back with STAR's offline findings, so the model can fix them now.

    Advisory only: the write has already happened and a finding never blocks it (star/luau_lint.py is a pattern
    checker, not a parser). The SWE-agent ACI study (arXiv 2405.15793) found that showing lint results right after an
    edit cut broken edits; this is the same idea with STAR's own Roblox rules.
    """
    if path.suffix.lower() not in LINTED_SUFFIXES:
        return result
    from .luau_lint import lint
    try:
        findings = lint(text)
    except Exception:       # a checker bug must never turn a successful write into a failed tool call
        return result
    if findings:
        result['lint'] = [{'line': f.line, 'rule': f.rule_id, 'severity': f.severity, 'message': f.message,
                           'fix': f.suggested_fix} for f in findings[:MAX_LINT_FINDINGS]]
        if len(findings) > MAX_LINT_FINDINGS:
            result['lint_more'] = len(findings) - MAX_LINT_FINDINGS
    return result
