"""Byte-level token scanner for the stand-in grammar (test support only)."""

BOM = b"\xef\xbb\xbf"
IDENT_START = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_") | frozenset(range(128, 256))
IDENT_CONT = IDENT_START | frozenset(b"0123456789")


def _char_length(lead):
    return 1 if lead < 0x80 else 2 if lead < 0xE0 else 3 if lead < 0xF0 else 4


def _quoted(data, i, n):
    j = i
    while j < n and data[j] != 0x22:
        j += 2 if data[j] == 0x5C else 1
    return min(n, j + 1)


def tokenize(data):
    tokens, n = [], len(data)
    i = 3 if data.startswith(BOM) else 0
    while i < n:
        c = data[i]
        if c in b" \t\r\n":
            i += 1
        elif data.startswith(b"//", i):
            j = data.find(b"\n", i)
            j = n if j < 0 else j
            tokens.append(("line_comment", i, j))
            i = j
        elif data.startswith(b"/*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                depth += 1 if data.startswith(b"/*", j) else -1 if data.startswith(b"*/", j) else 0
                j += 2 if data[j:j + 2] in (b"/*", b"*/") else 1
            tokens.append(("block_comment", i, j))
            i = j
        elif data.startswith((b'r"', b'r#"', b'br"', b'br#"'), i):
            start = data.index(b"r", i) + 1
            hashes = 0
            while data[start + hashes] == 0x23:
                hashes += 1
            close = data.find(b'"' + b"#" * hashes, start + hashes + 1)
            j = n if close < 0 else close + 1 + hashes
            tokens.append(("literal", i, j))
            i = j
        elif c == 0x22 or data.startswith(b'b"', i):
            j = _quoted(data, i + (1 if c == 0x22 else 2), n)
            tokens.append(("literal", i, j))
            i = j
        elif c == 0x27:
            if data[i + 1:i + 2] == b"\\":
                j = data.find(b"'", i + 3) + 1 or n
                tokens.append(("literal", i, j))
            elif i + 1 < n and data[i + 1 + _char_length(data[i + 1]):i + 2 + _char_length(data[i + 1])] == b"'":
                j = i + 2 + _char_length(data[i + 1])
                tokens.append(("literal", i, j))
            else:
                j = i + 1
                while j < n and data[j] in IDENT_CONT:
                    j += 1
                tokens.append(("lifetime", i, j))
            i = j
        elif c in IDENT_START:
            j = i + 1
            while j < n and data[j] in IDENT_CONT:
                j += 1
            if data[i:j] == b"r" and data[j:j + 1] == b"#" and j + 1 < n and data[j + 1] in IDENT_START:
                j += 2
                while j < n and data[j] in IDENT_CONT:
                    j += 1
            tokens.append(("ident", i, j))
            i = j
        elif c in b"0123456789":
            j = i + 1
            while j < n and (data[j] in IDENT_CONT or data[j] == 0x2E and data[j + 1:j + 2].isdigit()):
                j += 1
            tokens.append(("number", i, j))
            i = j
        else:
            tokens.append(("punct", i, i + 1))
            i += 1
    return tokens
