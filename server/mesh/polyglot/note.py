"""A hidden note on coding questions in languages/engines outside Litha's game-building system prompt (Python,
JavaScript/TypeScript, C#/.NET, Java, C/C++, Unreal, Rust, Go, Lua/LOVE, GDScript/Godot, SQL, shell, web...).

The launcher's system prompt names Roblox, Unity, Minecraft and RC rooms, and the fast path then refused such questions
("I don't support Python") or answered them as a short general question. The note goes on the last user turn (the
system prompt stays the cached prefix, like the docs block and the general-mode note) and carries the few version
facts that decide whether the code compiles today.

    hdr = apply(req)       # {"X-Mesh-Polyglot": "python"} or {} when the question is not one of these
"""
from __future__ import annotations

import re

DEFAULTS = {"polyglot_note": True}

# (language id, pattern on the question). First match wins; Roblox/Minecraft/Unity questions never match (their own
# prompt and checks cover them).
LANG_RULES = [
    ("unreal", r"\bunreal\b|\bue ?5\b|\bue4\b|\bblueprints?\b.*\bc\+\+|\bUCLASS\b|\bUPROPERTY\b"),
    ("gdscript", r"\bgodot\b|\bgdscript\b"),
    ("love", r"\bl(?:ö|o)ve2d\b|\bl(?:ö|o)ve 11\b|\bL(?:Ö|O)VE\b|\blove\.(?:update|draw|load)\b"),
    ("typescript", r"\btypescript\b|\bts-node\b|\bdeno\b"),
    ("web", r"\bhtml\b|\bweb ?page\b"),
    ("javascript", r"\bjavascript\b|\bnode\.?js\b|\bin node\b|\bnode (?:program|script)\b|\bjs\b|\breact\b|\bvue\b|"
                   r"\bthree\.js\b|\bphaser\b"),
    ("python", r"\bpython\b|\bpygame\b|\bdjango\b|\bflask\b|\bnumpy\b|\bpandas\b"),
    ("rust", r"\brust\b|\bcargo\b|\bbevy\b"),
    ("go", r"\bgolang\b|\bin go\b|\bgo program\b|\bgo (?:code|function|module|1\.\d+)\b|\bgoroutines?\b"),
    ("cpp", r"\bc\+\+|\bcpp\b|\bsfml\b|\braylib\b|\bsdl2?\b"),
    ("csharp", r"\bc#|\bcsharp\b|\b\.net\b|\bdotnet\b|\bmonogame\b"),
    ("java", r"\bjava\b(?!script)|\blibgdx\b|\bjdk\b"),
    ("c", r"\bin c\b|\bc program\b|\bansi c\b|\bc99\b|\bc11\b|\bc17\b|\bc code\b"),
    ("lua", r"\blua\b"),
    ("sql", r"\bsql\b|\bsqlite\b|\bpostgres(?:ql)?\b|\bmysql\b|\bmariadb\b|\bquery\b.*\btables?\b"),
    ("shell", r"\bbash\b|\bshell script\b|\bzsh\b|\bsh script\b"),
    ("web", r"\bcss\b|\bcanvas\b.*\bbrowser\b"),
    ("other", r"\bkotlin\b|\bswift\b|\bphp\b|\bruby\b|\bhaskell\b|\bscala\b|\bdart\b|\bflutter\b|\bzig\b|\belixir\b"),
]
LANG_RX = [(name, re.compile(rx, re.I)) for name, rx in LANG_RULES]
IN_SCOPE = re.compile(r"\broblox\b|\bluau\b|\bminecraft\b|\bspigot\b|\bpaper ?mc\b|\bbukkit\b|\bfabric\b|\bneoforge\b|"
                      r"\bforge\b|\bdata ?pack\b|\bmcfunction\b|\bunity\b|\bmonobehaviou?r\b|\bmetallic\b", re.I)
CODE_ASK = re.compile(r"\b(write|make|create|build|code|program|script|function|class|implement|fix|debug|error|compile|"
                      r"query|algorithm|parse|print|output|input|stdin|return|loop|array|list|game)\b|```", re.I)

NAMES = {"unreal": "Unreal Engine C++", "gdscript": "Godot (GDScript)", "love": "LOVE (Lua)", "typescript": "TypeScript",
         "javascript": "JavaScript", "python": "Python", "rust": "Rust", "go": "Go", "cpp": "C++", "csharp": "C#",
         "java": "Java", "c": "C", "lua": "Lua", "sql": "SQL", "shell": "shell (bash)", "web": "HTML/CSS/JavaScript",
         "other": "this language"}
TIPS = {
    "python": "Python 3.12, standard library unless a package is asked for; read input from sys.stdin.",
    "javascript": "Node.js (CommonJS unless asked): read all input with require('fs').readFileSync(0, 'utf8').",
    "typescript": "TypeScript 5 strict: give every parameter a type; on Node read input with "
                  "require('fs').readFileSync(0, 'utf8').",
    "csharp": ".NET 8 / C# 12 console app; Console.ReadLine() can return null at the end of input.",
    "java": "Java 21; name the class as asked (public class Main when it is a program); read input with "
            "BufferedReader.",
    "cpp": "C++20, standard library only unless asked; long long when values can pass 2^31.",
    "c": "C17; check scanf's return value; no undefined behaviour.",
    "rust": "Rust 2021 edition, std only unless a crate is asked for; read input with "
            "std::io::read_to_string(std::io::stdin()).",
    "go": "Go 1.22, standard library only; an unused variable or import is a compile error; bufio.Scanner needs "
          "a bigger Buffer for long lines.",
    "lua": "Lua 5.4: io.read('l') / io.read('n'); no Roblox APIs (no game, task, Instance).",
    "love": "LOVE 11.x: love.load / love.update(dt) / love.draw, love.graphics, love.keyboard.isDown; no Roblox APIs.",
    "gdscript": "Godot 4.x GDScript: @export / @onready, CharacterBody2D/3D use the velocity property and "
                "move_and_slide() with no arguments, signal_name.connect(callable), await instead of yield, "
                "instantiate() not instance(); no Godot 3 syntax.",
    "unreal": "Unreal Engine 5 C++: UCLASS() + GENERATED_BODY(), UPROPERTY/UFUNCTION specifiers, the .h and the .cpp, "
              "Enhanced Input (UInputAction, UEnhancedInputComponent) for input.",
    "sql": "SQL that runs on SQLite unless another database is named; every non-aggregated column in GROUP BY.",
    "shell": "bash; quote variables; read input with while IFS= read -r line.",
    "web": "one HTML file with <style> and <script> unless asked otherwise; addEventListener / querySelector.",
    "other": "current stable version and its standard library.",
}


def detect(text: str) -> str | None:
    """The language/engine of a coding question outside Litha's built-in scope, or None."""
    if not text or IN_SCOPE.search(text) or not CODE_ASK.search(text):
        return None
    for name, rx in LANG_RX:
        if rx.search(text):
            return name
    return None


def note(lang: str) -> str:
    return (f"(Note for Litha, not from the user: this is a {NAMES[lang]} programming question. Litha helps with every "
            f"programming language and game engine, not only Roblox, Unity and Minecraft: answer it fully with "
            f"correct, complete, runnable {NAMES[lang]} code that follows the asked input/output exactly; never say "
            f"it is outside your expertise. {TIPS[lang]})")


def apply(req: dict, cfg: dict | None = None) -> dict:
    """Add the note to the last user turn when the question is one of these; returns the header for the log."""
    if cfg is not None and not cfg.get("polyglot_note", True):
        return {}
    msgs = req.get("messages")
    if not isinstance(msgs, list) or not msgs or not isinstance(msgs[-1], dict) or msgs[-1].get("role") != "user":
        return {}
    text = msgs[-1].get("content")
    if not isinstance(text, str) or "(Note for Litha" in text:
        return {}
    lang = detect(text)
    if not lang:
        return {}
    msgs[-1] = {**msgs[-1], "content": text + "\n\n" + note(lang)}
    return {"X-Mesh-Polyglot": lang}
