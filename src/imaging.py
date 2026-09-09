"""Image format detection.

Generation providers return whatever format they like — Imagen returns PNG,
gemini-3-pro-image returns JPEG — so the format is read from the bytes rather
than assumed from a filename.
"""

# (magic prefix, extension, mime type)
_SIGNATURES = [
    (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
    (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
    (b"GIF87a", ".gif", "image/gif"),
    (b"GIF89a", ".gif", "image/gif"),
]

DEFAULT = (".png", "image/png")

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def detect_format(data: bytes) -> tuple[str, str]:
    """Return (extension, mime_type) for the given image bytes."""
    for magic, ext, mime in _SIGNATURES:
        if data.startswith(magic):
            return ext, mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return DEFAULT


def mime_for_path(path) -> str:
    """Return the mime type for a file on disk, read from its contents."""
    with open(path, "rb") as fh:
        return detect_format(fh.read(16))[1]
