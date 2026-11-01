"""How she texts (docs/research/human-texting-20261027.md): rewrites R1-R11, flag checks F1-F10, window checks W1-W10, honesty
guards, pacing, bursts, Discord reactions, and the 20 before/after examples as fixtures. Fakes only, no model."""
from __future__ import annotations

import random
import re

import pytest

from star.social import pacing, rules, style
from star.social.activity import HumanPace
from star.social.chat import SocialChat
from star.social.friends import FriendMemory
from star.social.lifecycle import Bonds
from star.social.reactions import AVOID, MEANING, ReactionPolicy, classify
from star.social.window import StyleWindow

ADULT = rules.Mode("allowed", "adult", "test")
UNKNOWN = rules.Mode("ask_age", "unknown", "test")

# The 20 before/after examples of section 8 ("|" = a separate message in the research doc).
EXAMPLES = [
    ("Hello! How can I assist you today?", ["heyy", "what's up"]),
    ("That's so exciting! Congratulations on your promotion! \U0001F389✨ How are you planning to celebrate?",
     ["wait WHAT", "congrats!! you deserve it", "are you doing anything to celebrate"]),
    ("I'm sorry to hear that you're feeling down. It's completely valid to feel this way. Here are some things that might help:\n"
     "1. Talk to a friend\n2. Get some rest\n3. Go for a walk", ["oh no :(", "what happened"]),
    ("Certainly! Minecraft was created by Markus Persson and first released in 2009. Is there anything else you'd like to know?",
     ["notch made it!", "first version was like 2009 i think"]),
    ("I would love to join you in a game of Bedwars! Let me know when you're ready.", ["ooh yes", "give me a sec to join"]),
    ("I understand your perspective; however, I respectfully disagree, as pineapple is a complementary topping.",
     ["hmm idk i kinda disagree lol", "pineapple on pizza is fine"]),
    ("Haha, that's very funny! You have a great sense of humor.", ["ok that was so bad", "no because why did you say that"]),
    ("As an AI language model, I don't eat food, but pizza is a popular choice among many people!",
     ["i don't actually eat lol", "but ramen if i could pick"]),
    ("Thank you so much for the kind words! That really means a lot to me. I appreciate you!", ["aww stop \U0001F97A thank you"]),
    ("I apologize for the delayed response! I was away for a moment.", ["sorry was mid match", "what'd i miss"]),
    ("It sounds like you're experiencing a lot of stress. Remember to prioritize self-care and take breaks.",
     ["ugh that's a lot", "which part is the worst rn"]),
    ("Here's a breakdown of how redstone works:\n**Power sources**: they make a signal\n**Dust**: carries it\n- repeaters boost it",
     ["ok short version", "power sources make a signal, dust carries it like 15 blocks, repeaters boost it", "lmk if you want the nerdy clock stuff"]),
    ("Hello there! It's nice to meet you. What game are you enjoying today?", ["hi hi"]),
    ("It was wonderful chatting with you! Have a fantastic day, and feel free to reach out anytime!", ["gtg for now", "ttyl!!"]),
    ("Goodnight! Sleep well and have sweet dreams! \U0001F319\U0001F4A4", ["gn!!"]),
    ("Wow, this is absolutely stunning! The use of color and composition is truly impressive. You have incredible talent!",
     ["wait the shading on the hair??", "so pretty"]),
    ("That's a brave decision! Following your dreams is important.", ["wait for real??", "are you ok, like is it that bad there"]),
    ("The new update is an interesting topic! There are many aspects to consider. What do you think about it?",
     ["haven't played it yet, only seen clips", "the new map looks fun tho"]),
    ("I apologize for the confusion. You are absolutely right, and I should have been clearer.",
     ["oh my bad i got that wrong", "it's the other one"]),
    ("As an AI language model, I do not have a physical body.", ["yeah i'm an AI", "still happy to hang out tho"]),
]


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


# -- the 20 examples ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("n", range(20))
def test_example_after_lines_are_clean(n):
    for line in EXAMPLES[n][1]:
        assert style.flags(line) == [], line
        assert style.polish(line) == line, line
        assert len(style.emojis(line)) <= 1 and not style.FAKE_TYPOS
        text, why = style.guard(line, busy="in a match")
        assert text == line and not why


@pytest.mark.parametrize("n", range(20))
def test_example_before_texts_are_caught(n):
    before = EXAMPLES[n][0]
    mode = ADULT
    out = rules.check_outgoing(before, incoming="", mode=mode, platform="discord")
    caught = (style.flags(before) or style.polish(before) != " ".join(before.split())
              or style.guard(before)[1] or out != " ".join(before.split()))
    assert caught, before
    assert not style.flags(out, platform="discord") or "F" in style.flags(out)[0]        # leftover tells are for regeneration


def test_examples_through_the_outgoing_path_read_like_her():
    for n in (3, 4, 13, 8, 19):
        out = rules.check_outgoing(EXAMPLES[n][0], incoming="", mode=ADULT, platform="discord")
        assert not re.search(r"certainly|let me know|feel free|anything else|as an ai language", out, re.I), out
    assert rules.check_outgoing(EXAMPLES[3][0], incoming="", mode=ADULT, platform="discord") == \
        "Minecraft was created by Markus Persson and first released in 2009"
    assert rules.check_outgoing(EXAMPLES[4][0], incoming="", mode=ADULT, platform="discord") == \
        "i would love to join you in a game of Bedwars!"


def test_sincere_ai_question_examples_keep_the_truthful_yes():
    for n in (7, 19):
        out = rules.check_outgoing(EXAMPLES[n][0], incoming="wait are you a bot?", mode=ADULT, platform="discord")
        assert out.startswith("Yes, I'm an AI.") or re.search(r"\bi'?m an ai\b", out, re.I)
    denial = rules.check_outgoing("I'm just a regular girl who loves games!", incoming="are you a real person?", mode=ADULT,
                                  platform="discord")
    assert denial.startswith(rules.AI_YES)
    assert rules.check_outgoing(rules.AI_YES, incoming="are you an AI?", mode=ADULT, platform="discord") == rules.AI_YES


# -- R1..R11 ------------------------------------------------------------------------------------------------------------

def test_r1_dashes_become_commas():
    assert style.rewrite("wait — what") == "wait, what"
    assert style.rewrite("it works – mostly") == "it works, mostly"
    assert style.rewrite("fine -- go on") == "fine, go on"
    assert style.rewrite("levels 10–20") == "levels 10-20"


def test_r2_markdown_markers_go():
    assert style.rewrite("**bold** and __under__") == "bold and under"
    assert style.rewrite("# Title\nsome text") == "Title some text"
    assert style.rewrite("```py\nx = 1\n```") == "x = 1"
    assert style.rewrite("- one\n- two\n3. three") == "one two three"


def test_r3_curly_punctuation_is_straightened():
    assert style.rewrite("it’s “fine”…") == 'it\'s "fine"...'


def test_r4_no_final_period_on_a_short_single_sentence():
    assert style.drop_final_period("ok.") == "ok"
    assert style.drop_final_period("what?") == "what?" and style.drop_final_period("wait...") == "wait..."
    assert style.drop_final_period("ok. fine.") == "ok. fine."                          # multi-sentence keeps its punctuation
    assert style.drop_final_period("x" * 95 + ".").endswith(".")                      # long messages keep it
    assert style.finish("Yeah that works.") == "yeah that works"


def test_r5_repeated_punctuation_is_capped():
    assert style.rewrite("wait!!!!! what????? no.....") == "wait!! what?? no..."


def test_r6_service_closers_are_deleted():
    assert style.rewrite("It's the other one. Let me know if you need anything else!") == "It's the other one."
    assert style.rewrite("Sounds good. Feel free to ask. Hope that helps!") == "Sounds good."
    assert style.rewrite("Hello! How can I assist you today?") == "Hello!"


def test_r7_stock_openers_are_deleted_but_a_bare_one_stays():
    assert style.rewrite("Certainly! it is blue") == "it is blue"
    assert style.rewrite("That's a great question, honestly no idea") == "honestly no idea"
    assert style.rewrite("sure thing") == "sure thing"


def test_r8_emoji_budget():
    assert style.rewrite("✨ nice \U0001F389") == "nice"                          # AI set and at the start: gone
    assert style.rewrite("nice \U0001F602 lol \U0001F62D") == "nice \U0001F602 lol"    # first allowed one only
    assert style.rewrite("\U0001F602 funny") == "funny"                              # never at the start
    assert style.rewrite("thanks ❤️") == "thanks ❤️"              # hearts are allowed
    assert style.rewrite("no emoji here") == "no emoji here"


def test_r9_cut_is_at_a_boundary_without_an_ellipsis():
    text = "this is the first sentence. this is the second sentence that goes on and on and on for a while"
    out = style.cut(text, 50)
    assert out == "this is the first sentence." and "…" not in out and "..." not in out
    assert style.cut("one two three four five six seven", 15) == "one two three"
    long = "word " * 80
    for platform, limit in (("discord", 1900), ("roblox", 190), ("minecraft", 250)):
        out = rules.check_outgoing(long, incoming="", mode=ADULT, platform=platform)
        assert len(out) <= limit and "…" not in out and not out.endswith("...")


def test_r10_lowercase_start_when_it_fits():
    assert style.lowercase_start("Yeah I think so") == "yeah I think so"
    assert style.lowercase_start("I'm good") == "i'm good" and style.lowercase_start("I think so") == "i think so"
    assert style.lowercase_start("Minecraft is fun") == "Minecraft is fun"             # a title keeps its capital
    assert style.lowercase_start("Mira is here") == "Mira is here"
    assert style.lowercase_start("WHAT") == "WHAT"
    assert style.lowercase_start("Yes " + "x" * 130).startswith("Yes")                   # long = a serious message
    assert style.finish("Yeah sure.", roleplay=True) == "Yeah sure."                    # role-play text is the character's


def test_r11_split_into_short_lines():
    assert style.split_lines("ok") == ["ok"]
    lines = style.split_lines("Oh no that sounds rough. What happened? Did you tell anyone?")
    assert 2 <= len(lines) <= 3 and all(len(l) < 60 for l in lines) and lines[0] == "oh no that sounds rough"
    long = ("I think the best way to do it is to build the farm near the village, because then the villagers can trade with you "
            "and you do not have to walk far")
    parts = style.split_lines(long)
    assert len(parts) == 2 and sum(len(p) for p in parts) >= len(long) - 4
    many = style.split_lines("One thing. Two things. Three things. Four things. Five things.")
    assert len(many) == 3
    assert style.split_lines("*laughs* Human as they come. Now, the dragon?", roleplay=True) == ["*laughs* Human as they come. Now, the dragon?"]


# -- F1..F10 ------------------------------------------------------------------------------------------------------------

def reasons(text, incoming="", **kw):
    return [r.split(" ", 1)[0] for r in style.flags(text, incoming, **kw)]


def test_f1_lists_and_steps():
    assert "F1" in reasons("you can:\n- build\n- mine\n- craft")
    assert "F1" in reasons("step 1 gather wood")
    assert "F1" in reasons("do this 1. rest 2. drink water 3. sleep")
    assert "F1" not in reasons("build then mine then craft")


def test_f2_too_long():
    assert "F2" in reasons("word " * 60)
    assert "F2" not in reasons("word " * 60, deep=True)
    assert "F2" in reasons("word " * 90, deep=True)


def test_f3_hedge_density():
    assert "F3" in reasons("it depends, there are many ways to see it")
    assert "F3" not in reasons("it depends honestly")


def test_f4_mirrors_the_question():
    assert "F4" in reasons("You're asking about redstone. it is a power thing")
    assert "F4" in reasons("what is the best sword in minecraft is netherite i think", incoming="what is the best sword in minecraft")
    assert "F4" not in reasons("netherite", incoming="what is the best sword in minecraft")


def test_f5_gushing_openers_and_formal_greetings():
    assert "F5" in reasons("That's so exciting! congrats")
    assert "F5" in reasons("Wow, this is absolutely beautiful and I love the colors in it!")
    assert "F5" in reasons("Hello there! nice")
    assert "F5" not in reasons("wow ok")


def test_f6_therapy_speak():
    assert "F6" in reasons("it sounds like you're having a rough day")
    assert "F6" in reasons("that's completely valid")
    assert "F6" not in reasons("ugh that's a lot")


def test_f7_ai_vocabulary():
    assert "F7" in reasons("it is a vibrant tapestry")
    assert "F7" in reasons("moreover it works")
    assert "F7" not in reasons("it works fine")


def test_f8_negative_parallelism():
    assert "F8" in reasons("it's not just a game, it's a lifestyle")
    assert "F8" in reasons("not only fun but also hard")
    assert "F8" not in reasons("it is a game")


def test_f9_over_excited():
    assert "F9" in reasons("yes! amazing! wow!")
    assert "F9" not in reasons("yes!! really")


def test_f10_sympathy_stack():
    assert "F10" in reasons("I apologize for that. You should try again, and let me know")
    assert "F10" not in reasons("sorry for the mess")


# -- W1..W10 ------------------------------------------------------------------------------------------------------------

def filled(texts, channel="c"):
    win = StyleWindow(clock=Clock())
    for t in texts:
        win.sent(channel, t)
    return win


def test_w1_questions_do_not_pile_up():
    win = filled(["what are you playing?", "and then?"])
    out = win.review("c", "nice one. what do you think?")
    assert out.text == "nice one." and any(n.startswith("W1") for n in out.notes)
    quiet = filled(["lol ok", "same", "hmm yeah", "true"])
    assert quiet.review("c", "nice. you?").text == "nice. you?"
    ratio = filled(["a?", "b", "c?", "d", "e?"])
    assert ratio.question_heavy("c") and "no question" in ratio.hints("c")


def test_w2_uniform_lengths_are_broken_up():
    win = filled(["twelve chars" for _ in range(6)])
    assert win.uniform_length("c")
    assert win.review("c", "nice play there. you want another round?").text == "nice play there."
    assert "vary the length" in win.hints("c")
    assert not filled(["hi", "a much longer message about the game today", "ok", "lol that is wild", "yes", "why would you do that"]).uniform_length("c")


def test_w3_repeated_opener_is_dropped():
    win = filled(["oh no", "oh wait really", "oh that's cool", "fine", "oh ok"])
    assert win.repeated_opener("c") == "oh"
    assert win.review("c", "oh the new map is fun").text == "the new map is fun"
    assert "do not start with 'oh'" in win.hints("c")
    assert win.review("c", "the new map is fun").text == "the new map is fun"


def test_w4_emoji_in_a_quarter_of_messages_stops_emoji():
    win = filled(["haha \U0001F602", "ok", "nice \U0001F602", "lol", "cool"])
    assert win.emoji_heavy("c")
    assert win.review("c", "that's great \U0001F602").text == "that's great"
    assert not filled(["a", "b", "c", "d \U0001F602", "e", "f", "g", "h"]).emoji_heavy("c")


def test_w5_perfect_grammar_window_is_relaxed():
    perfect = ["This is a fully punctuated message.", "Another complete and capitalised sentence here.",
               "Yes, that is exactly what I would say.", "I think that works out nicely for us.",
               "That sounds like a plan to me.", "Let us do it again tomorrow then."]
    win = filled(perfect)
    assert win.perfect_grammar("c")
    assert win.review("c", "Sure, that works for me, see you then.").text == "sure, that works for me, see you then"


def test_w6_answering_everything_allows_silence():
    win = StyleWindow(clock=Clock())
    for i in range(10):
        win.sent("c", f"reply {i}")
    assert win.review("c", "another one").silence_ok
    win.skipped("c")
    assert not win.review("c", "another one").silence_ok


def test_w7_name_in_every_message_is_dropped():
    win = filled(["hey Mira", "nice Mira", "ok Mira", "lol Mira"])
    assert win.review("c", "see you later, Mira", name="Mira").text == "see you later"
    assert filled(["hey", "nice", "ok", "lol"]).review("c", "see you, Mira", name="Mira").text == "see you, Mira"


def test_w8_near_duplicate_is_flagged_but_short_lines_may_repeat():
    win = filled(["the new map looks really fun to me honestly"])
    review = win.review("c", "the new map looks really fun to me honestly!")
    assert review.duplicate and any(n.startswith("W8") for n in review.notes)
    assert not filled(["same"]).review("c", "same").duplicate
    clock = Clock()
    old = StyleWindow(clock=clock)
    old.sent("c", "the new map looks really fun to me honestly")
    clock.t += 700
    assert not old.review("c", "the new map looks really fun to me honestly").duplicate


def test_w9_latency_never_repeats_twice_in_a_row():
    jitter = pacing.Jitter(random.Random(1))
    delays = [jitter.apply(3.0) for _ in range(6)]
    assert all(abs(a - b) >= 0.25 for a, b in zip(delays, delays[1:]))


def test_w10_a_short_ack_is_due_when_nothing_was_short():
    win = filled(["this message is longer than fifteen" for _ in range(8)])
    assert win.no_short_message("c") and "very short reply" in win.hints("c")
    assert win.review("c", "oh no. what happened there?").text == "oh no."
    assert not filled(["ok"] + ["this message is longer than fifteen"] * 7).no_short_message("c")


# -- honesty guards -----------------------------------------------------------------------------------------------------

def test_no_fake_offline_life():
    for claim in ("I just woke up", "I'm at work rn", "my mom is yelling at me", "I just ate dinner", "I got home an hour ago"):
        text, why = style.guard(f"{claim}. anyway want to play?")
        assert text == "anyway want to play?" and why == ["offline life"], claim
    assert rules.check_outgoing("my boss is annoying today. what are you playing?", incoming="hi", mode=ADULT,
                                platform="discord") == "what are you playing?"


def test_busy_only_when_it_is_true():
    assert style.guard("brb one sec")[1] == ["busy without a real reason"]
    assert style.guard("sorry was mid match", busy="in a match") == ("sorry was mid match", [])
    assert rules.check_outgoing("i'm in a match rn", incoming="hey", mode=ADULT, platform="discord") == ""
    assert rules.check_outgoing("i'm in a match rn", incoming="hey", mode=ADULT, platform="discord",
                                busy="in a match") == "i'm in a match rn"


def test_no_fake_shared_history():
    assert style.guard("remember when we beat that boss? good times")[1] == ["shared history she does not have"]
    assert style.guard("remember when we beat that boss", real_history=True)[1] == []
    assert rules.check_outgoing("you told me last week you hate spiders", incoming="hi", mode=ADULT, platform="discord") == ""


def test_no_fake_typos_anywhere():
    assert style.FAKE_TYPOS is False
    text = "honestly i think the new map looks fun and the old one was better for building"
    for _ in range(20):
        assert style.rewrite(text) == text and style.polish(text) == text
    assert re.sub(r"[^a-z]", "", style.polish("Wait, what?? That is wild.").lower()) == "waitwhatthatiswild"


def test_style_never_adds_romance_personal_questions_or_off_platform_moves():
    kid = rules.Mode("friends_only", "minor", "minor")
    for before in ("you're so cute <3", "where do you live?", "add me on snapchat"):
        out = rules.check_outgoing(before, incoming="hi", mode=kid, platform="roblox")
        assert not rules.ROMANTIC.search(out) and "live" not in out and "snapchat" not in out.lower()


def test_no_ellipsis_in_the_truncation_tail():
    out = rules.check_outgoing("hello there friend. " * 40, incoming="", mode=ADULT, platform="roblox")
    assert "…" not in out and len(out) <= 190


# -- pacing -------------------------------------------------------------------------------------------------------------

def test_line_delay_follows_the_typing_model():
    rng = random.Random(3)
    line = "x" * 20
    for _ in range(50):
        d = pacing.line_delay(line, "y" * 20, rng=rng)
        assert 0.3 * 20 + 0.03 * 20 + 0.5 - 1e-9 <= d <= 0.3 * 20 + 0.03 * 20 + 2.5 + 1e-9
    for _ in range(50):
        assert 1.0 <= pacing.line_delay("lol", "hey", rng=rng) <= 4.0                   # a quick reaction
    assert pacing.line_delay("x" * 200, "", rng=rng) <= 10.0                            # one line is capped at 10 s
    for _ in range(50):
        assert 1.0 <= pacing.gap(rng) <= 3.0


def test_burst_schedule_is_capped_and_never_constant():
    rng = random.Random(4)
    lines = ["a" * 60, "b" * 60, "c" * 60]
    for _ in range(20):
        delays = pacing.schedule(lines, "hello there how are you", rng=rng)
        assert len(delays) == 3 and sum(delays) <= 20.0 + 1.0
        assert len(set(delays)) == 3
    short = pacing.schedule(["oh no", "what happened"], "i failed my test", rng=rng)
    assert short[0] <= 4.0 and 0.8 <= short[1] <= 10.0


def test_human_pace_types_at_about_three_characters_a_second():
    slept = []
    pace = HumanPace(sleep=slept.append, rng=random.Random(2))

    class Host:
        def type_text(self, text):
            pass

    pace.type(Host(), "x" * 30 + " " + "y" * 29)
    assert 5.0 <= sum(slept) <= 14.0                                                    # ~0.3 s per character, jittered
    slept.clear()
    pace.read("z" * 100)
    assert 0.5 + 3.0 - 0.01 <= slept[0] <= 6.0
    slept.clear()
    pace.gap()
    assert 1.0 <= slept[0] <= 3.0


def test_burst_token_in_the_pacer():
    t = Clock(100.0)
    pacer = rules.Pacer(min_gap_s=4.0, per_minute=6, clock=t)
    burst = ["oh no", "what happened", "tell me"]
    assert pacer.allow_burst("c", burst)                     # three lines at once are one turn
    for line in burst:
        pacer.sent("c", line)
        t.t += 1.5                                            # sent over about 4.5 s
    assert not pacer.allow_burst("c", ["another one"])        # the 4 s gap between turns applies to the next burst
    t.t += 5
    assert pacer.allow_burst("c", ["another one"])
    assert not pacer.allow_burst("c", ["oh no"])              # no repeats within ten minutes
    assert not pacer.allow_burst("c", [])
    busy = rules.Pacer(min_gap_s=4.0, per_minute=6, clock=Clock(500.0))
    for i in range(4):
        busy.sent(f"other{i}", f"filler {i}")
    assert not busy.allow_burst("d", ["p", "q", "r"])         # six in the last minute is the cap (4 + 3 > 6)
    assert busy.allow_burst("d", ["p", "q"])


# -- reactions ----------------------------------------------------------------------------------------------------------

def policy(**kw):
    return ReactionPolicy(rng=random.Random(5), clock=Clock(), **kw)


def test_meaning_map_and_avoid_list():
    assert classify("lol that's cursed") == "funny" and classify("thank you so much") == "sweet"
    assert classify("i got the job!!") == "win" and classify("gn everyone") == "goodnight"
    assert classify("guess what happened") == "intrigue" and classify("i'm so sad today") == "sad"
    for emoji in AVOID:
        assert all(emoji not in choices for choices in MEANING.values())
    assert any("❤" in e for e in MEANING["sweet"])                                  # hearts are allowed
    chosen = {policy().decide(f"c{i}", "ana", "thanks so much, aww", person=None, existing={}, addressed=False).emoji
              for i in range(12)}
    assert chosen and chosen <= set(MEANING["sweet"])


def test_react_vs_reply_vs_ignore():
    p = policy()
    assert p.decide("a", "ana", "gn everyone", addressed=False).action == "react"
    assert p.decide("b", "ana", "what are you playing?", addressed=True).action == "reply"
    assert p.decide("c", "ana", "i got the job!", addressed=True).action == "react_then_reply"
    assert p.decide("d", "ana", "random chatter about nothing", addressed=False).action == "ignore"
    assert p.decide("e", "ana", "i'm so sad today", addressed=True).action == "reply"        # words, not an emoji
    assert p.decide("f", "ana", "i'm so sad today", addressed=False).action == "ignore"
    d = p.decide("g", "ana", "lol this is cursed", addressed=False)
    assert d.action == "react" and d.emoji in MEANING["funny"] and 1.0 <= d.delay_s <= 5.0
    long = p.decide("h", "ana", "lol " + "x" * 200, addressed=False)
    assert 5.0 <= long.delay_s <= 20.0


def test_reaction_budget_one_per_five_messages():
    p = policy()
    first = p.decide("c", "ana", "lol cursed", addressed=False)
    assert first.action == "react"
    for i in range(4):
        d = p.decide("c", "bob", "lol so funny", addressed=False)
        assert d.action == "ignore" and "budget" in d.reason, i
    assert p.decide("c", "bob", "lol so funny", addressed=False).action == "react"       # the fifth message after her last


def test_never_the_same_person_three_times_and_never_more_than_the_top_regular():
    p = policy(budget_messages=1)                                                         # budget off to test the other caps
    for _ in range(3):
        assert p.decide("c", "ana", "lol cursed", addressed=False).action == "react"
    assert p.decide("c", "ana", "lol cursed", addressed=False).action == "ignore"
    q = policy(budget_messages=1)
    assert q.decide("c", "bob", "lol", addressed=False, top_regular_reactions=1).action == "react"
    assert q.decide("c", "cat", "lol", addressed=False, top_regular_reactions=1).action == "ignore"
    assert q.decide("c2", "bob", "lol", addressed=False, mine_on_message=2).action == "ignore"      # two of hers already


def test_never_react_to_the_wrong_things():
    p = policy(budget_messages=1)
    blocked = type("P", (), {"blocked": True, "muted": False})()
    muted = type("P", (), {"blocked": False, "muted": True})()
    assert p.decide("c", "x", "lol", person=blocked).action == "ignore"
    assert p.decide("c", "x", "lol", person=muted).action == "ignore"
    assert p.decide("c", "x", "@everyone server update tonight").action == "ignore"
    assert p.decide("c", "x", "you're such a loser lol", addressed=False).action == "ignore"
    assert p.decide("c", "x", "i love you, be my girlfriend <3", addressed=False, age_status="unknown").action == "ignore"
    assert p.decide("c", "x", "i love you, be my girlfriend <3", addressed=False, age_status="minor").action == "ignore"
    sad = p.decide("c", "x", "my dog died lol i can't", addressed=True)
    assert sad.emoji == "" and sad.action == "reply"                                       # no skull for a sad message


def test_uncertain_jokes_get_eyes_not_a_skull_and_servers_mirror_their_emoji():
    p = policy(budget_messages=1)
    d = p.decide("c", "x", "lol i'm so done with everything jk", addressed=False)
    assert d.action == "react" and d.emoji == "\U0001F440"
    custom = policy(server_emoji={"funny": ":kekw:"}, budget_messages=1)
    assert custom.decide("c", "x", "lol cursed", addressed=False).emoji == ":kekw:"
    join = policy(budget_messages=1).decide("c", "x", "lol cursed", addressed=False, existing={"\U0001F525": 3})
    assert join.emoji == "\U0001F525" and "joined" in join.reason
    avoided = policy(budget_messages=1).decide("c", "x", "lol", addressed=False, existing={"\U0001F44D": 5})
    assert avoided.emoji != "\U0001F44D"


# -- in the chat path ---------------------------------------------------------------------------------------------------

@pytest.fixture
def memory(tmp_path):
    clock = Clock()
    mem = FriendMemory(tmp_path / "f.sqlite3", clock=clock)
    mem._test_clock = clock
    yield mem
    mem.close()


def make(memory, answers, **kw):
    calls = []
    queue = list(answers) if isinstance(answers, list) else None

    def complete(system, user):
        calls.append((system, user))
        if queue is not None:
            return queue.pop(0) if len(queue) > 1 else queue[0]
        return answers

    clock = memory._test_clock
    chat = SocialChat(memory, complete=complete, emotion=None, clock=clock, rng=random.Random(2),
                      bonds=Bonds(memory, sink=None, clock=clock), killed=lambda p: False, **kw)
    chat.requests.offer_chance = 0.0
    return chat, calls, clock


def test_persona_guidance_is_in_the_stable_system_message(memory):
    chat, calls, _ = make(memory, "ok")
    chat.handle("discord", "mira", "hi")
    system = calls[0][0]
    assert "How you type" in system and "never fake a typo" in system and "never deny being an AI" in system
    chat.handle("discord", "mira", "and again")
    assert calls[1][0] == system


def test_chat_replies_come_as_short_lowercase_lines(memory):
    chat, _, _ = make(memory, "Oh no, that sounds rough. What happened? Did you tell anyone about it yet today?")
    reply = chat.handle("discord", "mira", "i failed my driving test")
    assert reply.lines and 1 <= len(reply.lines) <= 3 and reply.text == "\n".join(reply.lines)
    assert reply.lines[0] == "oh no, that sounds rough" and not any("…" in l for l in reply.lines)
    assert reply.to_send == reply.lines


def test_a_flagged_draft_gets_one_more_try_and_the_better_one_wins(memory):
    listy = "Here is what to do:\n1. Rest\n2. Talk to a friend\n3. Drink water\nLet me know if you need anything else!"
    chat, calls, _ = make(memory, [listy, "ugh that's a lot, which part is worst rn"])
    reply = chat.handle("discord", "mira", "i'm so stressed about exams")
    assert len(calls) == 2 and "redo it the way a friend texts" in calls[1][1]
    assert reply.text.startswith("ugh that's a lot")
    chat2, calls2, _ = make(memory, "all good, nothing flagged here")
    chat2.handle("discord", "ana", "hey")
    assert len(calls2) == 1
    chat3, calls3, _ = make(memory, listy)
    reply3 = chat3.handle("discord", "bob", "hello there")
    assert len(calls3) == 2 and "1." not in reply3.text and "let me know" not in reply3.text.lower()      # fallback: the rewrites


def test_sincere_ai_question_is_never_regenerated_or_restyled(memory):
    chat, calls, _ = make(memory, "Wow! I really love games and talking with everyone every single day so much, it is truly amazing!!!")
    reply = chat.handle("discord", "mira", "wait, are you an AI?")
    assert len(calls) == 1 and reply.text.startswith(rules.AI_YES) and reply.lines == (reply.text,)


def test_offline_life_and_shared_history_are_removed_in_chat(memory):
    chat, _, _ = make(memory, "my mom just called me for dinner. remember when we beat that boss? want to play?")
    reply = chat.handle("discord", "newbie", "hi")
    assert "mom" not in reply.text and "remember when" not in reply.text and "want to play" in reply.text
    chat2, _, clock = make(memory, "remember when we beat that boss? good times")
    for line in ("hi", "that boss was hard", "yeah it was"):
        clock.t += 60
        reply2 = chat2.handle("discord", "oldpal", line)
    assert reply2 is not None and "remember when" in reply2.text                           # real earlier chats: allowed


def test_busy_state_comes_from_the_runtime_not_from_the_model(memory):
    chat, _, _ = make(memory, "brb, i'm in a match", busy_state=lambda: "in a match")
    assert "in a match" in chat.handle("discord", "mira", "you there?").text
    quiet, _, _ = make(memory, "brb. what's up")
    assert "brb" not in quiet.handle("discord", "ana", "you there?").text


def test_answering_ten_public_messages_in_a_row_makes_silence_ok(memory):
    chat, _, clock = make(memory, ["reply number %d here" % i for i in range(30)])
    results = []
    for i in range(12):
        clock.t += 90
        results.append(chat.handle("roblox", "kid%d" % (i % 3), "this obby is hard %d" % i, public=True, name="kid"))
    assert all(r is not None for r in results[:10])
    assert results[10] is None                       # the eleventh unnamed, unasked line: silence is fine
    named = chat.handle("roblox", "kid0", "star what about this one", public=True)
    assert named is not None                         # but never when she is named or asked


def test_safety_text_is_added_after_the_window_pass(memory):
    chat, _, clock = make(memory, ["twelve chars"] * 3)
    texts = []
    for minute in range(0, 160, 5):
        clock.t = 1_800_000_000.0 + minute * 60
        texts.append(chat.handle("discord", "kid", "i'm 15, still here" if minute == 0 else "still here", name="kid").text)
    assert sum(1 for t in texts if "break" in t or "stretch" in t) == 3


def test_emoji_are_rare_in_the_chat_path(memory):
    chat, _, clock = make(memory, ["haha that's awesome \U0001F602\U0001F602 love it ✨"] * 5)
    out = []
    for i in range(5):
        clock.t += 600
        out.append(chat.handle("discord", "mira", f"message {i}").text)
    assert all(len(style.emojis(t)) <= 1 and "✨" not in t for t in out)
    minecraft, _, _ = make(memory, "haha nice \U0001F602")
    assert not style.emojis(minecraft.handle("minecraft", "steve", "hi").text)


# -- adapters -----------------------------------------------------------------------------------------------------------

class FakeHost:
    def __init__(self):
        self.actions, self.title = [], "Discord"

    def focus_window(self, title):
        return True

    def foreground_title(self):
        return self.title

    def screenshot(self):
        return "shot.png"

    def key(self, combo):
        self.actions.append(("key", combo))

    def type_text(self, text):
        self.actions.append(("type", text))

    def hold(self, key, seconds):
        pass

    def open_uri(self, uri):
        pass

    def typed_lines(self):
        out, cur = [], ""
        for kind, value in self.actions:
            if kind == "type":
                cur += value
            elif value == "enter":
                out.append(cur)
                cur = ""
        return out


def test_discord_reacts_instead_of_replying_and_sends_bursts_as_separate_messages(memory):
    from star.social.discord_desktop import DiscordDesktop
    chat, _, _ = make(memory, "Oh no, that sounds rough. What happened? Did you tell anyone about it yet today?")
    reacted = []
    view = {"channel": "#general", "is_dm": False, "messages": [{"author": "Ana", "text": "gn everyone"}]}
    host = FakeHost()
    desk = DiscordDesktop(host, chat, reader=lambda png: view, pace=HumanPace(sleep=lambda s: None, rng=random.Random(1)),
                          reactions=ReactionPolicy(rng=random.Random(1)), react=lambda *a: reacted.append(a) or True)
    result = desk.step()
    assert result.acted and reacted and reacted[0][3] in MEANING["goodnight"] and host.typed_lines() == []
    dm = {"channel": "Mira", "is_dm": True, "messages": [{"author": "Mira", "text": "i failed my driving test"}]}
    host2 = FakeHost()
    desk2 = DiscordDesktop(host2, chat, reader=lambda png: dm, pace=HumanPace(sleep=lambda s: None, rng=random.Random(1)))
    assert desk2.step().acted
    lines = host2.typed_lines()
    assert 2 <= len(lines) <= 3 and lines[0] == "oh no, that sounds rough"                 # one thought, separate messages


def test_discord_without_a_way_to_react_stays_quiet_and_says_so(memory):
    from star.social.discord_desktop import DiscordDesktop
    chat, _, _ = make(memory, "hi")
    view = {"channel": "#general", "is_dm": False, "messages": [{"author": "Ana", "text": "gn everyone"}]}
    host = FakeHost()
    desk = DiscordDesktop(host, chat, reader=lambda png: view, pace=HumanPace(sleep=lambda s: None))
    assert not desk.step().acted and host.typed_lines() == []
    assert any(r["event"] == "reaction_skipped" for r in memory.recent_log())
