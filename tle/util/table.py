import re
import unicodedata
from collections.abc import Callable

FULL_WIDTH = 1.66667
WIDTH_MAPPING = {'F': FULL_WIDTH, 'H': 1, 'W': FULL_WIDTH, 'Na': 1, 'N': 1, 'A': 1}


def width(s: str) -> int:
    return round(sum(WIDTH_MAPPING[unicodedata.east_asian_width(c)] for c in s))


class Content:
    def __init__(self, *args: object) -> None:
        self.data = args

    def sizes(self) -> list[int]:
        return [width(str(x)) for x in self.data]

    def layout(self, style: 'Style') -> str:
        raise NotImplementedError

    def __len__(self) -> int:
        return len(self.data)


class Header(Content):
    def layout(self, style: 'Style') -> str:
        return style.format_header(self.data)


class Data(Content):
    def __init__(
        self, *args: object, colors: list[Callable[[str], str]] | None = None
    ) -> None:
        super().__init__(*args)
        self.colors = colors

    def layout(self, style: 'Style') -> str:
        if not self.colors:
            return style.format_body(self.data)
        seps, cells = style.format_body_cells(self.data)
        parts = [seps[0]]
        for i, cell in enumerate(cells):
            if i < len(self.colors) and self.colors[i] is not None:
                parts.append(self.colors[i](cell))
            else:
                parts.append(cell)
            parts.append(seps[i + 1])
        return ''.join(parts)


class Line:
    def __init__(self, c: str = '-') -> None:
        self.c = c

    def layout(self, style: 'Style') -> str:
        self.data = [''] * style.ncols
        return style.format_line(self.c)


class Style:
    def __init__(self, body: str, header: str | None = None) -> None:
        self._body = body
        self._header = header or body
        self.ncols = body.count('}')

    def _pad(self, data: tuple[object, ...] | list[str], fmt: str) -> str:
        S = []
        lastc = None
        size = iter(self.sizes)
        datum = iter(data)
        for c in fmt:
            if lastc == ':':
                dstr = str(next(datum))
                sz = str(next(size) - (width(dstr) - len(dstr)))
                if c in '<>^':
                    S.append(c + sz)
                else:
                    S.append(sz + c)
            else:
                S.append(c)
            lastc = c
        return ''.join(S)

    def format_header(self, data: tuple[object, ...]) -> str:
        return self._pad(data, self._header).format(*data)

    def format_line(self, c: str) -> str:
        data = [''] * self.ncols
        return self._pad(data, self._header).replace(':', ':' + c).format(*data)

    def format_body(self, data: tuple[object, ...]) -> str:
        return self._pad(data, self._body).format(*data)

    def format_body_cells(
        self, data: tuple[object, ...]
    ) -> tuple[list[str], list[str]]:
        """Return (separators, cells) for per-cell colored rendering."""
        padded = self._pad(data, self._body)
        parts = re.split(r'(\{[^}]*\})', padded)
        seps: list[str] = []
        cells: list[str] = []
        data_idx = 0
        for part in parts:
            if part.startswith('{') and part.endswith('}'):
                cells.append(part.format(data[data_idx]))
                data_idx += 1
            else:
                seps.append(part)
        return seps, cells

    def set_colwidths(self, sizes: list[int]) -> None:
        self.sizes = sizes


class Table:
    def __init__(self, style: Style) -> None:
        self.style = style
        self.rows: list[Content | Line] = []

    def append(self, row: Content | Line) -> 'Table':
        self.rows.append(row)
        return self

    __add__ = append

    def __repr__(self) -> str:
        sizes = [row.sizes() for row in self.rows if isinstance(row, Content)]
        max_colsize = [max(s[i] for s in sizes) for i in range(self.style.ncols)]
        self.style.set_colwidths(max_colsize)
        return '\n'.join(row.layout(self.style) for row in self.rows)

    __str__ = __repr__
