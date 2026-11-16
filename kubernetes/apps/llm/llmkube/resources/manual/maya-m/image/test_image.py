import hashlib
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class BuildCommandsTest(unittest.TestCase):
    def test_vision_import_preserves_recursive_source_fingerprint(self):
        env = os.environ.copy()
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        setting = re.search(r"\bPYTHONDONTWRITEBYTECODE=(\S+)", (HERE / "Dockerfile").read_text())
        if setting:
            env["PYTHONDONTWRITEBYTECODE"] = setting.group(1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ggml_vision_precision.py").write_text("VALUE = 1\n")

            def fingerprint():
                digest = hashlib.sha256()
                for file in sorted(p for p in root.rglob("*") if p.is_file()):
                    digest.update(file.relative_to(root).as_posix().encode() + b"\0" + file.read_bytes())
                return digest.hexdigest()

            before = fingerprint()
            subprocess.run([sys.executable, "-c", "import ggml_vision_precision"],
                           cwd=root, env=env, check=True)
            self.assertEqual(before, fingerprint(), "vision imports must not add hashed __pycache__ files")

    def test_daemon_and_workers_stay_under_pod_cgroup_limits(self):
        script = (HERE / "build.sh").read_text()
        self.assertIn('read -r quota period < "/sys/fs/cgroup$pod_cgroup/cpu.max"', script)
        self.assertIn('[ "$quota" != max ] && [ "$memory" != max ]', script)
        self.assertIn('> "/sys/fs/cgroup$container_cgroup/cgroup.procs"', script)
        self.assertIn('defaultCgroupParent = "%s"', script)
        self.assertNotIn('--opt cgroup-parent=', script)
        self.assertNotIn('exec buildctl-daemonless.sh', script)

    def test_only_runtime_injected_cuda_driver_may_be_unresolved(self):
        path = HERE / "verify.py"
        self.assertTrue(path.is_file(), "GPU-free verifier is missing")
        spec = importlib.util.spec_from_file_location("verify", path)
        assert spec is not None and spec.loader is not None
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        self.assertTrue(verifier.cmake_cache_matches("STRATA_PORTABLE:BOOL=ON\nCMAKE_CUDA_ARCHITECTURES:UNINITIALIZED=86\n"))
        self.assertFalse(verifier.cmake_cache_matches("STRATA_PORTABLE:BOOL=OFF\nCMAKE_CUDA_ARCHITECTURES:STRING=86\n"))
        self.assertFalse(verifier.cmake_cache_matches("STRATA_PORTABLE:BOOL=ON\nCMAKE_CUDA_ARCHITECTURES:STRING=89\n"))
        self.assertEqual(verifier.missing_dependencies("libcuda.so.1 => not found\n"), [])
        self.assertEqual(verifier.missing_dependencies("libcublas.so.13 => not found\n"), ["libcublas.so.13"])
        self.assertEqual(verifier.missing_dependencies("libstdc++.so.6 => /lib/libstdc++.so.6 (0x1)\n"), [])

    def test_both_cmake_paths_are_portable_and_bounded(self):
        path = HERE / "build_runtime.py"
        self.assertTrue(path.is_file(), "native build helper is missing")
        spec = importlib.util.spec_from_file_location("build_runtime", path)
        assert spec is not None and spec.loader is not None
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        for target in ("maya", "maya-vision"):
            conf = ["cmake", "-S", "/source"]
            build = ["cmake", "--build", "/build", "--target", target, "-j", "24"]
            configured, bounded = helper.cmake_commands(conf, build)
            self.assertIn("-DSTRATA_PORTABLE=ON", configured)
            self.assertEqual(bounded[-2:], ["-j", "4"])
            self.assertEqual(build[-1], "24", "must not mutate caller commands")


if __name__ == "__main__":
    unittest.main()
