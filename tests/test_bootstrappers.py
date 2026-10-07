"""L-004 generator tests: determinism, embedded tag/digests and refusals (no network, no install)."""
from __future__ import annotations

import importlib.util
import re
import subprocess
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gen", ROOT / "packaging/oneline/generate_bootstrappers.py")
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)

SUMS = "\n".join(
    [
        "1" * 64 + "  axiom-1.2.3-windows-x64.zip",
        "2" * 64 + "  axiom-1.2.3-linux-x64.tar.gz",
        "3" * 64 + "  axiom-1.2.3-macos-x64.tar.gz",
        "4" * 64 + "  SOURCE-REVISION.txt",
    ]
) + "\n"


class GeneratorTests(unittest.TestCase):
    def test_same_inputs_give_byte_identical_scripts(self):
        first = gen.generate("v1.2.3", SUMS)
        second = gen.generate("v1.2.3", SUMS.replace("\n", "\r\n"))
        self.assertEqual(first, second)
        for data in first.values():
            self.assertNotIn(b"\r\n", data)

    def test_scripts_embed_the_exact_tag_assets_and_digests(self):
        scripts = gen.generate("v1.2.3", SUMS)
        ps1 = scripts["install.ps1"].decode()
        sh = scripts["install.sh"].decode()
        self.assertIn("$AxiomTag = 'v1.2.3'", ps1)
        self.assertIn("$AxiomSha256 = '" + "1" * 64 + "'", ps1)
        self.assertIn("axiom-1.2.3-windows-x64.zip", ps1)
        self.assertIn("AXIOM_TAG='v1.2.3'", sh)
        self.assertIn("2" * 64, sh)
        self.assertIn("3" * 64, sh)
        for text in (ps1, sh):
            self.assertNotRegex(text, r"@@[A-Z_]+@@")
            # Downloads only ever use the embedded or an explicitly pinned tag, never `latest`.
            for line in text.splitlines():
                if line.lstrip().startswith("#"):
                    continue
                self.assertNotIn("latest", line)

    def test_moving_tags_and_missing_assets_are_refused(self):
        for tag in ("latest", "main", "1.2.3", "v1.2", "v1.2.3;rm"):
            with self.assertRaises(gen.GenerationError, msg=tag):
                gen.generate(tag, SUMS)
        with self.assertRaises(gen.GenerationError):
            gen.generate("v1.2.3", SUMS.replace("axiom-1.2.3-macos-x64.tar.gz", "other"))
        with self.assertRaises(gen.GenerationError):
            gen.generate("v1.2.3", "nothex  axiom-1.2.3-windows-x64.zip\n")
        with self.assertRaises(gen.GenerationError):
            gen.generate("v1.2.3", SUMS, "https://github.com/orchex006/axiom-cli/releases/latest/download")

    def test_posix_script_is_valid_sh(self):
        sh = shutil.which("sh")
        if not sh:
            self.skipTest("no sh on this host")
        script = gen.generate("v1.2.3", SUMS)["install.sh"]
        result = subprocess.run([sh, "-n"], input=script, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
