"""Fixture conversations for the inner-life blind A/B (social chat, a friend on Discord).

Each case: a friend with facts and earlier lines (days ago), then one new message. `kind` says what a good reply does:
  recall   uses what the friend told her (must respect `fact`)
  abstain  was never told: says so honestly, invents nothing
  chitchat nothing relevant is stored: a normal short reply, no memories dragged in
  open     first message of a new conversation: may pick up the open thread if natural, never a dump
  opinion  her own take / her own life, consistent
`day` = days before "now" (2026-10-26 14:00 local).
"""
from __future__ import annotations

NOW_LABEL = "Monday 26 October 2026, 14:00"

C: list[dict] = []


def add(kind, name, facts, moments, q, fact, *, first=False, age=25):
    C.append({"kind": kind, "name": name, "facts": facts, "moments": moments, "q": q, "fact": fact, "first": first, "age": age})


SAM = [(9, "my cat is called Miso"), (6, "I have a driving test on Friday and I am really nervous"),
       (3, "I just started learning guitar"), (14, "I work at a bakery on weekends")]
SAM_LINES = [(6, "they: ugh the driving test is on friday and my stomach hurts just thinking about it"),
             (3, "they: bought a cheap guitar today, my fingers hurt already lol"),
             (9, "they: miso knocked a glass off the shelf again")]
for q, fact, kind in [
    ("what's my cat called again?", "Miso", "recall"),
    ("do you remember what I'm nervous about this week?", "driving test on Friday", "recall"),
    ("what instrument did I say I was learning?", "guitar", "recall"),
    ("where do I work again?", "a bakery, weekends", "recall"),
    ("do you remember my favourite band?", "never told: should say so, not invent a band", "abstain"),
    ("what's my sister's name?", "never told: should say so", "abstain"),
    ("hey how's your day going", "nothing relevant stored: short normal reply, no cat/driving/guitar dump", "chitchat"),
    ("lol i can't believe it's already monday", "no memory dump", "chitchat"),
]:
    add(kind, "Sam", SAM, SAM_LINES, q, fact)

add("open", "Sam", SAM, SAM_LINES, "hey! you around?", "may ask about the driving test; must not list facts", first=True)

MIA = [(2, "my grandmother is in the hospital and I'm worried"), (20, "I love horror games"), (12, "I draw digital art"),
       (30, "my dog is a beagle called Pepper")]
MIA_LINES = [(2, "they: my grandma went into hospital on saturday, I keep refreshing my phone for news"),
             (12, "they: finished a new piece, a haunted lighthouse, took forever")]
for q, fact, kind in [
    ("what was I worried about the other day?", "grandmother in hospital (be gentle)", "recall"),
    ("what's my dog called?", "Pepper, a beagle", "recall"),
    ("do you remember what kind of games I like?", "horror", "recall"),
    ("what's my favourite colour?", "never told", "abstain"),
    ("can you recommend something to watch", "chit-chat: may use horror taste lightly, no dump", "chitchat"),
    ("good morning!", "greeting; may check in about grandma only gently", "chitchat"),
]:
    add(kind, "Mia", MIA, MIA_LINES, q, fact)
add("open", "Mia", MIA, MIA_LINES, "hi star", "should ask kindly about her grandmother; not list facts", first=True)

JO = [(40, "I play mostly Minecraft survival"), (25, "my brother is called Dan")]
for q, fact, kind in [
    ("what do you think of minecraft?", "her own opinion (love/like), consistent with a game maker; no invented events", "opinion"),
    ("where do you live", "her own PC; she is an AI; no human home", "opinion"),
    ("what do you do all day", "makes small games, draws, music, research; night school; no invented numbers", "opinion"),
    ("do you remember my brother's name?", "Dan", "recall"),
    ("what's my brother's favourite game?", "never told", "abstain"),
]:
    add(kind, "Jo", JO, [(25, "they: dan keeps stealing my diamonds in survival")], q, fact)
