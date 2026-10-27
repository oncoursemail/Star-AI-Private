"""Metallic RC inside the launcher. Qt-free; see module.py for the contract with the launcher shell."""
from .errors import RcError
from .module import MODULE_ID, RcModule

__all__ = ["RcModule", "RcError", "MODULE_ID"]
