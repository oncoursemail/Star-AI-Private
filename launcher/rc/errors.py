"""Problems the RC module reports, in plain words, each with the repair actions the UI can offer.

Every failure that reaches the UI is an `RcError`: a stable `code` (tests and UI logic key on it), a short title, a
sentence that says what happened and what is safe, and a list of repair actions. `detail` carries the raw cause (a
CLI message, an HTTP status) for the log; it is never the only thing the player sees.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# action id -> label shown on the button
ACTIONS: dict[str, str] = {
    "retry": "Try again",
    "install_tools": "Install RC tools",
    "repair_tools": "Repair RC tools",
    "rollback_tools": "Go back to the previous version",
    "start_backend": "Start the RC backend",
    "enable_and_start": "Turn on and start the RC backend",
    "restart_backend": "Restart the RC backend",
    "register_client": "Add this client",
    "rebaseline": "Accept the current files as the new baseline",
    "locate_client": "Locate the client folder",
    "register_launcher": "Choose the client's own launcher",
    "install_from_steam": "Install Rec Room from Steam",
    "use_screen": "Play on screen instead",
    "view_log": "View log",
    "open_vr_help": "Check my VR setup",
}

# code -> (title, message, default actions)
CATALOG: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "tools_missing": (
        "RC tools are not installed",
        "The Metallic RC tools (the part that checks and starts the client) are not on this PC yet. "
        "Installing them does not touch any game.",
        ("install_tools",)),
    "tools_corrupt": (
        "RC tools need repair",
        "Some RC tool files are missing or do not match what was installed. Nothing was started. "
        "Repairing puts back the exact files from the package.",
        ("repair_tools", "view_log")),
    "tools_timeout": (
        "RC tools did not answer",
        "The RC tools took too long, so they were stopped. The game was not touched.",
        ("retry", "repair_tools", "view_log")),
    "tools_bad_output": (
        "RC tools gave an unreadable answer",
        "The RC tools replied with something the launcher could not read. This usually means a mismatched version.",
        ("repair_tools", "view_log")),
    "no_source": (
        "No update source is set",
        "There is no place to get RC tools from yet. Pick a package folder or a release address in the RC settings.",
        ("view_log",)),
    "download_failed": (
        "The download did not finish",
        "The package could not be fetched. Whatever was installed before is untouched.",
        ("retry", "view_log")),
    "hash_mismatch": (
        "The package did not pass its check",
        "The package does not match its published SHA-256, so it was thrown away and not installed.",
        ("retry", "view_log")),
    "package_invalid": (
        "The package is not valid",
        "The package is missing its file list or contains a file it should not. It was not installed.",
        ("view_log",)),
    "disk_space": (
        "Not enough free space",
        "There is not enough free disk space to unpack the package. Free some space and try again.",
        ("retry",)),
    "installation_not_found": (
        "This client is not added yet",
        "The launcher has not registered this Rec Room folder. Adding it only reads the files; it does not change them.",
        ("register_client", "locate_client")),
    "client_missing": (
        "No client found",
        "No Rec Room client was found on this PC. The launcher never downloads the game for you; install it from "
        "Steam or locate a copy you already have.",
        ("install_from_steam", "locate_client")),
    "files_changed": (
        "Client files changed",
        "Some launch files no longer match what was recorded when this client was added. That happens after a game "
        "update or a mod. Nothing was started.",
        ("rebaseline", "locate_client", "view_log")),
    "external_launcher_required": (
        "This client needs its own launcher",
        "This copy has been modified, so starting the game directly would skip its launcher. "
        "Choose the launcher that came with it.",
        ("register_launcher",)),
    "external_launcher_unconfirmed": (
        "Confirm the client's launcher",
        "This will open the client's own launcher (not Metallic's). Confirm to continue.",
        ()),
    "platform_not_supported": (
        "This client needs Windows",
        "Rec Room runs on Windows. The launcher can look at it here but cannot start it.",
        ()),
    "vr_not_ready": (
        "No VR runtime found",
        "No VR runtime was detected (SteamVR or an OpenXR runtime). You can still try VR mode, or play on screen.",
        ("use_screen", "open_vr_help")),
    "launch_failed": (
        "The client did not start",
        "Windows did not start the client. Nothing was changed.",
        ("retry", "view_log")),
    "exited_early": (
        "The client closed right away",
        "The client started but closed within a few seconds. It may be waiting on Steam, an update, or a crash. "
        "Check the log.",
        ("retry", "view_log")),
    "backend_stopped": (
        "The RC backend is not running",
        "Metallic's own RC backend on this PC is stopped. Start it to use Metallic rooms and accounts.",
        ("start_backend",)),
    "backend_disabled": (
        "The RC backend is turned off",
        "Its Windows task was disabled earlier (a stop with auto-start off). Turning it back on makes it start at sign-in again.",
        ("enable_and_start",)),
    "backend_task_missing": (
        "The RC backend is not set up",
        "The Windows task that runs the backend (Metallic-RC-Backend) was not found. "
        "It is created by the RC backend installer.",
        ("view_log",)),
    "backend_conflict": (
        "Something else is using the backend port",
        "The backend port answers, but not as the Metallic RC backend. It was left alone.",
        ("view_log",)),
    "backend_unhealthy": (
        "The RC backend is not answering",
        "The backend process exists but did not report healthy in time.",
        ("restart_backend", "view_log")),
    "backend_start_timeout": (
        "The RC backend did not come up",
        "The start request was sent but the backend did not report healthy within the time limit.",
        ("retry", "view_log")),
    "cancelled": (
        "Cancelled",
        "Stopped at your request. Nothing was left half-done.",
        ()),
    "busy": (
        "Another RC task is running",
        "Wait for it to finish, or cancel it first.",
        ()),
    "bad_request": (
        "That request was not understood",
        "The launcher asked RC for something it does not support.",
        ()),
    "rc_error": (
        "RC reported a problem",
        "The RC tools refused the request.",
        ("view_log",)),
}

# RC CLI error codes (LauncherCatalog.cs / PathRules.cs) -> our codes
RC_CODE_MAP = {
    "installation_not_found": "installation_not_found",
    "verification_failed": "files_changed",
    "external_launcher_required": "external_launcher_required",
    "platform_not_supported": "platform_not_supported",
    "process_start_failed": "launch_failed",
}


@dataclass(eq=False)
class RcError(Exception):
    code: str
    detail: str = ""
    message: str = ""
    actions: list[str] = field(default_factory=list)
    title: str = ""

    def __post_init__(self):
        title, text, actions = CATALOG.get(self.code, CATALOG["rc_error"])
        self.title = self.title or title
        self.message = self.message or text
        if not self.actions:
            self.actions = list(actions)
        Exception.__init__(self, f"{self.code}: {self.detail or self.message}")

    def to_dict(self) -> dict:
        return {"code": self.code, "title": self.title, "message": self.message, "detail": self.detail,
                "actions": [{"id": a, "label": ACTIONS.get(a, a)} for a in self.actions]}


class Cancelled(RcError):
    def __init__(self):
        super().__init__("cancelled")


def from_rc(code: str, message: str) -> RcError:
    """Wrap an error object printed by the RC CLI ({"error": code, "message": text})."""
    mapped = RC_CODE_MAP.get(code, "rc_error")
    err = RcError(mapped, detail=f"{code}: {message}")
    if mapped == "rc_error":
        err.message = message[:400] or err.message  # RC's own sentences are already plain
    return err
