"""Turn streamed model text into speakable chunks, one sentence at a time.

The brain streams at roughly speaking pace, so speech has to start on the first sentence instead of
waiting for the whole reply. The first chunk is released as early as is safe (the moment its closing
punctuation arrives, or at a clause break when the opening sentence is long); later chunks wait for the
character after the punctuation so "3.5", "e.g." and "main.py" are not cut in half.

Pure Python, no third-party imports: the unit tests run in the plain repo test environment.
"""
from __future__ import annotations

import re

TERMINATORS = ".!?…。！？"
CLOSERS = "\"')]}”’»"
CLAUSE_BREAKS = ",;:—–"
# Words a long opening sentence may be split in front of when it has no punctuation to split at.
_MAX_PENDING_CHARS = 65_536  # bounded even inside unfinished hidden/model reasoning
SOFT_BREAK_WORDS = frozenset({"and", "but", "or", "so", "because", "that", "which", "who", "when", "while", "if",
                              "then", "between", "with", "for", "from", "about", "before", "after", "until"})
# Words that end with a full stop without ending the sentence. Lower case, without the final dot.
ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e", "eg", "ie",
    "fig", "approx", "inc", "ltd", "mt", "a.m", "p.m",
})

_THINK = re.compile(r"<think>.*?(</think>|\Z)", re.S | re.I)
_CODE_BLOCK = re.compile(r"```.*?(```|\Z)", re.S)
_LINK = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
_URL = re.compile(r"https?://\S+")
_STAGE = re.compile(r"(?<![\w*])\*[^*\n]{1,40}\*(?![\w*])")   # *smiles warmly*
_MARKUP = re.compile(r"[*_~`#>|]+")
_BULLET = re.compile(r"(?m)^\s*(?:[-•]|\d{1,2}[.)])\s+")
_SPACES = re.compile(r"\s+")
# Emoji and pictographs: speech engines either skip them or read their names aloud.
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF\U0000FE0F\U0000200D]")

# Scan sentence boundaries and protected spans in C's regex engine instead of
# walking every character in Python for every tiny LLM token. The protected
# alternatives MUST precede punctuation: a period inside <think> or a code
# fence must never become a spoken boundary.
_BOUNDARY_OR_HIDDEN = re.compile(
    r"```.*?(?:```|\Z)|<think>.*?(?:</think>|\Z)|[\n.!?…。！？]",
    re.S | re.I,
)


def speakable(text: str) -> str:
    """Strip everything a voice should not read aloud: markup, emoji, stage directions, raw links."""
    text = _THINK.sub(" ", text)
    text = _CODE_BLOCK.sub(" I've put the code on screen for you. ", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("a link", text)
    text = _STAGE.sub(" ", text)
    text = _BULLET.sub("", text)
    text = _MARKUP.sub("", text)
    text = _EMOJI.sub("", text)
    return _SPACES.sub(" ", text).strip()


def _has_words(text: str) -> bool:
    return any(ch.isalnum() for ch in text)


def _word_before(text: str, dot: int) -> str:
    start = dot
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    return text[start:dot].strip("\"'([{“‘").lower()


class SentenceChunker:
    """Feed text deltas, get back complete chunks ready for text-to-speech.

    first_eager: release the first chunk as soon as its terminator arrives (no look-ahead). The cost: a
        dotted name in the very first sentence ("main.py") can be cut at the dot. The voice prompt tells the
        brain not to read file names aloud, and later chunks are never affected.
    first_clause_words: if the opening sentence runs long, release its first clause once it has at
        least this many words (0 disables clause splitting).
    first_soft_words: if the opening sentence reaches this many words with no punctuation at all, split
        it in front of a linking word ("and", "because", "between", ...) so speech can start (0 disables).
        A brain that writes at speaking pace needs about four seconds for a seventeen-word sentence.
    max_chars: hard cap so a run-on sentence still reaches the speaker.
    """

    def __init__(self, *, first_eager: bool = True, first_clause_words: int = 4,
                 first_clause_chars: int = 28, first_soft_words: int = 9, max_chars: int = 240) -> None:
        self.first_eager = first_eager
        self.first_clause_words = first_clause_words
        self.first_clause_chars = first_clause_chars
        self.first_soft_words = first_soft_words
        self.max_chars = max(40, max_chars)
        self._buf = ""
        self._emitted = 0
        self._in_think = False
        self._in_code = False
        self._poisoned = False

    # -- public API -------------------------------------------------------------------------
    def feed(self, delta: str) -> list[str]:
        if self._poisoned:
            raise RuntimeError("discard overflowed speech stream and create a fresh chunker")
        if not delta:
            return []
        if len(self._buf) + len(delta) > _MAX_PENDING_CHARS:
            # An unterminated <think> or code fence otherwise accumulates
            # indefinitely while withholding all output. Fail closed for this
            # utterance: never resume a poisoned stream or expose hidden text.
            self._buf = ""
            self._poisoned = True
            raise ValueError("speech stream exceeded bounded pending buffer")
        self._buf += delta
        out: list[str] = []
        while True:
            cut = self._next_cut()
            if cut is None:
                break
            self._release(cut, out)
        return out

    def flush(self) -> list[str]:
        """Call when the stream ends: whatever is left is the last chunk."""
        if self._poisoned:
            raise RuntimeError("discard overflowed speech stream and create a fresh chunker")
        out: list[str] = []
        while True:
            cut = self._next_cut()
            if cut is None:
                break
            self._release(cut, out)
        self._release(len(self._buf), out)
        self._buf = ""
        return out

    @property
    def pending(self) -> str:
        return self._buf

    # -- internals --------------------------------------------------------------------------
    def _release(self, cut: int, out: list[str]) -> None:
        piece, self._buf = self._buf[:cut], self._buf[cut:].lstrip()
        clean = speakable(piece)
        if clean and _has_words(clean):
            out.append(clean)
            self._emitted += 1

    def _hidden_region(self) -> bool:
        """True while the buffer ends inside an unfinished <think> block or code fence."""
        # Most voice tokens contain neither reasoning tags nor code fences.
        # Avoid allocating a lowercase copy of each growing plain-text buffer.
        if "<" not in self._buf and "`" not in self._buf:
            return False
        low = self._buf.lower()
        if low.rfind("<think>") > low.rfind("</think>"):
            return True
        return self._buf.count("```") % 2 == 1

    def _next_cut(self) -> int | None:
        buf = self._buf
        if not buf or self._hidden_region():
            return None
        eager = self.first_eager and self._emitted == 0
        n = len(buf)
        # The regex skips protected text as one token. Iterating the matches
        # also avoids redoing a Python character-by-character scan every time
        # the model emits another 1-4 character delta.
        end_of_punctuation = 0
        for found in _BOUNDARY_OR_HIDDEN.finditer(buf):
            i = found.start()
            if i < end_of_punctuation:
                continue  # remaining punctuation or closing quotes in a run
            ch = buf[i]
            if ch == "\n":
                if _has_words(buf[:i]):
                    return i + 1
            elif ch in TERMINATORS:
                j = i + 1
                while j < n and buf[j] in TERMINATORS:      # "?!", "..."
                    j += 1
                while j < n and buf[j] in CLOSERS:
                    j += 1
                if self._is_sentence_end(buf, i, j, eager):
                    return j
                end_of_punctuation = j
        if eager and self.first_clause_words:
            cut = self._first_clause_cut(buf)
            if cut is not None:
                return cut
        if eager and self.first_soft_words:
            cut = self._first_soft_cut(buf)
            if cut is not None:
                return cut
        if n > self.max_chars:
            return self._forced_cut(buf)
        return None

    def _is_sentence_end(self, buf: str, dot: int, after: int, eager: bool) -> bool:
        if not _has_words(buf[:dot]):
            return False
        at_end = after >= len(buf)
        single_dot = buf[dot] == "." and not (dot + 1 < len(buf) and buf[dot + 1] in TERMINATORS)
        if single_dot:
            word = _word_before(buf, dot)
            if word in ABBREVIATIONS or (len(word) == 1 and word.isalpha() and word not in {"i", "a"}):
                return False
            if at_end and (word[-1:].isdigit() or "." in word):
                return False          # may still become "3.5" or "main.py": wait for the next character
        if not at_end:
            return buf[after].isspace()
        # Nothing after the punctuation yet. Only the eager first chunk acts on that, because speed
        # matters most there; later chunks wait for the next character (flush() ends the last one).
        return eager

    def _first_clause_cut(self, buf: str) -> int | None:
        for i, ch in enumerate(buf):
            if ch in CLAUSE_BREAKS and i + 1 < len(buf) and buf[i + 1].isspace():
                head = buf[:i]
                if len(head) >= self.first_clause_chars and len(head.split()) >= self.first_clause_words:
                    return i + 1
        return None

    def _first_soft_cut(self, buf: str) -> int | None:
        """Position in front of the last linking word once the opening sentence is long and unpunctuated."""
        words = list(re.finditer(r"\S+", buf))
        complete = len(words) if buf[-1:].isspace() else len(words) - 1     # the last word may still be growing
        if complete <= self.first_soft_words:
            return None
        for index in range(min(complete, self.first_soft_words + 1) - 1, 3, -1):
            if words[index].group().lower() in SOFT_BREAK_WORDS:
                return words[index].start()
        return None

    def _forced_cut(self, buf: str) -> int:
        window = buf[:self.max_chars]
        for marks in (CLAUSE_BREAKS, " "):
            best = max((window.rfind(m) for m in marks), default=-1)
            if best > self.max_chars // 3:
                return best + 1
        return self.max_chars