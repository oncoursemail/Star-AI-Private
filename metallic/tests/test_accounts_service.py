"""Metallic accounts rules: sign-in, lockout, refresh rotation, 2FA, recovery, privacy for minors, friends, presence,
invites, news, admin, audit. Uses the real argon2id hasher and ES256 signer with a fake clock."""
from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("argon2")
pytest.importorskip("cryptography")

from metallic.accounts import crypto  # noqa: E402
from metallic.accounts.service import Accounts, Refused  # noqa: E402
from metallic.accounts.store import Store  # noqa: E402

PW = "violet-crow-river-42"


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def cheap_hashing():
    saved = crypto._HASHER, crypto._DUMMY_HASH
    crypto.set_cost(1, 1024)            # the real cost (t=3, 64 MiB) is checked in test_real_cost_is_argon2id
    yield
    crypto._HASHER, crypto._DUMMY_HASH = saved


@pytest.fixture
def env(tmp_path):
    clock = Clock()
    store = Store(":memory:", tmp_path / "audit.jsonl", clock=clock)
    signer = crypto.Signer(crypto.new_signing_key_pem(), clock=clock)
    acc = Accounts(store, signer, crypto.Sealer(os.urandom(32)), clock=clock)
    return acc, clock, tmp_path


def reg(acc, name, band="adult", pw=PW):
    return acc.register(name, pw, name.title(), band, "203.0.113.9")


def claims(acc, tokens):
    return acc.authenticate("Bearer " + tokens["access_token"])


def befriend(acc, a, b):
    acc.friend_request(claims(acc, a), b["account"]["username"], "ip")
    acc.friend_accept(claims(acc, b), a["account"]["username"], "ip")


def test_register_login_and_token_claims(env):
    acc, clock, _ = env
    out = reg(acc, "alex")
    assert len(out["recovery_codes"]) == 10 and out["account"]["role"] == "user"
    c = crypto.verify_jwt(out["access_token"], acc.signer.jwks, now=clock.t)
    assert c["iss"] == "metallic-accounts" and c["aud"] == "metallic" and c["name"] == "alex"
    assert c["minor"] is False and c["amr"] == ["pwd"]
    t = acc.login("ALEX", PW, "ip")                      # usernames are case-insensitive
    assert t["account"]["username"] == "alex"
    with pytest.raises(Refused) as e:
        acc.login("alex", "wrong-password-123", "ip")
    assert e.value.code == "wrong_login"
    with pytest.raises(Refused) as e:
        acc.login("nobody", PW, "ip")
    assert e.value.code == "wrong_login"                 # same answer: no username probing


def test_registration_rules(env):
    acc, _, _ = env
    reg(acc, "taken")
    for name, pw, code in [("taken", PW, "username_taken"), ("ab", PW, "bad_username"), ("admin", PW, "bad_username"),
                           ("bob", "short", "weak_password"), ("bob", "password123", "weak_password"),
                           ("bobby", "bobby-is-great-1", "weak_password"), ("bob", "aaaaaaaaaaaa", "weak_password")]:
        with pytest.raises(Refused) as e:
            acc.register(name, pw, None, "adult", "ip")
        assert e.value.code == code, (name, pw)
    with pytest.raises(Refused):
        acc.register("carl", PW, None, "toddler", "ip")


def test_real_cost_is_argon2id(env):
    acc, _, _ = env
    crypto.set_cost(*crypto.DEFAULT_COST)
    reg(acc, "costly")
    row = acc.s.one("SELECT pw_hash FROM accounts WHERE uname='costly'")
    assert row["pw_hash"].startswith("$argon2id$v=19$m=65536,t=3,p=1$")
    assert acc.login("costly", PW, "ip")


def test_password_is_never_stored_or_logged(env):
    acc, _, tmp = env
    out = reg(acc, "dana")
    assert acc.s.one("SELECT pw_hash FROM accounts WHERE uname='dana'")["pw_hash"].startswith("$argon2id$")
    with pytest.raises(Refused):
        acc.login("dana", "wrong-password-1", "ip")
    dump = "\n".join(str(tuple(r)) for t in ("accounts", "sessions", "recovery_codes", "audit")
                     for r in acc.s.q(f"SELECT * FROM {t}"))
    audit_text = (tmp / "audit.jsonl").read_text()
    for secret in [PW, "wrong-password-1", out["refresh_token"], out["recovery_codes"][0]]:
        assert secret not in dump and secret not in audit_text


def test_lockout_after_five_wrong_then_escalates(env):
    acc, clock, _ = env
    reg(acc, "erin")
    for _ in range(5):
        with pytest.raises(Refused) as e:
            acc.login("erin", "not-the-password", "ip")
        assert e.value.code == "wrong_login"
    with pytest.raises(Refused) as e:
        acc.login("erin", PW, "ip")                       # right password, still locked
    assert e.value.code == "locked" and 0 < e.value.extra["retry_after"] <= 900
    clock.t += 901
    acc.login("erin", PW, "ip")                           # works again and resets the counters
    for _ in range(5):
        with pytest.raises(Refused):
            acc.login("erin", "not-the-password", "ip")
    with pytest.raises(Refused) as e:
        acc.login("erin", PW, "ip")
    assert e.value.extra["retry_after"] <= 900            # reset after the success: first lock again
    clock.t += 901
    for _ in range(5):
        with pytest.raises(Refused):
            acc.login("erin", "not-the-password", "ip")
    with pytest.raises(Refused) as e:
        acc.login("erin", PW, "ip")
    assert 900 < e.value.extra["retry_after"] <= 1800     # second lockout without a success in between: 30 min
    events = [r["event"] for r in acc.s.audit_rows(100)]
    assert events.count("lockout") == 3


def test_failures_outside_window_do_not_add_up(env):
    acc, clock, _ = env
    reg(acc, "finn")
    for _ in range(4):
        with pytest.raises(Refused):
            acc.login("finn", "not-the-password", "ip")
    clock.t += 16 * 60
    with pytest.raises(Refused) as e:
        acc.login("finn", "not-the-password", "ip")
    assert e.value.code == "wrong_login"
    acc.login("finn", PW, "ip")


def test_access_expiry_refresh_rotation_and_reuse_detection(env):
    acc, clock, _ = env
    t1 = reg(acc, "gwen")
    clock.t += 16 * 60
    with pytest.raises(Refused) as e:
        claims(acc, t1)
    assert e.value.code == "signed_out"
    t2 = acc.refresh(t1["refresh_token"], "ip")
    assert t2["refresh_token"] != t1["refresh_token"]
    assert claims(acc, t2)["sid"] == crypto.verify_jwt(t1["access_token"], acc.signer.jwks, now=clock.t - 960)["sid"]
    with pytest.raises(Refused):                          # the old refresh token again: theft signal
        acc.refresh(t1["refresh_token"], "ip")
    with pytest.raises(Refused):                          # ...which ended the whole session
        acc.refresh(t2["refresh_token"], "ip")
    with pytest.raises(Refused):
        claims(acc, t2)
    assert any(r["event"] == "refresh_reuse" for r in acc.s.audit_rows())


def test_refresh_idle_expiry_and_logout(env):
    acc, clock, _ = env
    t = reg(acc, "hana")
    clock.t += 31 * 86400
    with pytest.raises(Refused):
        acc.refresh(t["refresh_token"], "ip")
    t = acc.login("hana", PW, "ip")
    t_other = acc.login("hana", PW, "ip")
    acc.logout(claims(acc, t), "ip")
    with pytest.raises(Refused):
        claims(acc, t)                                    # sign-out is immediate on this service
    with pytest.raises(Refused):
        acc.refresh(t["refresh_token"], "ip")
    assert claims(acc, t_other)                           # other device still signed in
    acc.logout(claims(acc, t_other), "ip", everywhere=True)
    assert acc.introspect(t_other["access_token"]) == {"active": False}


def test_totp_setup_login_replay_and_disable(env):
    acc, clock, _ = env
    t = reg(acc, "ivan")
    c = claims(acc, t)
    with pytest.raises(Refused):
        acc.totp_setup(c, "wrong-password-xx", "ip")
    setup = acc.totp_setup(c, PW, "ip")
    assert setup["uri"].startswith("otpauth://totp/Metallic:ivan?secret=")
    with pytest.raises(Refused):
        acc.totp_confirm(c, "000000", "ip")
    code = crypto.totp_code(setup["secret"], int(clock.t // 30))
    new_codes = acc.totp_confirm(c, code, "ip")["recovery_codes"]
    assert len(new_codes) == 10
    sealed = acc.s.one("SELECT totp_sealed FROM accounts WHERE uname='ivan'")["totp_sealed"]
    assert setup["secret"] not in sealed                  # sealed at rest
    with pytest.raises(Refused) as e:
        acc.login("ivan", PW, "ip")
    assert e.value.code == "otp_required"
    with pytest.raises(Refused) as e:
        acc.login("ivan", PW, "ip", otp=code)             # the code used to confirm cannot be replayed
    assert e.value.code == "wrong_code"
    clock.t += 30
    code2 = crypto.totp_code(setup["secret"], int(clock.t // 30))
    t2 = acc.login("ivan", PW, "ip", otp=code2)
    assert crypto.verify_jwt(t2["access_token"], acc.signer.jwks, now=clock.t)["amr"] == ["pwd", "otp"]
    t3 = acc.login("ivan", PW, "ip", recovery_code=new_codes[0])
    assert t3["account"]["recovery_codes_left"] == 9
    with pytest.raises(Refused):
        acc.login("ivan", PW, "ip", recovery_code=new_codes[0])    # one use only
    clock.t += 30
    acc.totp_disable(claims(acc, t2), PW, crypto.totp_code(setup["secret"], int(clock.t // 30)), "ip")
    assert acc.login("ivan", PW, "ip")["account"]["totp"] is False


def test_wrong_otp_counts_toward_lockout(env):
    acc, clock, _ = env
    t = reg(acc, "jade")
    s = acc.totp_setup(claims(acc, t), PW, "ip")
    acc.totp_confirm(claims(acc, t), crypto.totp_code(s["secret"], int(clock.t // 30)), "ip")
    for _ in range(5):
        with pytest.raises(Refused):
            acc.login("jade", PW, "ip", otp="123456")
    with pytest.raises(Refused) as e:
        acc.login("jade", PW, "ip", otp=crypto.totp_code(s["secret"], int(clock.t // 30) + 1))
    assert e.value.code == "locked"


def test_email_free_recovery_resets_password_and_signs_out(env):
    acc, _, _ = env
    out = reg(acc, "kira")
    new_pw = "brand-new-phrase-77"
    with pytest.raises(Refused):
        acc.recover("kira", "aaaa-bbbb-cccc-dddd", new_pw, "ip")
    res = acc.recover("kira", out["recovery_codes"][3].upper(), new_pw, "ip")   # case and spaces do not matter
    assert res["recovery_codes_left"] == 9
    with pytest.raises(Refused):
        claims(acc, out)
    with pytest.raises(Refused):
        acc.login("kira", PW, "ip")
    acc.login("kira", new_pw, "ip")
    with pytest.raises(Refused):
        acc.recover("kira", out["recovery_codes"][3], "another-phrase-88", "ip")


def test_minor_privacy_defaults_cannot_be_widened(env):
    acc, _, _ = env
    kid = reg(acc, "kiddo", "child")
    teen = reg(acc, "teena", "teen")
    for t in (kid, teen):
        me = t["account"]
        assert me["minor"] is True
        assert me["privacy"] == {"presence_visibility": "friends", "friend_requests_from": "friends_of_friends",
                                 "invites_from": "friends"}
        c = claims(acc, t)
        for key, value in [("presence_visibility", "everyone"), ("friend_requests_from", "everyone")]:
            with pytest.raises(Refused) as e:
                acc.update_privacy(c, {key: value}, "ip")
            assert e.value.code == "not_allowed"
        assert acc.update_privacy(c, {"presence_visibility": "nobody"}, "ip")["privacy"]["presence_visibility"] == "nobody"
    adult = reg(acc, "grownup")
    assert adult["account"]["privacy"]["friend_requests_from"] == "everyone"
    assert acc.update_privacy(claims(acc, adult), {"presence_visibility": "everyone"}, "ip")


def test_strangers_cannot_request_or_invite_minors(env):
    acc, _, _ = env
    kid, stranger, mutual = reg(acc, "kidtwo", "child"), reg(acc, "stranger"), reg(acc, "mutual")
    with pytest.raises(Refused) as e:
        acc.friend_request(claims(acc, stranger), "kidtwo", "ip")
    assert e.value.code == "not_accepting"
    with pytest.raises(Refused):
        acc.invite(claims(acc, stranger), "kidtwo", "RC", "room-1", "ip")
    befriend(acc, kid, mutual)
    befriend(acc, stranger, mutual)                        # now a friend of a friend
    assert acc.friend_request(claims(acc, stranger), "kidtwo", "ip")["state"] == "requested"
    acc.update_privacy(claims(acc, kid), {"friend_requests_from": "nobody"}, "ip")
    other = reg(acc, "otherguy")
    befriend(acc, other, mutual)
    with pytest.raises(Refused):
        acc.friend_request(claims(acc, other), "kidtwo", "ip")


def test_friend_flow_presence_visibility_and_blocks(env):
    acc, clock, _ = env
    a, b, c = reg(acc, "anna"), reg(acc, "ben"), reg(acc, "cleo")
    assert acc.friend_request(claims(acc, a), "ben", "ip")["state"] == "requested"
    assert [x["username"] for x in acc.friends(claims(acc, b))["incoming"]] == ["anna"]
    assert acc.friend_request(claims(acc, b), "anna", "ip")["state"] == "friends"     # mutual request accepts
    acc.set_presence(claims(acc, a), "playing", "RC", "Rec Center", True)
    seen = acc.friends(claims(acc, b))["friends"][0]["presence"]
    assert seen == {"status": "playing", "game": "RC", "detail": "Rec Center", "joinable": True}
    assert acc.profile(claims(acc, c), "anna")["presence"] == {"status": "offline"}   # friends-only default
    acc.update_privacy(claims(acc, a), {"presence_visibility": "everyone"}, "ip")
    assert acc.profile(claims(acc, c), "anna")["presence"] == {"status": "playing", "game": "RC"}  # no room detail
    clock.t += 121
    assert acc.friends(claims(acc, b))["friends"][0]["presence"]["status"] == "offline"   # heartbeat expired
    acc.set_presence(claims(acc, a), "online")
    acc.block(claims(acc, b), "anna", "ip")
    assert acc.friends(claims(acc, b))["friends"] == []
    with pytest.raises(Refused):
        acc.profile(claims(acc, a), "ben")                 # blocked players disappear
    with pytest.raises(Refused):
        acc.friend_request(claims(acc, a), "ben", "ip")
    acc.block(claims(acc, b), "anna", "ip", on=False)
    assert acc.friend_request(claims(acc, a), "ben", "ip")["state"] == "requested"


def test_minor_display_name_hidden_from_strangers(env):
    acc, _, _ = env
    kid, adult = reg(acc, "kidthree", "teen"), reg(acc, "adultx")
    p = acc.profile(claims(acc, adult), "kidthree")
    assert "display_name" not in p and p["presence"] == {"status": "offline"}
    assert "display_name" in acc.profile(claims(acc, kid), "adultx")


def test_invites_only_between_friends_and_expire(env):
    acc, clock, _ = env
    a, b = reg(acc, "inva"), reg(acc, "invb")
    with pytest.raises(Refused):
        acc.invite(claims(acc, a), "invb", "RC", "room-9", "ip")
    befriend(acc, a, b)
    with pytest.raises(Refused):
        acc.invite(claims(acc, a), "invb", "RC", "has spaces and a message", "ip")    # no free text
    inv = acc.invite(claims(acc, a), "invb", "MC", "srv-42", "ip")
    got = acc.invites(claims(acc, b))["incoming"]
    assert [(i["from"], i["game"], i["target"]) for i in got] == [("inva", "MC", "srv-42")]
    assert acc.answer_invite(claims(acc, b), inv["id"], True, "ip") == {"ok": True, "game": "MC", "target": "srv-42"}
    inv2 = acc.invite(claims(acc, a), "invb", "RC", "room-1", "ip")
    clock.t += 16 * 60
    with pytest.raises(Refused):
        acc.answer_invite(claims(acc, acc.login("invb", PW, "ip")), inv2["id"], True, "ip")
    acc.update_privacy(claims(acc, acc.login("invb", PW, "ip")), {"invites_from": "nobody"}, "ip")
    with pytest.raises(Refused):
        acc.invite(claims(acc, acc.login("inva", PW, "ip")), "invb", "RC", "room-1", "ip")


def test_news_roles_owner_code_and_admin(env):
    acc, _, _ = env
    user = reg(acc, "plainuser")
    with pytest.raises(Refused) as e:
        acc.post_news(claims(acc, user), "Hi", "text", None, False, "ip")
    assert e.value.code == "forbidden"
    code = acc.new_owner_code()
    with pytest.raises(Refused):
        acc.register("fakeowner", PW, None, "adult", "ip", owner_code="nope")
    owner = acc.register("theowner", PW, None, "adult", "ip", owner_code=code)
    assert owner["account"]["role"] == "owner"
    with pytest.raises(Refused):
        acc.register("second", PW, None, "adult", "ip", owner_code=code)        # one use
    oc = claims(acc, owner)
    acc.post_news(oc, "RC beta night", "Friday 7 pm.", "RC", True, "ip")
    acc.post_news(oc, "MC update", "New server profile.", "MC", False, "ip")
    assert [n["title"] for n in acc.news(game="RC")] == ["RC beta night"]
    assert acc.news()[0]["pinned"] is True
    acc.admin_action(oc, "plainuser", "set_role", "admin", "ip")
    assert claims(acc, user)["role"] == "admin"           # live on this service
    with pytest.raises(Refused):
        acc.admin_action(claims(acc, user), "theowner", "disable", None, "ip")   # admins cannot touch the owner
    acc.admin_action(oc, "plainuser", "set_age_band", "teen", "ip")
    assert acc.me(claims(acc, user)["sub"])["privacy"]["friend_requests_from"] == "friends_of_friends"
    acc.admin_action(oc, "plainuser", "disable", None, "ip")
    with pytest.raises(Refused):
        claims(acc, user)
    rows = acc.admin_audit(oc, limit=500)
    assert {"admin_set_role", "admin_disable", "news_post", "register", "owner_code_created"} <= {r["event"] for r in rows}


def test_audit_jsonl_lines_are_json(env):
    acc, _, tmp = env
    reg(acc, "auditee")
    with pytest.raises(Refused):
        acc.login("auditee", "nope-nope-nope", "1.2.3.4")
    lines = [json.loads(x) for x in (tmp / "audit.jsonl").read_text().splitlines()]
    assert lines[-1]["event"] == "login" and lines[-1]["ok"] is False and lines[-1]["ip"] == "1.2.3.4"


def test_key_rotation_keeps_old_tokens_verifiable(env):
    acc, clock, _ = env
    old_pem = crypto.new_signing_key_pem()
    old = crypto.Signer(old_pem, clock=clock)
    token = old.sign({"sub": "acct_x"}, 900)
    new = crypto.Signer(crypto.new_signing_key_pem(), old_pem, clock=clock)
    assert len(new.jwks["keys"]) == 2
    assert crypto.verify_jwt(token, new.jwks, now=clock.t)["sub"] == "acct_x"
    with pytest.raises(crypto.TokenError):
        crypto.verify_jwt(token, crypto.Signer(crypto.new_signing_key_pem()).jwks, now=clock.t)
    with pytest.raises(crypto.TokenError):
        crypto.verify_jwt(token[:-4] + "AAAA", new.jwks, now=clock.t)
    with pytest.raises(crypto.TokenError):
        crypto.verify_jwt(token, new.jwks, now=clock.t + 2000)


def test_totp_matches_rfc6238_vector():
    import base64
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert crypto.totp_code(secret, 59 // 30, digits=8) == "94287082"
    assert crypto.totp_code(secret, 1111111109 // 30, digits=8) == "07081804"
