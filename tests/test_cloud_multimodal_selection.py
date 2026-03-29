from __future__ import annotations

from pathlib import Path

from PIL import Image

from webmail_summary.archive.html_rewrite import ExternalAsset
from webmail_summary.archive.mime_parts import SavedAttachment
from webmail_summary.jobs.tasks_sync import _select_multimodal_inputs


def _make_image(path: Path, *, width: int, height: int = 200) -> None:
    img = Image.new("RGB", (width, height), color=(20, 40, 60))
    img.save(path)


def test_select_multimodal_inputs_always_keeps_wide_images(tmp_path: Path):
    attach_dir = tmp_path / "attachments"
    ext_dir = tmp_path / "external"
    attach_dir.mkdir()
    ext_dir.mkdir()

    wide1 = attach_dir / "wide1.jpg"
    wide2 = ext_dir / "wide2.png"
    small = attach_dir / "small.jpg"

    _make_image(wide1, width=900)
    _make_image(wide2, width=720)
    _make_image(small, width=320)

    selected = _select_multimodal_inputs(
        base_dir=tmp_path,
        attachments=[
            SavedAttachment(
                filename=wide1.name,
                rel_path="attachments/wide1.jpg",
                mime_type="image/jpeg",
                size_bytes=wide1.stat().st_size,
                content_id=None,
                is_inline=False,
            ),
            SavedAttachment(
                filename=small.name,
                rel_path="attachments/small.jpg",
                mime_type="image/jpeg",
                size_bytes=small.stat().st_size,
                content_id=None,
                is_inline=False,
            ),
        ],
        external_assets=[
            ExternalAsset(
                original_url="https://example.com/wide2.png",
                rel_path="external/wide2.png",
                status="downloaded",
                mime_type="image/png",
                size_bytes=wide2.stat().st_size,
            )
        ],
        max_images=1,
    )

    paths = {Path(x.path).name for x in selected}
    assert "wide1.jpg" in paths
    assert "wide2.png" in paths


def test_select_multimodal_inputs_respects_toggle_fill_limit_for_small_images(
    tmp_path: Path,
):
    attach_dir = tmp_path / "attachments"
    attach_dir.mkdir()

    small1 = attach_dir / "small1.jpg"
    small2 = attach_dir / "small2.jpg"
    small3 = attach_dir / "small3.jpg"
    for p in [small1, small2, small3]:
        _make_image(p, width=320)

    selected = _select_multimodal_inputs(
        base_dir=tmp_path,
        attachments=[
            SavedAttachment(
                p.name,
                f"attachments/{p.name}",
                "image/jpeg",
                p.stat().st_size,
                None,
                False,
            )
            for p in [small1, small2, small3]
        ],
        external_assets=[],
        max_images=2,
    )

    assert len(selected) == 2


def test_select_multimodal_inputs_excludes_logo_and_small_banner(tmp_path: Path):
    attach_dir = tmp_path / "attachments"
    attach_dir.mkdir()

    logo = attach_dir / "company_logo.png"
    banner = attach_dir / "newsletter_banner.jpg"
    hero = attach_dir / "hero.jpg"

    _make_image(logo, width=180, height=80)
    _make_image(banner, width=720, height=120)
    _make_image(hero, width=900, height=480)

    selected = _select_multimodal_inputs(
        base_dir=tmp_path,
        attachments=[
            SavedAttachment(
                logo.name,
                f"attachments/{logo.name}",
                "image/png",
                logo.stat().st_size,
                None,
                True,
            ),
            SavedAttachment(
                banner.name,
                f"attachments/{banner.name}",
                "image/jpeg",
                banner.stat().st_size,
                None,
                False,
            ),
            SavedAttachment(
                hero.name,
                f"attachments/{hero.name}",
                "image/jpeg",
                hero.stat().st_size,
                None,
                False,
            ),
        ],
        external_assets=[],
        max_images=5,
    )

    names = {Path(x.path).name for x in selected}
    assert "company_logo.png" not in names
    assert "newsletter_banner.jpg" not in names
    assert "hero.jpg" in names
