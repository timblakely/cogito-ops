import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class PrepareRuntimeTest(unittest.TestCase):
    def test_seed_preserves_retained_profile_and_config(self):
        spec = importlib.util.spec_from_file_location("prepare", HERE / "prepare.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seed, runtime = root / "seed", root / "runtime"
            for base in (seed, runtime):
                (base / "data").mkdir(parents=True)
            (seed / ".cogito-source-commit").write_text(module.SOURCE_COMMIT + "\n")
            (seed / "data/expert-profile-glm.bin").write_bytes(b"image default")
            (runtime / "data/expert-profile-glm.bin").write_bytes(b"retained calibration")
            (seed / "build").mkdir()
            (seed / "build/maya").write_bytes(b"baked native engine")
            (seed / "python-link").symlink_to("/usr/bin/python3.12")
            config = root / "retained.json"
            config.write_text(json.dumps({"model_name": "glm-5.3-flash", "gpu": [0, 1]}))
            before = config.read_bytes()
            module.prepare(seed, runtime, config)
            self.assertEqual((runtime / "data/expert-profile-glm.bin").read_bytes(), b"retained calibration")
            self.assertEqual((runtime / "build/maya").read_bytes(), b"baked native engine")
            self.assertTrue((runtime / "python-link").is_symlink())
            self.assertEqual(config.read_bytes(), before)
            self.assertEqual((runtime / "maya-maya-m.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
