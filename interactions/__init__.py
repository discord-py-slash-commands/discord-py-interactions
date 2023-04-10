"""
interactions.py

Easy, simple, scalable and modular: a Python library for interactions.

To see the documentation, please head over to the link here:
    https://interactionspy.rtfd.io/en/latest for ``stable`` builds.
    https://interactionspy.rtfd.io/en/unstable for ``unstable`` builds.

(c) 2021 interactions-py.
"""
from warnings import warn

from .client import *  # noqa isort: skip
from .api import *  # noqa: F401 F403
from .base import *  # noqa: F401 F403
from .utils import *  # noqa: F401 F403

warn(
    "The v4 is now deprecated and won't be supported in the future. Please, migrate to v5. https://github.com/interactions-py/interactions.py",
    DeprecationWarning,
    stacklevel=2,
)
