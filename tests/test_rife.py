"""rife-ncnn-vulkan discovery contract: env hint > repo bin/ > PATH."""

from pathlib import Path

import vrpatch.rife as rife_mod
from vrpatch.rife import EXE_NAME, find_rife


def test_env_hint_file(tmp_path: Path):
    exe = tmp_path / EXE_NAME
    exe.write_bytes(b"")
    assert find_rife(root=tmp_path / "bin",
                     env={"VRPATCH_RIFE": str(exe)}) == str(exe)


def test_env_hint_directory(tmp_path: Path):
    d = tmp_path / "rife-ncnn-vulkan-20221029"
    d.mkdir()
    (d / EXE_NAME).write_bytes(b"")
    assert find_rife(root=tmp_path / "bin",
                     env={"VRPATCH_RIFE": str(d)}) == str(d / EXE_NAME)


def test_repo_bin_glob(tmp_path: Path):
    d = tmp_path / "bin" / "rife-ncnn-vulkan-20221029-windows"
    d.mkdir(parents=True)
    (d / EXE_NAME).write_bytes(b"")
    assert find_rife(root=tmp_path / "bin", env={}) == str(d / EXE_NAME)


def test_missing_env_hint_falls_through(tmp_path: Path):
    # hint names a nonexistent file -> ignored, bin/ wins
    d = tmp_path / "bin" / "rife-ncnn-vulkan-x"
    d.mkdir(parents=True)
    (d / EXE_NAME).write_bytes(b"")
    assert find_rife(root=tmp_path / "bin",
                     env={"VRPATCH_RIFE": str(tmp_path / "nope.exe")}) == str(d / EXE_NAME)


def test_nowhere_to_be_found(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(rife_mod.shutil, "which", lambda name: None)
    assert find_rife(root=tmp_path / "empty", env={}) is None
