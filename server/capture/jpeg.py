"""Structural JPEG check: a photo must be a JPEG and must not carry EXIF/XMP/IRB metadata.

Pages are re-captured in the app, so any metadata means the file did not come from it
(and could leak location or device details). The walk goes from SOI to the first SOS.
"""

SOI = 0xD8
EOI = 0xD9
SOS = 0xDA
APP1 = 0xE1
APP13 = 0xED
EXIF_PREFIX = b"Exif\x00\x00"
XMP_PREFIX = b"http://ns.adobe.com/xap/1.0/\x00"

NOT_JPEG = "not_jpeg"
HAS_METADATA = "has_metadata"


def check_jpeg(data: bytes) -> None:
    """Return normally for an acceptable JPEG; raise ValueError(NOT_JPEG | HAS_METADATA) otherwise."""
    if data[:2] != b"\xff\xd8":
        raise ValueError(NOT_JPEG)
    size = len(data)
    pos = 2
    while True:
        if pos >= size or data[pos] != 0xFF:
            raise ValueError(NOT_JPEG)
        while pos < size and data[pos] == 0xFF:  # fill bytes
            pos += 1
        if pos >= size:
            raise ValueError(NOT_JPEG)
        marker = data[pos]
        pos += 1
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # standalone markers
            continue
        if marker in (0x00, SOI, EOI):  # stuffed zero, nested SOI or EOI before any scan
            raise ValueError(NOT_JPEG)
        if pos + 2 > size:
            raise ValueError(NOT_JPEG)
        length = int.from_bytes(data[pos : pos + 2], "big")
        if length < 2 or pos + length > size:
            raise ValueError(NOT_JPEG)
        payload = data[pos + 2 : pos + length]
        if marker == APP1 and (payload.startswith(EXIF_PREFIX) or payload.startswith(XMP_PREFIX)):
            raise ValueError(HAS_METADATA)
        if marker == APP13:
            raise ValueError(HAS_METADATA)
        if marker == SOS:
            return
        pos += length
