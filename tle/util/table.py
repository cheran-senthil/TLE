class Content:
    def __init__(self, *args):
        self.data = args
    def sizes(self):
        return [len(str(x)) for x in self.data]
    def __len__(self):
        return len(self.data)
    
class Header(Content):
    def layout(self, style):
        return style.header.format(*self.data)

class Data(Content):
    def layout(self, style):
        return style.body.format(*self.data)

class Line:
    def __init__(self, c='-'):
        self.c = c
    def layout(self, style):
        fmt = style.header.replace(':', ':'+self.c)
        return fmt.format(*['']*style.ncols)

class Style:
    def __init__(self, body, header=None):
        self._body = body
        self._header = header or body
        self.ncols = body.count('}')

    def _pad(self, fmt):
        S = []
        lastc = None
        size = iter(self.sizes)
        for c in fmt:
            if lastc == ':':
                sz = str(next(size))
                if c in '<>^':
                    S.append(c + sz)
                else:
                    S.append(sz + c)
            else:
                S.append(c)
            lastc = c
        return ''.join(S)

    def apply_padding(self, sizes):
        self.sizes = sizes
        self.body   = self._pad(self._body)
        self.header = self._pad(self._header)

class Table:
    def __init__(self, style):
        self.style = style
        self.rows = []

    def append(self, row):
        self.rows.append(row)
        return self
    __add__ = append

    def __repr__(self):
        sizes = [row.sizes() for row in self.rows if isinstance(row, Content)]
        max_colsize = [max(s[i] for s in sizes) for i in range(self.style.ncols)]
        self.style.apply_padding(max_colsize)
        return '\n'.join(row.layout(self.style) for row in self.rows)
    __str__ = __repr__
