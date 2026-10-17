from __future__ import annotations

import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ficframe.desktop import available_port, configure_stdio
from ficframe.runtime_paths import user_data_root, visual_presets_root


class RuntimePathTests(unittest.TestCase):
    def test_frozen_app_keeps_data_beside_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "chosen-drive" / "FicFrame" / "FicFrame.exe"
            executable.parent.mkdir(parents=True)
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("FICFRAME_DATA_DIR", None)
                with patch("ficframe.runtime_paths.is_frozen", return_value=True), patch.object(
                    sys, "executable", str(executable)
                ):
                    root = user_data_root(create=False)

        self.assertEqual(root, (executable.parent / "data").resolve())

    def test_data_directory_override_has_priority(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"FICFRAME_DATA_DIR": directory}, clear=False
        ):
            self.assertEqual(user_data_root(create=False), Path(directory).resolve())

    def test_visual_presets_use_overridden_global_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"FICFRAME_DATA_DIR": directory}):
            root = visual_presets_root()
            self.assertEqual(root, Path(directory).resolve() / "visual-presets")
            self.assertTrue((root / "drafts").is_dir())
            self.assertTrue((root / "references").is_dir())

    def test_visual_presets_use_packaged_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FICFRAME_DATA_DIR", None)
            executable = Path(directory) / "FicFrame.exe"
            with patch("ficframe.runtime_paths.is_frozen", return_value=True), patch.object(sys, "executable", str(executable)):
                self.assertEqual(visual_presets_root(create=False), (executable.parent / "data" / "visual-presets").resolve())


class DesktopPortTests(unittest.TestCase):
    def test_configure_stdio_uses_utf8_for_frozen_cli_output(self) -> None:
        stdout = Mock()
        stderr = Mock()
        with patch("ficframe.desktop.sys.stdout", stdout), patch("ficframe.desktop.sys.stderr", stderr):
            configure_stdio()

        stdout.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")
        stderr.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")

    def test_available_port_skips_an_occupied_port(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.bind(("127.0.0.1", 0))
            port = occupied.getsockname()[1]
            selected = available_port("127.0.0.1", port, span=2)

        self.assertEqual(selected, port + 1)


if __name__ == "__main__":
    unittest.main()
