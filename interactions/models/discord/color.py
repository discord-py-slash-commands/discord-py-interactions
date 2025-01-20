import colorsys
import re
from enum import Enum
from random import randint

import attrs

__all__ = (
    "COLOR_TYPES",
    "BrandColors",
    "BrandColours",
    "Color",
    "Colour",
    "FlatUIColors",
    "FlatUIColours",
    "MaterialColors",
    "MaterialColours",
    "RoleColors",
    "RoleColours",
    "process_color",
    "process_colour",
)

COLOR_TYPES = tuple[int, int, int] | list[int] | str | int

hex_regex = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")


@attrs.define(eq=False, order=False, hash=False, init=False)
class Color:
    value: int = attrs.field(repr=True)
    """The color value as an integer."""

    def __init__(self, color: COLOR_TYPES | None = None) -> None:
        color = color or (0, 0, 0)
        if isinstance(color, int):
            self.value = color
        elif isinstance(color, (tuple, list)):
            color = tuple(color)
            self.rgb = color
        elif isinstance(color, str):
            if re.match(hex_regex, color):
                self.hex = color
            else:
                self.value = BrandColors[color].value
        else:
            raise TypeError

    def __str__(self) -> str:
        return self.hex

    # Helper methods

    @staticmethod
    def clamp(x, min_value=0, max_value=255) -> int:
        """Sanitise a value between a minimum and maximum value"""
        return max(min_value, min(x, max_value))

    # Constructor methods

    @classmethod
    def from_rgb(cls, r: int, g: int, b: int) -> "Color":
        """
        Create a Color object from red, green and blue values.

        Args:
            r: The red value.
            g: The green value.
            b: The blue value.

        Returns:
            A Color object.

        """
        return cls((r, g, b))

    @classmethod
    def from_hex(cls, value: str) -> "Color":
        """
        Create a Color object from a hexadecimal string.

        Args:
            value: The hexadecimal string.

        Returns:
            A Color object.

        """
        instance = cls()
        instance.hex = value
        return instance

    @classmethod
    def from_hsv(cls, h: int, s: int, v: int) -> "Color":
        """
        Create a Color object from a hue, saturation and value.

        Args:
            h: The hue value.
            s: The saturation value.
            v: The value value.

        Returns:
            A Color object.

        """
        instance = cls()
        instance.hsv = h, s, v
        return instance

    @classmethod
    def random(cls) -> "Color":
        """Returns random Color instance"""
        # FFFFFF == 16777215
        return cls(randint(0, 16777215))

    # Properties and setter methods

    def _get_byte(self, n) -> int:
        """
        Get the nth byte of the color value

        Args:
            n: The index of the byte to get.

        Returns:
            The nth byte of the color value.

        """
        return (self.value >> (8 * n)) & 255

    @property
    def r(self) -> int:
        """Red color value"""
        return self._get_byte(2)

    @property
    def g(self) -> int:
        """Green color value"""
        return self._get_byte(1)

    @property
    def b(self) -> int:
        """Blue color value"""
        return self._get_byte(0)

    @property
    def rgb(self) -> tuple[int, int, int]:
        """The red, green, blue color values in a tuple"""
        return self.r, self.g, self.b

    @rgb.setter
    def rgb(self, value: tuple[int, int, int]) -> None:
        """Set the color value from a tuple of (r, g, b) values"""
        # noinspection PyTypeChecker
        r, g, b = (self.clamp(v) for v in value)
        self.value = (r << 16) + (g << 8) + b

    @property
    def rgb_float(self) -> tuple[float, float, float]:
        """The red, green, blue color values in a tuple"""
        # noinspection PyTypeChecker
        return tuple(v / 255 for v in self.rgb)

    @property
    def hex(self) -> str:
        """Hexadecimal representation of color value"""
        r, g, b = self.rgb
        return f"#{r:02x}{g:02x}{b:02x}"

    @hex.setter
    def hex(self, value: str) -> None:
        """Set the color value from a hexadecimal string"""
        value = value.lstrip("#")
        # split hex into 3 parts of 2 digits and convert each to int from base-16 number
        self.rgb = tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))

    @property
    def hsv(self) -> tuple[float, float, float]:
        """The hue, saturation, value color values in a tuple"""
        return colorsys.rgb_to_hsv(*self.rgb_float)

    @hsv.setter
    def hsv(self, value) -> None:
        """Set the color value from a tuple of (h, s, v) values"""
        self.rgb = tuple(round(v * 255) for v in colorsys.hsv_to_rgb(*value))


class BrandColors(Color, Enum):
    """
    A collection of colors complying to the Discord Brand specification.

    https://discord.com/branding

    """

    BLURPLE = "#5865F2"
    GREEN = "#57F287"
    YELLOW = "#FEE75C"
    FUCHSIA = "#EB459E"
    RED = "#ED4245"
    WHITE = "#FFFFFF"
    BLACK = "#000000"


class MaterialColors(Color, Enum):
    """
    A collection of material ui colors.

    https://www.materialpalette.com/

    """

    RED = "#F44336"
    PINK = "#E91E63"
    LAVENDER = "#EDB9F5"
    PURPLE = "#9C27B0"
    DEEP_PURPLE = "#673AB7"
    INDIGO = "#3F51B5"
    BLUE = "#2196F3"
    LIGHT_BLUE = "#03A9F4"
    CYAN = "#00BCD4"
    TEAL = "#009688"
    GREEN = "#4CAF50"
    LIGHT_GREEN = "#8BC34A"
    LIME = "#CDDC39"
    YELLOW = "#FFEB3B"
    AMBER = "#FFC107"
    ORANGE = "#FF9800"
    DEEP_ORANGE = "#FF5722"
    BROWN = "#795548"
    GREY = "#9E9E9E"
    BLUE_GREY = "#607D8B"


class FlatUIColors(Color, Enum):
    """
    A collection of flat ui colours.

    https://materialui.co/flatuicolors

    """

    TURQUOISE = "#1ABC9C"
    EMERLAND = "#2ECC71"
    PETERRIVER = "#3498DB"
    AMETHYST = "#9B59B6"
    WETASPHALT = "#34495E"
    GREENSEA = "#16A085"
    NEPHRITIS = "#27AE60"
    BELIZEHOLE = "#2980B9"
    WISTERIA = "#8E44AD"
    MIDNIGHTBLUE = "#2C3E50"
    SUNFLOWER = "#F1C40F"
    CARROT = "#E67E22"
    ALIZARIN = "#E74C3C"
    CLOUDS = "#ECF0F1"
    CONCRETE = "#95A5A6"
    ORANGE = "#F39C12"
    PUMPKIN = "#D35400"
    POMEGRANATE = "#C0392B"
    SILVER = "#BDC3C7"
    ASBESTOS = "#7F8C8D"


class RoleColors(Color, Enum):
    """A collection of the default role colors Discord provides."""

    TEAL = "#1ABC9C"
    DARK_TEAL = "#11806A"
    GREEN = "#2ECC71"
    DARK_GREEN = "#1F8B4C"
    BLUE = "#3498DB"
    DARK_BLUE = "#206694"
    PURPLE = "#9B59B6"
    DARK_PURPLE = "#71368A"
    MAGENTA = "#E91E63"
    DARK_MAGENTA = "#AD1457"
    YELLOW = "#F1C40F"
    DARK_YELLOW = "#C27C0E"
    ORANGE = "#E67E22"
    DARK_ORANGE = "#A84300"
    RED = "#E74C3C"
    DARK_RED = "#992D22"
    LIGHTER_GRAY = "#95A5A6"
    LIGHT_GRAY = "#979C9F"
    DARK_GRAY = "#607D8B"
    DARKER_GRAY = "#546E7A"

    # a certain other lib called the yellows this
    # i honestly cannot decide if they are or not
    # so why not satisfy everyone here?
    GOLD = YELLOW
    DARK_GOLD = DARK_YELLOW

    # aliases
    LIGHT_GREY = LIGHT_GRAY
    LIGHTER_GREY = LIGHTER_GRAY
    DARK_GREY = DARK_GRAY
    DARKER_GREY = DARKER_GRAY


def process_color(color: Color | dict | COLOR_TYPES | None) -> int | None:
    """
    Process color to a format that can be used by discord.

    Args:
        color: The color to process.

    Returns:
        The processed color value.

    """
    if not color:
        return None
    if isinstance(color, Color):
        return color.value
    if isinstance(color, dict):
        return color["value"]
    if isinstance(color, (tuple, list, str, int)):
        return Color(color).value

    raise ValueError(f"Invalid color: {type(color)}")


# aliases
Colour = Color
BrandColours = BrandColors
MaterialColours = MaterialColors
FlatUIColours = FlatUIColors
RoleColours = RoleColors
process_colour = process_color
