# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Runtime provenance detects dirty source and mutable container tag changes."""

import hashlib

import pytest

from robots.univtac.pilot import provenance


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    for name in provenance.SOURCES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    image = ["sha256:" + "a" * 64]

    def command(args, **kwargs):
        if args[0] == "docker":
            assert args == [
                "docker",
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                "candidate:latest",
            ]
            return image[0] + "\n"
        assert args == ["git", "-C", str(tmp_path), "rev-parse", "HEAD"]
        return "same-git-head\n"

    monkeypatch.setattr(provenance.subprocess, "check_output", command)
    return tmp_path, image


def test_dirty_source_and_retagged_image_change_effective_evidence(checkout):
    root, image = checkout
    before = provenance.collect(root, sandbox_image="candidate:latest")
    assert before["controller"]["sandbox_image"] == image[0]
    assert before["memory"] == {
        "mode": "empty_read_only",
        "shared": False,
        "file_tools": False,
    }
    name = "robots/univtac/control.py"
    (root / name).write_text("changed controller without a git commit")
    image[0] = "sha256:" + "b" * 64
    after = provenance.collect(root, sandbox_image="candidate:latest")
    assert after["code_revision"]["git_head"] == before["code_revision"]["git_head"]
    assert (
        after["code_revision"]["sources"][name]
        != before["code_revision"]["sources"][name]
    )
    assert (
        after["code_revision"]["sources"][name]
        == hashlib.sha256((root / name).read_bytes()).hexdigest()
    )
    assert after["controller"]["sandbox_image"] != before["controller"]["sandbox_image"]


def test_missing_source_fails_instead_of_recording_an_incomplete_freeze(checkout):
    root, _ = checkout
    (root / "robots/libero/research/worker.py").unlink()
    with pytest.raises(FileNotFoundError):
        provenance.collect(root, sandbox_image="candidate:latest")


def test_unresolved_image_tag_is_rejected(checkout):
    root, image = checkout
    image[0] = "candidate:latest"
    with pytest.raises(ValueError, match="immutable sandbox image"):
        provenance.collect(root, sandbox_image="candidate:latest")
