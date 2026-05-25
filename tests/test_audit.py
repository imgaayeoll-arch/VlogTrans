import os
from modules.audit import cleanup_temporary_files


def test_cleanup_removes_single_file(tmp_path):
    f = tmp_path / "temp.txt"
    f.write_text("data")

    cleanup_temporary_files([str(f)])

    assert not f.exists()


def test_cleanup_removes_directory(tmp_path):
    d = tmp_path / "tempdir"
    d.mkdir()
    (d / "nested.txt").write_text("data")

    cleanup_temporary_files([str(d)])

    assert not d.exists()


def test_cleanup_skips_nonexistent_path(tmp_path):
    nonexistent = str(tmp_path / "does_not_exist")

    # Should not raise
    cleanup_temporary_files([nonexistent])
