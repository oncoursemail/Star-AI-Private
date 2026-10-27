"""Local motion-mode activities. A mode never manufactures missing avatar artwork."""
from . import control
from .activities import INTEREST, _result


def appearance_mode(ctx, mode: str, *, ctl=control) -> dict:
    from ..home import control as home_control
    if home_control.stopped(ctx.home) or ctx.interrupt.is_set():
        return _result(False, False, "avatar mode change stopped", [])
    if getattr(ctx.executor, "dry_run", False):
        return _result(True, False, f"dry run: would select {mode} avatar motion", [])
    result = ctl.set_mode(mode)
    return _result(True, False, f"selected {result['requested_mode']} motion; matching avatar layers required",
                   [result["note"]])


def appearance_expression(ctx, name: str) -> dict:
    from ..home import control as home_control
    if home_control.stopped(ctx.home) or ctx.interrupt.is_set():
        return _result(False, False, "avatar expression stopped", [])
    if getattr(ctx.executor, "dry_run", False):
        return _result(True, False, f"dry run: would request {name} expression", [])
    from . import emit_expression
    emit_expression(name)
    return _result(True, False, f"requested a short {name} expression; loopback delivery not verified", [])


def register_home_activities(registry) -> None:
    if registry.runtime is None:
        return
    for name, mode in (("normal mode", "normal"), ("cat mode", "cat"), ("puppy mode", "puppy")):
        registry.register(name, INTEREST, lambda ctx, mode=mode: appearance_mode(ctx, mode),
                          f"select {mode} avatar motion; ears and tail need matching painted layers")
    from .expressions import EXPRESSION_NAMES
    for expression in EXPRESSION_NAMES:
        registry.register(f"expression {expression}", INTEREST,
                          lambda ctx, name=expression: appearance_expression(ctx, name),
                          f"request a short {expression} facial expression without changing emotion state")
