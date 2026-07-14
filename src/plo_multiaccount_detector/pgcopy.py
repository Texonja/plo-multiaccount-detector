"""Small PostgreSQL COPY text helpers.

HM2 `.pghembk` files are zip archives containing a PostgreSQL dump. The raw
hand histories live in COPY rows for the `handhistories` table. The text field
uses PostgreSQL COPY escapes such as `\\r\\n`.
"""
from __future__ import annotations


def pg_copy_unescape(value: str | None) -> str | None:
    """Decode a single PostgreSQL COPY text-format field.

    Handles the escape sequences HM2 uses in its database dump. It is intentionally
    conservative: unknown backslash escapes are preserved as the escaped character.
    """
    if value is None or value == r"\N":
        return None

    out: list[str] = []
    i = 0
    n = len(value)
    while i < n:
        ch = value[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue

        if i + 1 >= n:
            out.append("\\")
            i += 1
            continue

        nxt = value[i + 1]
        mapping = {
            "b": "\b",
            "f": "\f",
            "n": "\n",
            "r": "\r",
            "t": "\t",
            "v": "\v",
            "\\": "\\",
        }
        if nxt in mapping:
            out.append(mapping[nxt])
            i += 2
            continue

        # PostgreSQL COPY text can use octal escapes. Rare in HM2 dumps, but cheap
        # to support.
        if nxt in "01234567":
            j = i + 1
            oct_digits: list[str] = []
            while j < n and len(oct_digits) < 3 and value[j] in "01234567":
                oct_digits.append(value[j])
                j += 1
            try:
                out.append(chr(int("".join(oct_digits), 8)))
            except ValueError:
                out.append("\\" + "".join(oct_digits))
            i = j
            continue

        out.append(nxt)
        i += 2

    return "".join(out)


def split_copy_row(line: str, expected_fields: int | None = None) -> list[str | None]:
    """Split and unescape one COPY row.

    COPY text rows are tab-separated. Literal tabs inside fields are escaped as
    `\\t`, so a raw split on tab is safe for the HM2 dump.
    """
    line = line.rstrip("\n")
    if line.endswith("\r"):
        line = line[:-1]
    parts = line.split("\t")
    if expected_fields is not None and len(parts) != expected_fields:
        raise ValueError(f"Expected {expected_fields} COPY fields, got {len(parts)}")
    return [pg_copy_unescape(part) for part in parts]
