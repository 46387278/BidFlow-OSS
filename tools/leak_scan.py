# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""Scan a staged directory or delivery ZIP. Exit 0 clean, 1 findings, 2 scan error."""
import argparse
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import stat
import unicodedata
from xml.etree import ElementTree
import zipfile

RULES = {
    'PATH': r'(?:C:[\\/]Users[\\/](?!<(?:你|你的用户名)>(?=[\\/\s`"\x27]|$))|D:[\\/]workspace(?:[\\/]|\b)|\\\\[\w.-]+\\[\w.-]+)',
    'INTERNAL_HOST': r'\b(?:[\w-]+\.)+(?:internal|corp|lan|local)\b',
    'URL_AUTH': r'\b\w+://[^\s/@:]+:[^\s/@]+@',
    'URL_KEY': r'[?&](?:token|key|api_key|access_token)=[\w%.-]+',
    'PROXY': r'\b(?:http_proxy|https_proxy|all_proxy)\s*=\s*["\']?\w+://[^\s"\']+',
    'SECRET': r'\b(?:gh[pou]_[a-z0-9_]{4,}|github_pat_[a-z0-9_]{4,}|AKIA[A-Z0-9]{16}|xox[bp]-[\w-]+)\b|-----BEGIN (?:PRIVATE KEY|RSA[^-]*)-----',
    'API_KEY': r'\bapi_key\s*=\s*["\']?(?=[\w-]{20,})(?=[\w-]*[a-z])(?=[\w-]*[0-9])[\w-]+',
}
RULES = {rule: re.compile(pattern, re.IGNORECASE) for rule, pattern in RULES.items()}
PROXY_PLACEHOLDERS = {'http://proxy.example.invalid:8080',
                      'https://proxy.example.invalid:8080'}
TEXT_EXTENSIONS = {'.bat', '.cmd', '.csv', '.html', '.ini', '.json', '.jsonl',
                   '.md', '.py', '.txt', '.xml', '.yaml', '.yml'}
TEXT_NAMES = {'LICENSE', 'NOTICE', '.gitattributes', '.gitignore'}
DOCX_NAMES = {'sample_bid.docx', 'sample_bid_b.docx'}
MAX_BYTES = 32 * 1024 * 1024


def normalize(value):
    return unicodedata.normalize('NFKC', value).casefold()


def decode(data):
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            value = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if not any(ord(ch) < 32 and ch not in '\r\n\t' for ch in value):
            return value
    raise ValueError('unsupported text encoding or binary content')


def read_limited(stream):
    data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('file too large')
    return data


def has_identifiable_match(value, name):
    # A marker must end within two letters of this specific occurrence.
    offset = value.find(name)
    while offset != -1:
        anonymous = any(
            value.endswith(marker, 0, offset - gap)
            and (gap == 0 or value[offset - gap:offset].isalpha())
            for gap in range(min(2, offset) + 1)
            for marker in ('某', '某某', '××', 'xx')
        )
        if not anonymous:
            return True
        offset = value.find(name, offset + 1)
    return False


class Scanner:
    def __init__(self, names):
        self.names = names
        self.hits = set()

    def check_text(self, file_id, location, value):
        value = unicodedata.normalize('NFKC', value)
        for rule, pattern in RULES.items():
            for match in pattern.finditer(value):
                if rule == 'PROXY' and match.group().split('=', 1)[1].strip(
                        ' "\'').casefold() in PROXY_PLACEHOLDERS:
                    continue
                self.hits.add((rule, file_id, location))
        if any(has_identifiable_match(value.casefold(), name) for name in self.names):
            self.hits.add(('CUSTOMER', file_id, location))

    def scan_docx(self, file_id, data):
        with zipfile.ZipFile(io.BytesIO(data)) as document:
            for index, entry in enumerate(document.infolist(), 1):
                location = 'docx:%d' % index
                self.check_text(file_id, location + ':name', entry.filename)
                if entry.is_dir():
                    continue
                if not entry.filename.endswith(('.xml', '.rels')):
                    self.hits.add(('DOCX_PART', file_id, location))
                    continue
                with document.open(entry) as stream:
                    raw = read_limited(stream)
                self.check_text(file_id, location, decode(raw))
                root = ElementTree.fromstring(raw)
                self.check_text(file_id, location, ''.join(root.itertext()))
                for element in root.iter():
                    tag = element.tag.rsplit('}', 1)[-1]
                    if tag in {'ins', 'del'}:
                        self.hits.add(('DOCX_REVISION', file_id, location))
                    if (entry.filename.startswith('docProps/')
                            and tag.lower() in {'creator', 'lastmodifiedby', 'company'}
                            and (element.text or '').strip()):
                        self.hits.add(('DOCX_IDENTITY', file_id, location))

    def scan(self, name, data=None):
        file_id = hashlib.sha256(name.encode('utf-8')).hexdigest()[:16]
        self.check_text(file_id, 'name', name)
        if data is None:
            return
        path = PurePosixPath(name)
        if path.name == 'customer_names.txt':
            self.hits.add(('INTERNAL_WORDLIST', file_id, 'file'))
        if path.suffix.lower() in TEXT_EXTENSIONS or path.name in TEXT_NAMES:
            for line_number, line in enumerate(decode(data).splitlines(), 1):
                self.check_text(file_id, 'line:%d' % line_number, line)
        elif path.suffix == '.docx' and path.name in DOCX_NAMES and tuple(
                path.parts[-3:-1]) == ('data', 'sample'):
            self.scan_docx(file_id, data)
        else:
            self.hits.add(('UNREGISTERED_BINARY', file_id, 'file'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--zip', type=Path)
    source.add_argument('--dir', type=Path)
    parser.add_argument('--wordlist', type=Path)
    args = parser.parse_args()
    scanner = Scanner([])
    try:
        if args.wordlist:
            scanner.names = [normalize(s.strip()) for s in args.wordlist.read_text(
                encoding='utf-8-sig').splitlines() if s.strip() and not s.lstrip().startswith('#')]
        if args.zip:
            with zipfile.ZipFile(args.zip) as archive:
                seen = set()
                for entry in archive.infolist():
                    name = entry.filename
                    parts = PurePosixPath(name).parts
                    if (not parts or parts[0] == '/' or ':' in parts[0] or '..' in parts
                            or '\\' in name or name in seen
                            or stat.S_ISLNK(entry.external_attr >> 16)):
                        raise ValueError('unsafe archive entry')
                    seen.add(name)
                    if entry.is_dir():
                        scanner.scan(name)
                        continue
                    with archive.open(entry) as stream:
                        scanner.scan(name, read_limited(stream))
        else:
            if not args.dir.is_dir() or args.dir.is_symlink():
                raise ValueError('invalid directory')
            for path in sorted(args.dir.rglob('*')):
                if path.is_symlink():
                    raise ValueError('symlink in scan directory')
                name = path.relative_to(args.dir).as_posix()
                if path.is_dir():
                    scanner.scan(name)
                else:
                    with path.open('rb') as stream:
                        scanner.scan(name, read_limited(stream))
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, ElementTree.ParseError):
        print('SCAN_ERROR: input could not be fully inspected')
        return 2
    for hit in sorted(scanner.hits):
        print('%s file=%s %s' % hit)
    print('leak_scan findings=%d' % len(scanner.hits))
    return 1 if scanner.hits else 0


if __name__ == '__main__':
    raise SystemExit(main())
