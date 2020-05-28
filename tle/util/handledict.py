"""
    A case insensitive dictionay with bare minimum functions required for handling usernames.
"""

class HandleDict:
    def __init__(self):
        self._store = {}

    @staticmethod
    def _getlower(key):
        return key.lower() if type(key)==str else key

    def __setitem__(self, key, value):
        # Use the lowercased key for lookups, but store the actual
        # key alongside the value.
        self._store[self._getlower(key)] = (key, value)

    def __getitem__(self, key):
        return self._store[self._getlower(key)][1]

    def __delitem__(self, key):
        del self._store[self._getlower(key)]

    def __iter__(self):
        return (cased_key for cased_key, mapped_value in self._store.values())

    def items(self):
        return dict([value for value in self._store.values()]).items()

    def __repr__(self):
        return str(self.items())
