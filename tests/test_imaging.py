from src.imaging import detect_format, mime_for_path

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 16


def test_detects_png():
    assert detect_format(PNG) == (".png", "image/png")


def test_detects_jpeg_which_gemini_3_pro_image_returns():
    assert detect_format(JPEG) == (".jpg", "image/jpeg")


def test_detects_gif_and_webp():
    assert detect_format(GIF) == (".gif", "image/gif")
    assert detect_format(WEBP) == (".webp", "image/webp")


def test_unknown_bytes_default_to_png():
    assert detect_format(b"not an image at all") == (".png", "image/png")


def test_empty_bytes_do_not_crash():
    assert detect_format(b"") == (".png", "image/png")


def test_mime_for_path_reads_contents_not_extension(tmp_path):
    # A JPEG misnamed .png must still upload as image/jpeg.
    mislabeled = tmp_path / "candidate-027.png"
    mislabeled.write_bytes(JPEG)
    assert mime_for_path(mislabeled) == "image/jpeg"
