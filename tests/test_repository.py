from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reloaded_package import PACKAGE_TAG, parse_package_summary  # noqa: E402


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RepositoryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.uv_guard = load_module(ROOT / "src" / "gowreloaded_static_uvstream_regression_guard.py", "gowr_uv_guard")

    def test_game_metadata_is_reloaded_steam(self) -> None:
        game = json.loads((ROOT / "game.json").read_text(encoding="utf-8"))
        self.assertEqual(game["id"], "gears-of-war-reloaded")
        self.assertEqual(game["releaseYear"], 2025)
        self.assertEqual(game["platforms"][0]["steamAppId"], 2523720)
        self.assertEqual(game["platforms"][0]["buildId"], "20087529")

    def test_package_summary_parser(self) -> None:
        folder = b"None\0"
        header = bytearray()
        header += struct.pack("<Ihhi", PACKAGE_TAG, 835, 76, 512)
        header += struct.pack("<i", len(folder)) + folder
        header += struct.pack("<I7i", 0x028A0009, 12, 105, 34, 4096, 7, 2048, 4800)
        summary = parse_package_summary(bytes(header))
        self.assertEqual(summary.tag, "0x9E2A83C1")
        self.assertEqual(summary.file_version, 835)
        self.assertEqual(summary.licensee_version, 76)
        self.assertEqual(summary.folder_name, "None")
        self.assertEqual(summary.export_count, 34)

    def test_native_inventory_counts_and_versions(self) -> None:
        inventory = json.loads(
            (ROOT / "evidence" / "native-inventory" / "pc-steam-build-20087529" / "native-inventory.json").read_text(encoding="utf-8")
        )
        self.assertEqual(inventory["schema"], "gowr_native_inventory_v1")
        self.assertEqual(inventory["fileCount"], 2606)
        self.assertEqual(inventory["totalBytes"], 74256775264)
        self.assertEqual(inventory["packageSummaryErrors"], 0)
        expected = {".war": 1859, ".upk": 566, ".tfc": 68, ".bik": 113}
        self.assertEqual({key: value["count"] for key, value in inventory["byExtension"].items()}, expected)
        versions = {
            (row["packageSummary"]["file_version"], row["packageSummary"]["licensee_version"])
            for row in inventory["files"]
            if "packageSummary" in row
        }
        self.assertEqual(versions, {(835, 76)})
        self.assertEqual(len(inventory["anchors"]), 3)

    def test_uvstream_layout_at_full_precision_flag(self) -> None:
        data = bytearray(128)
        raw_base = 64
        struct.pack_into("<6i", data, raw_base - 12, 2, 20, 3, 0, 20, 3)
        result = self.uv_guard.detect_uv_stream(bytes(data), raw_base, 20, 3)
        self.assertEqual(result["status"], "repo_verified")
        self.assertEqual(result["payload_delta_from_data_rel"], 12)
        self.assertEqual(result["uv0_offset"], 12)
        self.assertEqual(result["uv1_offset"], 16)

    def test_uvstream_layout_at_bulk_header(self) -> None:
        data = bytearray(128)
        raw_base = 80
        struct.pack_into("<6i", data, raw_base - 16, 1, 24, 4, 1, 24, 4)
        result = self.uv_guard.detect_uv_stream(bytes(data), raw_base, 24, 4)
        self.assertEqual(result["status"], "repo_verified")
        self.assertEqual(result["payload_delta_from_data_rel"], 8)
        self.assertEqual(result["uv0_offset"], 16)

    def test_migration_manifest_has_expected_corpus(self) -> None:
        manifest = json.loads((ROOT / "inventory" / "legacy-migration.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["itemCount"], 130)
        self.assertEqual(manifest["countsByKind"], {"legacy-evidence": 6, "legacy-probe": 124})

    def test_promoted_uv_guard_matches_archived_source(self) -> None:
        maintained = ROOT / "src" / "gowreloaded_static_uvstream_regression_guard.py"
        archived = ROOT / "research" / "legacy-probes" / maintained.name
        self.assertEqual(sha256_file(maintained), sha256_file(archived))

    def test_claim_ids_match_file_names(self) -> None:
        claims = sorted((ROOT / "evidence" / "claims").glob("*.json"))
        self.assertEqual(len(claims), 11)
        for path in claims:
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(path.stem, value["id"])


if __name__ == "__main__":
    unittest.main()
