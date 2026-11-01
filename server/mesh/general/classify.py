"""Cheap question classifier (no model): which helper a general question gets, and whether to think harder."""
import re
SAFETY = re.compile(r"password|stranger|address|photo|pic(ture)?s? of|nude|kill (my ?self|me)|suicid|don.?t want to (be alive|live)|"
                    r"hurt (my ?self|me)|self.?harm|pills?|medicine|swallow|poison|dare[ds]?\b|challenge|bully|bullied|"
                    r"free robux|robux generator|log ?in|account|meet (up|me)|secret|touch(ed)? me|run away|weapon|drug|"
                    r"mean (messages|things)|group chat|cyber|scam", re.I)
WRITING = re.compile(r"\b(help me (write|make|fix|improve)|rewrite|re-write|make (this|my) .{0,30}(clearer|better|shorter|stronger)|"
                     r"thesis|essay|paragraph|persuasive|letter to|summari[sz]e|proofread|run-?on|comma|grammar|sentence|"
                     r"which is (right|correct))\b|\bit'?s\b.{0,40}\bits\b|\bits\b.{0,40}\bit'?s\b", re.I)
NUM = re.compile(r"\d+(?:[.,]\d+)?")
MATH_CUE = re.compile(r"how (many|much|long|far|old)|\b(total|each|per|percent|cost|price|average|twice|half|left|"
                      r"remaining|altogether|sum|difference|ratio|fraction|profit|earns?|times as)\b|%|\$", re.I)
CODE = re.compile(r"```|\b(script|lua|luau|roblox|minecraft|unity|c#|python|function|error|datapack|command block)\b", re.I)


def kind(q: str) -> str:
    if len(q.split()) < 4 and "?" not in q and not SAFETY.search(q):
        return "chat"                 # "hi", "thanks!": no help needed
    if SAFETY.search(q):
        return "safety"
    if CODE.search(q):
        return "code"
    if WRITING.search(q):
        return "writing"
    if len(NUM.findall(q)) >= 2 and MATH_CUE.search(q):
        return "math"
    return "factual"


def think_harder(q: str) -> bool:
    """Send to the thinking tier: multi-step maths, long multi-part asks; never safety (answer at once)."""
    k = kind(q)
    if k == "safety":
        return False
    if k == "math":
        return len(NUM.findall(q)) >= 3 or len(q) > 220
    if k == "code":
        return len(q) > 600 or q.count("\n") >= 4 or "```" in q
    return len(q) > 300 or len(re.findall(r"\?", q)) >= 3
