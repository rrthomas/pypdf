"""Test the pypdf._reader module."""
import io
import time
from io import BytesIO
from pathlib import Path

import pytest

from pypdf import PdfReader
from pypdf._reader import convert_to_int, convertToInt
from pypdf.constants import ImageAttributes as IA
from pypdf.constants import PageAttributes as PG
from pypdf.errors import (
    DeprecationError,
    EmptyFileError,
    FileNotDecryptedError,
    PdfReadError,
    PdfReadWarning,
    WrongPasswordError,
)
from pypdf.generic import (
    ArrayObject,
    Destination,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from . import get_pdf_from_url, normalize_warnings

try:
    from Crypto.Cipher import AES  # noqa: F401

    HAS_PYCRYPTODOME = True
except ImportError:
    HAS_PYCRYPTODOME = False

TESTS_ROOT = Path(__file__).parent.resolve()
PROJECT_ROOT = TESTS_ROOT.parent
RESOURCE_ROOT = PROJECT_ROOT / "resources"
SAMPLE_ROOT = PROJECT_ROOT / "sample-files"


@pytest.mark.parametrize(
    ("src", "num_pages"),
    [("selenium-pypdf-issue-177.pdf", 1), ("pdflatex-outline.pdf", 4)],
)
def test_get_num_pages(src, num_pages):
    src = RESOURCE_ROOT / src
    reader = PdfReader(src)
    assert len(reader.pages) == num_pages


@pytest.mark.parametrize(
    ("pdf_path", "expected"),
    [
        (
            RESOURCE_ROOT / "crazyones.pdf",
            {
                "/CreationDate": "D:20150604133406-06'00'",
                "/Creator": " XeTeX output 2015.06.04:1334",
                "/Producer": "xdvipdfmx (20140317)",
            },
        ),
        (
            RESOURCE_ROOT / "metadata.pdf",
            {
                "/CreationDate": "D:20220415093243+02'00'",
                "/ModDate": "D:20220415093243+02'00'",
                "/Creator": "pdflatex, or other tool",
                "/Producer": "Latex with hyperref, or other system",
                "/Author": "Martin Thoma",
                "/Keywords": "Some Keywords, other keywords; more keywords",
                "/Subject": "The Subject",
                "/Title": "The Title",
                "/Trapped": "/False",
                "/PTEX.Fullbanner": (
                    "This is pdfTeX, Version "
                    "3.141592653-2.6-1.40.23 (TeX Live 2021) "
                    "kpathsea version 6.3.3"
                ),
            },
        ),
    ],
    ids=["crazyones", "metadata"],
)
def test_read_metadata(pdf_path, expected):
    with open(pdf_path, "rb") as inputfile:
        reader = PdfReader(inputfile)
        docinfo = reader.metadata
        assert docinfo is not None
        metadict = dict(docinfo)
        assert metadict == expected
        docinfo.title
        docinfo.title_raw
        docinfo.author
        docinfo.author_raw
        docinfo.creator
        docinfo.creator_raw
        docinfo.producer
        docinfo.producer_raw
        docinfo.subject
        docinfo.subject_raw
        docinfo.creation_date
        docinfo.creation_date_raw
        docinfo.modification_date
        docinfo.modification_date_raw
        if "/Title" in metadict:
            assert metadict["/Title"] == docinfo.title


@pytest.mark.samples()
@pytest.mark.parametrize(
    "pdf_path", [SAMPLE_ROOT / "017-unreadable-meta-data/unreadablemetadata.pdf"]
)
def test_broken_meta_data(pdf_path):
    with open(pdf_path, "rb") as f:
        reader = PdfReader(f)
        with pytest.raises(
            PdfReadError,
            match=(
                "trailer not found or does not point to document "
                "information directory"
            ),
        ):
            reader.metadata


@pytest.mark.parametrize(
    "src",
    [
        RESOURCE_ROOT / "crazyones.pdf",
        RESOURCE_ROOT / "commented.pdf",
    ],
)
def test_get_annotations(src):
    reader = PdfReader(src)

    for page in reader.pages:
        if PG.ANNOTS in page:
            for annot in page[PG.ANNOTS]:
                subtype = annot.get_object()[IA.SUBTYPE]
                if subtype == "/Text":
                    annot.get_object()[PG.CONTENTS]


@pytest.mark.parametrize(
    ("src", "nb_attachments"),
    [
        (RESOURCE_ROOT / "attachment.pdf", 1),
        (RESOURCE_ROOT / "crazyones.pdf", 0),
    ],
)
def test_get_attachments(src, nb_attachments):
    reader = PdfReader(src)

    attachments = {}
    for page in reader.pages:
        if PG.ANNOTS in page:
            for annotation in page[PG.ANNOTS]:
                annotobj = annotation.get_object()
                if annotobj[IA.SUBTYPE] == "/FileAttachment":
                    fileobj = annotobj["/FS"]
                    attachments[fileobj["/F"]] = fileobj["/EF"]["/F"].get_data()
    assert len(attachments) == nb_attachments


@pytest.mark.parametrize(
    ("src", "outline_elements"),
    [
        (RESOURCE_ROOT / "pdflatex-outline.pdf", 9),
        (RESOURCE_ROOT / "crazyones.pdf", 0),
    ],
)
def test_get_outline(src, outline_elements):
    reader = PdfReader(src)
    outline = reader.outline
    assert len(outline) == outline_elements


@pytest.mark.samples()
@pytest.mark.parametrize(
    ("src", "expected_images"),
    [
        ("pdflatex-outline.pdf", []),
        ("crazyones.pdf", []),
        ("git.pdf", ["Image9.png"]),
        pytest.param(
            "imagemagick-lzw.pdf",
            ["Im0.png"],
            marks=pytest.mark.xfail(reason="broken image extraction"),
        ),
        pytest.param(
            "imagemagick-ASCII85Decode.pdf",
            ["Im0.png"],
            marks=pytest.mark.xfail(reason="broken image extraction"),
        ),
        ("imagemagick-CCITTFaxDecode.pdf", ["Im0.tiff"]),
        (SAMPLE_ROOT / "019-grayscale-image/grayscale-image.pdf", ["X0.png"]),
    ],
)
def test_get_images(src, expected_images):
    from PIL import Image

    src_abs = RESOURCE_ROOT / src
    reader = PdfReader(src_abs)

    with pytest.raises(TypeError):
        page = reader.pages["0"]

    page = reader.pages[-1]
    page = reader.pages[0]

    images_extracted = page.images
    assert len(images_extracted) == len(expected_images)
    for image, expected_image in zip(images_extracted, expected_images):
        assert image.name == expected_image
        try:
            fn = f"{src}-test-out-{image.name}"
            with open(fn, "wb") as fp:
                fp.write(image.data)
                assert (
                    image.name.split(".")[-1].upper()
                    == Image.open(io.BytesIO(image.data)).format
                )
        finally:
            try:
                Path(fn).unlink()
            except Exception:
                pass


@pytest.mark.parametrize(
    ("strict", "with_prev_0", "startx_correction", "should_fail", "warning_msgs"),
    [
        (
            True,
            False,
            -1,
            False,
            [
                "startxref on same line as offset",
                "Xref table not zero-indexed. "
                "ID numbers for objects will be corrected.",
            ],
        ),  # all nominal => no fail
        (True, True, -1, True, ""),  # Prev=0 => fail expected
        (
            False,
            False,
            -1,
            False,
            ["startxref on same line as offset"],
        ),
        (
            False,
            True,
            -1,
            False,
            [
                "startxref on same line as offset",
                "/Prev=0 in the trailer - assuming there is no previous xref table",
            ],
        ),  # Prev =0 => no strict so tolerant
        (True, False, 0, True, ""),  # error on startxref, in strict => fail expected
        (True, True, 0, True, ""),
        (
            False,
            False,
            0,
            False,
            ["startxref on same line as offset", "incorrect startxref pointer(1)"],
        ),  # error on startxref, but no strict => xref rebuilt,no fail
        (
            False,
            True,
            0,
            False,
            ["startxref on same line as offset", "incorrect startxref pointer(1)"],
        ),
    ],
)
def test_get_images_raw(
    caplog, strict, with_prev_0, startx_correction, should_fail, warning_msgs
):
    pdf_data = (
        b"%%PDF-1.7\n"
        b"1 0 obj << /Count 1 /Kids [4 0 R] /Type /Pages >> endobj\n"
        b"2 0 obj << >> endobj\n"
        b"3 0 obj << >> endobj\n"
        b"4 0 obj << /Contents 3 0 R /CropBox [0.0 0.0 2550.0 3508.0]"
        b" /MediaBox [0.0 0.0 2550.0 3508.0] /Parent 1 0 R"
        b" /Resources << /Font << >> >>"
        b" /Rotate 0 /Type /Page >> endobj\n"
        b"5 0 obj << /Pages 1 0 R /Type /Catalog >> endobj\n"
        b"xref 1 5\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"trailer << %s/Root 5 0 R /Size 6 >>\n"
        b"startxref %d\n"
        b"%%%%EOF"
    )
    pdf_data = pdf_data % (
        pdf_data.find(b"1 0 obj"),
        pdf_data.find(b"2 0 obj"),
        pdf_data.find(b"3 0 obj"),
        pdf_data.find(b"4 0 obj"),
        pdf_data.find(b"5 0 obj"),
        b"/Prev 0 " if with_prev_0 else b"",
        # startx_correction should be -1 due to double % at the beginning
        # inducing an error on startxref computation
        pdf_data.find(b"xref") + startx_correction,
    )
    pdf_stream = io.BytesIO(pdf_data)
    if should_fail:
        with pytest.raises(PdfReadError) as exc, pytest.warns(PdfReadWarning):
            PdfReader(pdf_stream, strict=strict)
        assert exc.type == PdfReadError
        if startx_correction == -1:
            assert (
                exc.value.args[0]
                == "/Prev=0 in the trailer (try opening with strict=False)"
            )
    else:
        PdfReader(pdf_stream, strict=strict)
        assert normalize_warnings(caplog.text) == warning_msgs


def test_issue297(caplog):
    path = RESOURCE_ROOT / "issue-297.pdf"
    with pytest.raises(PdfReadError) as exc:
        reader = PdfReader(path, strict=True)
    assert caplog.text == ""
    assert "Broken xref table" in exc.value.args[0]
    reader = PdfReader(path, strict=False)
    assert normalize_warnings(caplog.text) == ["incorrect startxref pointer(1)"]
    reader.pages[0]


@pytest.mark.parametrize(
    ("pdffile", "password", "should_fail"),
    [
        ("encrypted-file.pdf", "test", False),
        ("encrypted-file.pdf", b"test", False),
        ("encrypted-file.pdf", "qwerty", True),
        ("encrypted-file.pdf", b"qwerty", True),
    ],
)
def test_get_page_of_encrypted_file(pdffile, password, should_fail):
    """
    Check if we can read a page of an encrypted file.

    This is a regression test for issue 327:
    IndexError for get_page() of decrypted file
    """
    path = RESOURCE_ROOT / pdffile
    if should_fail:
        with pytest.raises(PdfReadError):
            PdfReader(path, password=password)
    else:
        PdfReader(path, password=password).pages[0]


@pytest.mark.parametrize(
    ("src", "expected", "expected_get_fields"),
    [
        (
            "form.pdf",
            {"foo": ""},
            {"foo": {"/DV": "", "/FT": "/Tx", "/T": "foo", "/V": ""}},
        ),
        (
            "form_acrobatReader.pdf",
            {"foo": "Bar"},
            {"foo": {"/DV": "", "/FT": "/Tx", "/T": "foo", "/V": "Bar"}},
        ),
        (
            "form_evince.pdf",
            {"foo": "bar"},
            {"foo": {"/DV": "", "/FT": "/Tx", "/T": "foo", "/V": "bar"}},
        ),
        (
            "crazyones.pdf",
            {},
            None,
        ),
    ],
)
def test_get_form(src, expected, expected_get_fields, txt_file_path):
    """Check if we can read out form data."""
    src = RESOURCE_ROOT / src
    reader = PdfReader(src)
    fields = reader.get_form_text_fields()
    assert fields == expected

    with open(txt_file_path, "w") as f:
        fields = reader.get_fields(fileobj=f)
    assert fields == expected_get_fields
    if fields:
        for field in fields.values():
            # Just access the attributes
            [
                field.field_type,
                field.parent,
                field.kids,
                field.name,
                field.alternate_name,
                field.mapping_name,
                field.flags,
                field.value,
                field.default_value,
                field.additional_actions,
            ]


@pytest.mark.parametrize(
    ("src", "page_number"),
    [
        ("form.pdf", 0),
        ("pdflatex-outline.pdf", 2),
    ],
)
def test_get_page_number(src, page_number):
    src = RESOURCE_ROOT / src
    reader = PdfReader(src)
    page = reader.pages[page_number]
    assert reader.get_page_number(page) == page_number


@pytest.mark.parametrize(
    ("src", "expected"),
    [("form.pdf", None), ("AutoCad_Simple.pdf", "/SinglePage")],
)
def test_get_page_layout(src, expected):
    src = RESOURCE_ROOT / src
    reader = PdfReader(src)
    assert reader.page_layout == expected


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("form.pdf", "/UseNone"),
        ("crazyones.pdf", None),
    ],
)
def test_get_page_mode(src, expected):
    src = RESOURCE_ROOT / src
    reader = PdfReader(src)
    assert reader.page_mode == expected


def test_read_empty():
    with pytest.raises(EmptyFileError) as exc:
        PdfReader(io.BytesIO())
    assert exc.value.args[0] == "Cannot read an empty file"


def test_read_malformed_header(caplog):
    with pytest.raises(PdfReadError) as exc:
        PdfReader(io.BytesIO(b"foo"), strict=True)
    assert exc.value.args[0] == "PDF starts with 'foo', but '%PDF-' expected"
    caplog.clear()
    try:
        PdfReader(io.BytesIO(b"foo"), strict=False)
    except Exception:
        pass
    assert caplog.messages[0].startswith("invalid pdf header")


def test_read_malformed_body():
    with pytest.raises(PdfReadError) as exc:
        PdfReader(io.BytesIO(b"%PDF-"), strict=True)
    assert (
        exc.value.args[0] == "EOF marker not found"
    )  # used to be:STREAM_TRUNCATED_PREMATURELY


def test_read_prev_0_trailer():
    pdf_data = (
        b"%%PDF-1.7\n"
        b"1 0 obj << /Count 1 /Kids [4 0 R] /Type /Pages >> endobj\n"
        b"2 0 obj << >> endobj\n"
        b"3 0 obj << >> endobj\n"
        b"4 0 obj << /Contents 3 0 R /CropBox [0.0 0.0 2550.0 3508.0]"
        b" /MediaBox [0.0 0.0 2550.0 3508.0] /Parent 1 0 R"
        b" /Resources << /Font << >> >>"
        b" /Rotate 0 /Type /Page >> endobj\n"
        b"5 0 obj << /Pages 1 0 R /Type /Catalog >> endobj\n"
        b"xref 1 5\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"trailer << %s/Root 5 0 R /Size 6 >>\n"
        b"startxref %d\n"
        b"%%%%EOF"
    )
    with_prev_0 = True
    pdf_data = pdf_data % (
        pdf_data.find(b"1 0 obj"),
        pdf_data.find(b"2 0 obj"),
        pdf_data.find(b"3 0 obj"),
        pdf_data.find(b"4 0 obj"),
        pdf_data.find(b"5 0 obj"),
        b"/Prev 0 " if with_prev_0 else b"",
        pdf_data.find(b"xref") - 1,
    )
    pdf_stream = io.BytesIO(pdf_data)
    with pytest.raises(PdfReadError) as exc, pytest.warns(PdfReadWarning):
        PdfReader(pdf_stream, strict=True)
    assert exc.value.args[0] == "/Prev=0 in the trailer (try opening with strict=False)"


def test_read_missing_startxref():
    pdf_data = (
        b"%%PDF-1.7\n"
        b"1 0 obj << /Count 1 /Kids [4 0 R] /Type /Pages >> endobj\n"
        b"2 0 obj << >> endobj\n"
        b"3 0 obj << >> endobj\n"
        b"4 0 obj << /Contents 3 0 R /CropBox [0.0 0.0 2550.0 3508.0]"
        b" /MediaBox [0.0 0.0 2550.0 3508.0] /Parent 1 0 R"
        b" /Resources << /Font << >> >>"
        b" /Rotate 0 /Type /Page >> endobj\n"
        b"5 0 obj << /Pages 1 0 R /Type /Catalog >> endobj\n"
        b"xref 1 5\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"trailer << /Root 5 0 R /Size 6 >>\n"
        # Removed for this test: b"startxref %d\n"
        b"%%%%EOF"
    )
    pdf_data = pdf_data % (
        pdf_data.find(b"1 0 obj"),
        pdf_data.find(b"2 0 obj"),
        pdf_data.find(b"3 0 obj"),
        pdf_data.find(b"4 0 obj"),
        pdf_data.find(b"5 0 obj"),
        # Removed for this test: pdf_data.find(b"xref") - 1,
    )
    pdf_stream = io.BytesIO(pdf_data)
    with pytest.raises(PdfReadError) as exc:
        PdfReader(pdf_stream, strict=True)
    assert exc.value.args[0] == "startxref not found"


def test_read_unknown_zero_pages(caplog):
    pdf_data = (
        b"%%PDF-1.7\n"
        b"1 0 obj << /Count 1 /Kids [4 0 R] /Type /Pages >> endobj\n"
        b"2 0 obj << >> endobj\n"
        b"3 0 obj << >> endobj\n"
        b"4 0 obj << /Contents 3 0 R /CropBox [0.0 0.0 2550.0 3508.0]"
        b" /MediaBox [0.0 0.0 2550.0 3508.0] /Parent 1 0 R"
        b" /Resources << /Font << >> >>"
        b" /Rotate 0 /Type /Page >> endobj\n"
        # Pages 0 0 is the key point:
        b"5 0 obj << /Pages 0 0 R /Type /Catalog >> endobj\n"
        b"xref 1 5\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"trailer << /Root 5 1 R /Size 6 >>\n"
        b"startxref %d\n"
        b"%%%%EOF"
    )
    pdf_data = pdf_data % (
        pdf_data.find(b"1 0 obj"),
        pdf_data.find(b"2 0 obj"),
        pdf_data.find(b"3 0 obj"),
        pdf_data.find(b"4 0 obj"),
        pdf_data.find(b"5 0 obj"),
        pdf_data.find(b"xref") - 1,
    )
    pdf_stream = io.BytesIO(pdf_data)
    reader = PdfReader(pdf_stream, strict=True)
    warnings = [
        "startxref on same line as offset",
        "Xref table not zero-indexed. ID numbers for objects will be corrected.",
    ]
    assert normalize_warnings(caplog.text) == warnings
    with pytest.raises(PdfReadError) as exc, pytest.warns(PdfReadWarning):
        len(reader.pages)

    assert exc.value.args[0] == "Could not find object."
    reader = PdfReader(pdf_stream, strict=False)
    warnings += [
        "Object 5 1 not defined.",
        "startxref on same line as offset",
    ]
    assert normalize_warnings(caplog.text) == warnings
    with pytest.raises(AttributeError) as exc, pytest.warns(PdfReadWarning):
        len(reader.pages)
    assert exc.value.args[0] == "'NoneType' object has no attribute 'get_object'"


def test_read_encrypted_without_decryption():
    src = RESOURCE_ROOT / "libreoffice-writer-password.pdf"
    reader = PdfReader(src)
    with pytest.raises(FileNotDecryptedError) as exc:
        len(reader.pages)
    assert exc.value.args[0] == "File has not been decrypted"


def test_get_destination_page_number():
    src = RESOURCE_ROOT / "pdflatex-outline.pdf"
    reader = PdfReader(src)
    outline = reader.outline
    for outline_item in outline:
        if not isinstance(outline_item, list):
            reader.get_destination_page_number(outline_item)


def test_do_not_get_stuck_on_large_files_without_start_xref():
    """
    Tests for the absence of a DoS bug, where a large file without an
    startxref mark would cause the library to hang for minutes to hours.
    """
    start_time = time.time()
    broken_stream = BytesIO(b"\0" * 5 * 1000 * 1000)
    with pytest.raises(PdfReadError):
        PdfReader(broken_stream)
    parse_duration = time.time() - start_time
    # parsing is expected take less than a second on a modern cpu, but include
    # a large tolerance to account for busy or slow systems
    assert parse_duration < 60


@pytest.mark.enable_socket()
def test_decrypt_when_no_id():
    """
    Decrypt an encrypted file that's missing the 'ID' value in its trailer.

    https://github.com/py-pdf/pypdf/issues/608
    """
    with open(RESOURCE_ROOT / "encrypted_doc_no_id.pdf", "rb") as inputfile:
        ipdf = PdfReader(inputfile)
        ipdf.decrypt("")
        assert ipdf.metadata == {"/Producer": "European Patent Office"}


def test_reader_properties():
    reader = PdfReader(RESOURCE_ROOT / "crazyones.pdf")
    assert reader.outline == []
    assert len(reader.pages) == 1
    assert reader.page_layout is None
    assert reader.page_mode is None
    assert reader.is_encrypted is False


@pytest.mark.parametrize(
    "strict",
    [True, False],
)
def test_issue604(caplog, strict):
    """Test with invalid destinations."""  # todo
    with open(RESOURCE_ROOT / "issue-604.pdf", "rb") as f:
        pdf = None
        outline = None
        if strict:
            pdf = PdfReader(f, strict=strict)
            with pytest.raises(PdfReadError) as exc, pytest.warns(PdfReadWarning):
                outline = pdf.outline
            if "Unknown Destination" not in exc.value.args[0]:
                raise Exception("Expected exception not raised")
            return  # outline is not correct
        else:
            pdf = PdfReader(f, strict=strict)
            outline = pdf.outline
            msg = [
                "Unknown destination: ms_Thyroid_2_2020_071520_watermarked.pdf [0, 1]"
            ]
            assert normalize_warnings(caplog.text) == msg

        def get_dest_pages(x) -> int:
            if isinstance(x, list):
                r = [get_dest_pages(y) for y in x]
                return r
            else:
                return pdf.get_destination_page_number(x) + 1

        out = []

        # oi can be destination or a list:preferred to just print them
        for oi in outline:
            out.append(get_dest_pages(oi))


def test_decode_permissions():
    reader = PdfReader(RESOURCE_ROOT / "crazyones.pdf")
    base = {
        "accessability": False,
        "annotations": False,
        "assemble": False,
        "copy": False,
        "forms": False,
        "modify": False,
        "print_high_quality": False,
        "print": False,
    }

    print_ = base.copy()
    print_["print"] = True
    assert reader.decode_permissions(4) == print_

    modify = base.copy()
    modify["modify"] = True
    assert reader.decode_permissions(8) == modify


def test_pages_attribute():
    pdf_path = RESOURCE_ROOT / "crazyones.pdf"
    reader = PdfReader(pdf_path)

    # Test if getting as slice throws an error
    assert len(reader.pages[:]) == 1

    with pytest.raises(IndexError) as exc:
        reader.pages[-1000]

    assert exc.value.args[0] == "sequence index out of range"

    with pytest.raises(IndexError):
        reader.pages[1000]

    assert exc.value.args[0] == "sequence index out of range"


def test_convert_to_int():
    assert convert_to_int(b"\x01", 8) == 1


def test_convert_to_int_error():
    with pytest.raises(PdfReadError) as exc:
        convert_to_int(b"256", 16)
    assert exc.value.args[0] == "invalid size in convert_to_int"


def test_converttoint_deprecated():
    msg = (
        "convertToInt is deprecated and was removed in pypdf 3.0.0. "
        "Use convert_to_int instead."
    )
    with pytest.raises(
        DeprecationError,
        match=msg,
    ):
        assert convertToInt(b"\x01", 8) == 1


@pytest.mark.enable_socket()
def test_iss925():
    url = "https://github.com/py-pdf/pypdf/files/8796328/1.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name="iss925.pdf")))

    for page_sliced in reader.pages:
        page_object = page_sliced.get_object()
        # Extracts the PDF's Annots (Annotations and Commenting):
        annots = page_object.get("/Annots")
        if annots is not None:
            for annot in annots:
                annot.get_object()


def test_get_object():
    reader = PdfReader(RESOURCE_ROOT / "hello-world.pdf")
    assert reader.get_object(22)["/Type"] == "/Catalog"
    assert reader._get_indirect_object(22, 0)["/Type"] == "/Catalog"


def test_extract_text_hello_world():
    reader = PdfReader(RESOURCE_ROOT / "hello-world.pdf")
    text = reader.pages[0].extract_text().split("\n")
    assert text == [
        "English:",
        "Hello World",
        "Arabic:",
        "مرحبا بالعالم",
        "Russian:",
        "Привет, мир",
        "Chinese (traditional):",
        "你好世界",
        "Thai:",
        "สวัสดีชาวโลก",
        "Japanese:",
        "こんにちは世界",
    ]


def test_read_path():
    path = Path(RESOURCE_ROOT, "crazyones.pdf")
    reader = PdfReader(path)
    assert len(reader.pages) == 1


def test_read_not_binary_mode(caplog):
    with open(RESOURCE_ROOT / "crazyones.pdf") as f:
        msg = (
            "PdfReader stream/file object is not in binary mode. "
            "It may not be read correctly."
        )
        with pytest.raises(io.UnsupportedOperation):
            PdfReader(f)
    assert normalize_warnings(caplog.text) == [msg]


@pytest.mark.enable_socket()
@pytest.mark.skipif(not HAS_PYCRYPTODOME, reason="No pycryptodome")
def test_read_form_416():
    url = (
        "https://www.fda.gov/downloads/AboutFDA/ReportsManualsForms/Forms/UCM074728.pdf"
    )
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name="issue_416.pdf")))
    fields = reader.get_form_text_fields()
    assert len(fields) > 0


def test_form_topname_with_and_without_acroform(caplog):
    r = PdfReader(RESOURCE_ROOT / "crazyones.pdf")
    r.add_form_topname("no")
    r.rename_form_topname("renamed")
    assert "/AcroForm" not in r.trailer["/Root"]
    r.trailer["/Root"][NameObject("/AcroForm")] = DictionaryObject()
    r.add_form_topname("toto")
    r.rename_form_topname("renamed")
    assert len(r.get_fields()) == 0

    r = PdfReader(RESOURCE_ROOT / "form.pdf")
    r.add_form_topname("top")
    flds = r.get_fields()
    assert "top" in flds
    assert "top.foo" in flds
    r.rename_form_topname("renamed")
    flds = r.get_fields()
    assert "renamed" in flds
    assert "renamed.foo" in flds

    r = PdfReader(RESOURCE_ROOT / "form.pdf")
    r.get_fields()["foo"].indirect_reference.get_object()[
        NameObject("/Parent")
    ] = DictionaryObject()
    r.add_form_topname("top")
    assert "have a non-expected parent" in caplog.text


@pytest.mark.enable_socket()
def test_extract_text_xref_issue_2(caplog):
    # pdf/0264cf510015b2a4b395a15cb23c001e.pdf
    url = "https://corpora.tika.apache.org/base/docs/govdocs1/981/981961.pdf"
    msg = "incorrect startxref pointer(2)"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name="tika-981961.pdf")))
    for page in reader.pages:
        page.extract_text()
    assert normalize_warnings(caplog.text) == [msg]


@pytest.mark.enable_socket()
@pytest.mark.slow()
def test_extract_text_xref_issue_3(caplog):
    # pdf/0264cf510015b2a4b395a15cb23c001e.pdf
    url = "https://corpora.tika.apache.org/base/docs/govdocs1/977/977774.pdf"
    msg = "incorrect startxref pointer(3)"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name="tika-977774.pdf")))
    for page in reader.pages:
        page.extract_text()
    assert normalize_warnings(caplog.text) == [msg]


@pytest.mark.enable_socket()
def test_extract_text_pdf15():
    # pdf/0264cf510015b2a4b395a15cb23c001e.pdf
    url = "https://corpora.tika.apache.org/base/docs/govdocs1/976/976030.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name="tika-976030.pdf")))
    for page in reader.pages:
        page.extract_text()


@pytest.mark.enable_socket()
def test_extract_text_xref_table_21_bytes_clrf():
    # pdf/0264cf510015b2a4b395a15cb23c001e.pdf
    url = "https://corpora.tika.apache.org/base/docs/govdocs1/956/956939.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name="tika-956939.pdf")))
    for page in reader.pages:
        page.extract_text()


@pytest.mark.enable_socket()
def test_get_fields():
    url = "https://corpora.tika.apache.org/base/docs/govdocs1/972/972486.pdf"
    name = "tika-972486.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    fields = reader.get_fields()
    assert fields is not None
    assert "c1-1" in fields
    assert dict(fields["c1-1"]) == ({"/FT": "/Btn", "/T": "c1-1"})


@pytest.mark.enable_socket()
def test_get_full_qualified_fields():
    url = "https://github.com/py-pdf/pypdf/files/10142389/fields_with_dots.pdf"
    name = "fields_with_dots.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    fields = reader.get_form_text_fields(True)
    assert fields is not None
    assert "customer.name" in fields

    fields = reader.get_form_text_fields(False)
    assert fields is not None
    assert "customer.name" not in fields
    assert "name" in fields

    fields = reader.get_fields(True)
    assert fields is not None
    assert "customer.name" in fields
    assert fields["customer.name"]["/T"] == "name"


@pytest.mark.enable_socket()
@pytest.mark.filterwarnings("ignore::pypdf.errors.PdfReadWarning")
def test_get_fields_read_else_block():
    # covers also issue 1089
    url = "https://corpora.tika.apache.org/base/docs/govdocs1/934/934771.pdf"
    name = "tika-934771.pdf"
    PdfReader(BytesIO(get_pdf_from_url(url, name=name)))


@pytest.mark.enable_socket()
def test_get_fields_read_else_block2():
    url = "https://corpora.tika.apache.org/base/docs/govdocs1/914/914902.pdf"
    name = "tika-914902.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    fields = reader.get_fields()
    assert fields is None


@pytest.mark.enable_socket()
@pytest.mark.filterwarnings("ignore::pypdf.errors.PdfReadWarning")
def test_get_fields_read_else_block3():
    url = "https://corpora.tika.apache.org/base/docs/govdocs1/957/957721.pdf"
    name = "tika-957721.pdf"
    PdfReader(BytesIO(get_pdf_from_url(url, name=name)))


@pytest.mark.enable_socket()
def test_metadata_is_none():
    url = "https://corpora.tika.apache.org/base/docs/govdocs1/963/963692.pdf"
    name = "tika-963692.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    assert reader.metadata is None


@pytest.mark.enable_socket()
def test_get_fields_read_write_report(txt_file_path):
    url = "https://corpora.tika.apache.org/base/docs/govdocs1/909/909655.pdf"
    name = "tika-909655.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    with open(txt_file_path, "w") as fp:
        fields = reader.get_fields(fileobj=fp)
    assert fields


@pytest.mark.parametrize(
    "src",
    [
        RESOURCE_ROOT / "crazyones.pdf",
        RESOURCE_ROOT / "commented.pdf",
    ],
)
def test_xfa(src):
    reader = PdfReader(src)
    assert reader.xfa is None


@pytest.mark.enable_socket()
def test_xfa_non_empty():
    url = "https://corpora.tika.apache.org/base/docs/govdocs1/942/942050.pdf"
    name = "tika-942050.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    assert list(reader.xfa.keys()) == [
        "preamble",
        "config",
        "template",
        "PDFSecurity",
        "datasets",
        "postamble",
    ]


@pytest.mark.parametrize(
    ("src", "pdf_header"),
    [
        (RESOURCE_ROOT / "attachment.pdf", "%PDF-1.5"),
        (RESOURCE_ROOT / "crazyones.pdf", "%PDF-1.5"),
    ],
)
def test_header(src, pdf_header):
    reader = PdfReader(src)

    assert reader.pdf_header == pdf_header


@pytest.mark.enable_socket()
def test_outline_color():
    url = "https://corpora.tika.apache.org/base/docs/govdocs1/924/924546.pdf"
    name = "tika-924546.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    assert reader.outline[0].color == [0, 0, 1]


@pytest.mark.enable_socket()
def test_outline_font_format():
    url = "https://corpora.tika.apache.org/base/docs/govdocs1/924/924546.pdf"
    name = "tika-924546.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    assert reader.outline[0].font_format == 2


def get_outline_property(outline, attribute_name: str):
    results = []
    if isinstance(outline, list):
        for outline_item in outline:
            if isinstance(outline_item, Destination):
                results.append(getattr(outline_item, attribute_name))
            else:
                results.append(get_outline_property(outline_item, attribute_name))
    else:
        raise ValueError(f"got {type(outline)}")
    return results


@pytest.mark.samples()
def test_outline_title_issue_1121():
    reader = PdfReader(SAMPLE_ROOT / "014-outlines/mistitled_outlines_example.pdf")

    assert get_outline_property(reader.outline, "title") == [
        "First",
        [
            "Second",
            "Third",
            "Fourth",
            [
                "Fifth",
                "Sixth",
            ],
            "Seventh",
            [
                "Eighth",
                "Ninth",
            ],
        ],
        "Tenth",
        [
            "Eleventh",
            "Twelfth",
            "Thirteenth",
            "Fourteenth",
        ],
        "Fifteenth",
        [
            "Sixteenth",
            "Seventeenth",
        ],
        "Eighteenth",
        "Nineteenth",
        [
            "Twentieth",
            "Twenty-first",
            "Twenty-second",
            "Twenty-third",
            "Twenty-fourth",
            "Twenty-fifth",
            "Twenty-sixth",
            "Twenty-seventh",
        ],
    ]


@pytest.mark.samples()
def test_outline_count():
    reader = PdfReader(SAMPLE_ROOT / "014-outlines/mistitled_outlines_example.pdf")

    assert get_outline_property(reader.outline, "outline_count") == [
        5,
        [
            None,
            None,
            2,
            [
                None,
                None,
            ],
            -2,
            [
                None,
                None,
            ],
        ],
        4,
        [
            None,
            None,
            None,
            None,
        ],
        -2,
        [
            None,
            None,
        ],
        None,
        8,
        [
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
    ]


def test_outline_missing_title(caplog):
    # Strict
    reader = PdfReader(RESOURCE_ROOT / "outline-without-title.pdf", strict=True)
    with pytest.raises(PdfReadError) as exc:
        reader.outline
    assert exc.value.args[0].startswith("Outline Entry Missing /Title attribute:")

    # Non-strict : no errors
    reader = PdfReader(RESOURCE_ROOT / "outline-without-title.pdf", strict=False)
    assert reader.outline[0]["/Title"] == ""


@pytest.mark.enable_socket()
def test_named_destination():
    # 1st case : the named_dest are stored directly as a dictionnary, PDF1.1 style
    url = "https://github.com/py-pdf/pypdf/files/9197028/lorem_ipsum.pdf"
    name = "lorem_ipsum.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    assert len(reader.named_destinations) > 0
    # 2nd case : Dest below names and with Kids...
    url = (
        "https://opensource.adobe.com/dc-acrobat-sdk-docs/standards/"
        "pdfstandards/pdf/PDF32000_2008.pdf"
    )
    name = "PDF32000_2008.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    assert len(reader.named_destinations) > 0
    # 3nd case : Dests with Name tree
    # TODO : case to be added


@pytest.mark.enable_socket()
def test_outline_with_missing_named_destination():
    url = "https://corpora.tika.apache.org/base/docs/govdocs1/913/913678.pdf"
    name = "tika-913678.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    # outline items in document reference a named destination that is not defined
    assert reader.outline[1][0].title.startswith("Report for 2002AZ3B: Microbial")


@pytest.mark.enable_socket()
def test_outline_with_empty_action():
    url = "https://corpora.tika.apache.org/base/docs/govdocs1/924/924546.pdf"
    name = "tika-924546.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    # outline items (entitled Tables and Figures) utilize an empty action (/A)
    # that has no type or destination
    assert reader.outline[-4].title == "Tables"


def test_outline_with_invalid_destinations():
    reader = PdfReader(RESOURCE_ROOT / "outlines-with-invalid-destinations.pdf")
    # contains 9 outline items, 6 with invalid destinations
    # caused by different malformations
    assert len(reader.outline) == 9


@pytest.mark.enable_socket()
def test_pdfreader_multiple_definitions(caplog):
    """iss325"""
    url = "https://github.com/py-pdf/pypdf/files/9176644/multipledefs.pdf"
    name = "multipledefs.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    reader.pages[0].extract_text()
    assert normalize_warnings(caplog.text) == [
        "Multiple definitions in dictionary at byte 0xb5 for key /Group"
    ]


def test_wrong_password_error():
    encrypted_pdf_path = RESOURCE_ROOT / "encrypted-file.pdf"
    with pytest.raises(WrongPasswordError):
        PdfReader(
            encrypted_pdf_path,
            password="definitely_the_wrong_password!",
        )


def test_get_page_number_by_indirect():
    reader = PdfReader(RESOURCE_ROOT / "crazyones.pdf")
    reader._get_page_number_by_indirect(1)


@pytest.mark.enable_socket()
def test_corrupted_xref_table():
    # issue #1292
    url = "https://github.com/py-pdf/pypdf/files/9444747/BreezeManual.orig.pdf"
    name = "BreezeMan1.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    reader.pages[0].extract_text()
    url = "https://github.com/py-pdf/pypdf/files/9444748/BreezeManual.failed.pdf"
    name = "BreezeMan2.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    reader.pages[0].extract_text()


@pytest.mark.enable_socket()
def test_reader(caplog):
    # iss #1273
    url = "https://github.com/py-pdf/pypdf/files/9464742/shiv_resume.pdf"
    name = "shiv_resume.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    assert "Previous trailer can not be read" in caplog.text
    caplog.clear()
    # first call requires some reparations...
    reader.pages[0].extract_text()
    assert "repaired" in caplog.text
    assert "found" in caplog.text
    caplog.clear()
    # ...and now no more required
    reader.pages[0].extract_text()
    assert caplog.text == ""


@pytest.mark.enable_socket()
def test_zeroing_xref():
    # iss #328
    url = (
        "https://github.com/py-pdf/pypdf/files/9066120/"
        "UTA_OSHA_3115_Fall_Protection_Training_09162021_.pdf"
    )
    name = "UTA_OSHA.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    len(reader.pages)


@pytest.mark.enable_socket()
def test_thread():
    url = (
        "https://github.com/py-pdf/pypdf/files/9066120/"
        "UTA_OSHA_3115_Fall_Protection_Training_09162021_.pdf"
    )
    name = "UTA_OSHA.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    assert reader.threads is None
    url = "https://corpora.tika.apache.org/base/docs/govdocs1/924/924666.pdf"
    name = "tika-924666.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    assert isinstance(reader.threads, ArrayObject)
    assert len(reader.threads) >= 1


@pytest.mark.enable_socket()
def test_build_outline_item(caplog):
    url = "https://github.com/py-pdf/pypdf/files/9464742/shiv_resume.pdf"
    name = "shiv_resume.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    outline = reader._build_outline_item(
        DictionaryObject(
            {
                NameObject("/Title"): TextStringObject("Toto"),
                NameObject("/Dest"): NumberObject(2),
            }
        )
    )
    assert "Removed unexpected destination 2 from destination" in caplog.text
    assert outline["/Title"] == "Toto"
    reader.strict = True
    with pytest.raises(PdfReadError) as exc:
        reader._build_outline_item(
            DictionaryObject(
                {
                    NameObject("/Title"): TextStringObject("Toto"),
                    NameObject("/Dest"): NumberObject(2),
                }
            )
        )
    assert "Unexpected destination 2" in exc.value.args[0]


@pytest.mark.samples()
@pytest.mark.parametrize(
    ("src", "page_labels"),
    [
        (RESOURCE_ROOT / "selenium-pypdf-issue-177.pdf", ["1"]),
        (RESOURCE_ROOT / "encrypted_doc_no_id.pdf", ["1", "2", "3"]),
        (RESOURCE_ROOT / "pdflatex-outline.pdf", ["1", "2", "3", "4"]),
        (
            SAMPLE_ROOT / "009-pdflatex-geotopo/GeoTopo.pdf",
            ["i", "ii", "iii", "1", "2", "3"],
        ),
    ],
    ids=[
        "selenium-pypdf-issue-177.pdf",
        "encrypted_doc_no_id.pdf",
        "pdflatex-outline.pdf",
        "GeoTopo.pdf",
    ],
)
def test_page_labels(src, page_labels):
    max_indices = 6
    assert PdfReader(src).page_labels[:max_indices] == page_labels[:max_indices]


@pytest.mark.enable_socket()
def test_iss1559():
    url = "https://github.com/py-pdf/pypdf/files/10441992/default.pdf"
    name = "iss1559.pdf"
    reader = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    for p in reader.pages:
        p.extract_text()


@pytest.mark.enable_socket()
def test_iss1652():
    # test of an annotation(link) directly stored in the /Annots in the page
    url = "https://github.com/py-pdf/pypdf/files/10818844/tt.pdf"
    name = "invalidNamesDest.pdf"
    in_pdf = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    in_pdf.named_destinations


@pytest.mark.enable_socket()
def test_iss1689():
    url = "https://github.com/py-pdf/pypdf/files/10948283/error_file_without_data.pdf"
    name = "iss1689.pdf"
    in_pdf = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    in_pdf.pages[0]


@pytest.mark.enable_socket()
def test_iss1710():
    url = "https://nlp.stanford.edu/IR-book/pdf/irbookonlinereading.pdf"
    name = "irbookonlinereading.pdf"
    in_pdf = PdfReader(BytesIO(get_pdf_from_url(url, name=name)))
    in_pdf.outline


def test_broken_file_header():
    pdf_data = (
        b"%%PDF-\xa0sd\n"
        b"1 0 obj << /Count 1 /Kids [4 0 R] /Type /Pages >> endobj\n"
        b"2 0 obj << >> endobj\n"
        b"3 0 obj << >> endobj\n"
        b"4 0 obj << /Contents 3 0 R /CropBox [0.0 0.0 2550.0 3508.0]"
        b" /MediaBox [0.0 0.0 2550.0 3508.0] /Parent 1 0 R"
        b" /Resources << /Font << >> >>"
        b" /Rotate 0 /Type /Page >> endobj\n"
        b"5 0 obj << /Pages 1 0 R /Type /Catalog >> endobj\n"
        b"xref 1 5\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"%010d 00000 n\n"
        b"trailer << %s/Root 5 0 R /Size 6 >>\n"
        b"startxref %d\n"
        b"%%%%EOF"
    )
    with_prev_0 = True
    pdf_data = pdf_data % (
        pdf_data.find(b"1 0 obj"),
        pdf_data.find(b"2 0 obj"),
        pdf_data.find(b"3 0 obj"),
        pdf_data.find(b"4 0 obj"),
        pdf_data.find(b"5 0 obj"),
        b"/Prev 0 " if with_prev_0 else b"",
        pdf_data.find(b"xref") - 1,
    )
    PdfReader(io.BytesIO(pdf_data))
