"""Tests for the repository-scoped Git HTTPS credential helper.

The helper must answer only exact in-scope ``get`` requests for
https://github.com/timblakely/cogito-ops[.git], read the projected token
file fresh on every request, and fail closed otherwise without ever
echoing the token back on failure paths.
"""
import builtins
import importlib.util
import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "kubernetes/apps/llm/opencode/app"
HELPER = APP / "github-credential-helper.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("github_credential_helper", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request(action="get", lines=None, **attrs):
    if lines is not None:
        return "\n".join(lines)
    body = [action] + [f"{key}={value}" for key, value in attrs.items()]
    return "\n".join(body) + "\n\n"


def request_attrs(**attrs):
    """stdin for `git credential fill`: attribute lines, no action line."""
    return "".join(f"{key}={value}\n" for key, value in attrs.items()) + "\n"


def run_helper(module, stdin_text, token_path):
    stdout, stderr = io.StringIO(), io.StringIO()
    code = module.run(io.StringIO(stdin_text), stdout, stderr, token_path)
    return code, stdout.getvalue(), stderr.getvalue()


class FakeTokenMixin:
    FAKE_TOKEN = "ghs_FAKE_ONLY_NOT_A_REAL_VALUE"

    def setUp(self):
        self.helper = load_helper()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.token_dir = Path(self._tmp.name)
        self.token = self.token_dir / "token"
        self.token_path = str(self.token)

    def write_token(self, text):
        self.token.write_text(text)


class HelperSuccessTests(FakeTokenMixin, unittest.TestCase):
    def test_get_for_plain_repo_path_emits_username_password_and_blank_line(self):
        self.write_token(self.FAKE_TOKEN + "\n")
        stdin = request(protocol="https", host="github.com",
                        path="timblakely/cogito-ops")
        code, out, err = run_helper(self.helper, stdin, self.token_path)
        self.assertEqual(code, 0)
        self.assertEqual(out, "username=x-access-token\n"
                              f"password={self.FAKE_TOKEN}\n\n")
        self.assertEqual(err, "")


class HelperScopeTests(FakeTokenMixin, unittest.TestCase):
    def assert_declined_without_token_access(self, stdin):
        self.write_token(self.FAKE_TOKEN + "\n")
        real_open = builtins.open
        opened = []

        def spy_open(file, *args, **kwargs):
            opened.append(str(file))
            return real_open(file, *args, **kwargs)

        with mock.patch.object(builtins, "open", spy_open):
            code, out, err = run_helper(self.helper, stdin, self.token_path)
        self.assertEqual(code, 1, msg=f"stdin={stdin!r}")
        self.assertEqual(out, "")
        self.assertNotIn(self.FAKE_TOKEN, err)
        self.assertEqual(opened, [], "out-of-scope request must not open files")

    def test_plain_http_protocol_is_declined(self):
        self.assert_declined_without_token_access(
            request(protocol="http", host="github.com", path="timblakely/cogito-ops"))

    def test_other_host_is_declined(self):
        self.assert_declined_without_token_access(
            request(protocol="https", host="gitlab.com", path="timblakely/cogito-ops"))

    def test_gitea_subdomain_like_github_prefix_is_declined(self):
        self.assert_declined_without_token_access(
            request(protocol="https", host="github.com.evil.example",
                    path="timblakely/cogito-ops"))

    def test_host_with_port_is_declined(self):
        self.assert_declined_without_token_access(
            request(protocol="https", host="github.com:443",
                    path="timblakely/cogito-ops"))

    def test_other_repository_path_is_declined(self):
        self.assert_declined_without_token_access(
            request(protocol="https", host="github.com", path="someone-else/repo"))

    def test_missing_path_is_declined(self):
        self.assert_declined_without_token_access(
            request(protocol="https", host="github.com"))


class HelperGitSuffixAndUsernameTests(FakeTokenMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write_token(self.FAKE_TOKEN + "\n")

    def get(self, **attrs):
        stdin = request(protocol="https", host="github.com",
                        path="timblakely/cogito-ops.git", **attrs)
        return run_helper(self.helper, stdin, self.token_path)

    def test_dot_git_suffix_is_accepted(self):
        code, out, err = self.get()
        self.assertEqual(code, 0)
        self.assertEqual(out, "username=x-access-token\n"
                              f"password={self.FAKE_TOKEN}\n\n")

    def test_explicit_x_access_token_username_is_accepted(self):
        code, out, _ = self.get(username="x-access-token")
        self.assertEqual(code, 0)
        self.assertIn(f"password={self.FAKE_TOKEN}\n\n", out)

    def test_empty_username_is_accepted(self):
        code, out, _ = self.get(username="")
        self.assertEqual(code, 0)
        self.assertIn(f"password={self.FAKE_TOKEN}\n\n", out)

    def test_foreign_username_is_declined_without_token_access(self):
        real_open = builtins.open
        opened = []

        def spy_open(file, *args, **kwargs):
            opened.append(str(file))
            return real_open(file, *args, **kwargs)

        with mock.patch.object(builtins, "open", spy_open):
            code, out, _ = self.get(username="tim")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(opened, [])


class HelperActionTests(FakeTokenMixin, unittest.TestCase):
    IN_SCOPE = {"protocol": "https", "host": "github.com",
                "path": "timblakely/cogito-ops"}

    def run_ignoring_action(self, action):
        self.write_token(self.FAKE_TOKEN + "\n")
        real_open = builtins.open
        opened = []

        def spy_open(file, *args, **kwargs):
            opened.append(str(file))
            return real_open(file, *args, **kwargs)

        with mock.patch.object(builtins, "open", spy_open):
            code, out, err = run_helper(self.helper,
                                        request(action, **self.IN_SCOPE),
                                        self.token_path)
        self.assertEqual(out, "")
        self.assertNotIn(self.FAKE_TOKEN, err)
        self.assertEqual(opened, [], f"{action} must not touch any file")
        return code

    def test_store_is_ignored_without_output_or_file_access(self):
        self.assertEqual(self.run_ignoring_action("store"), 0)

    def test_erase_is_ignored_without_output_or_file_access(self):
        self.assertEqual(self.run_ignoring_action("erase"), 0)

    def test_unknown_action_is_declined_without_output_or_file_access(self):
        self.assertEqual(self.run_ignoring_action("capability"), 1)


class HelperTokenFailureTests(FakeTokenMixin, unittest.TestCase):
    IN_SCOPE = {"protocol": "https", "host": "github.com",
                "path": "timblakely/cogito-ops"}

    def assert_fail_closed(self):
        code, out, err = run_helper(self.helper,
                                    request(**self.IN_SCOPE), self.token_path)
        self.assertEqual(code, 1)
        self.assertIn(out, ("", "quit=true\n\n"),
                      "must not emit credential fields")
        self.assertNotIn("password", out)
        self.assertIn("github-credential-helper", err)
        joined = out + err
        self.assertNotIn("Traceback", joined)
        for secret in (self.FAKE_TOKEN, "ghs_", self.token_path):
            self.assertNotIn(secret, joined)

    def test_missing_token_file_fails_closed(self):
        self.assert_fail_closed()

    def test_empty_token_file_fails_closed(self):
        self.write_token("")
        self.assert_fail_closed()

    def test_whitespace_only_token_fails_closed(self):
        self.write_token("   \n")
        self.assert_fail_closed()

    def test_internal_space_token_fails_closed(self):
        self.write_token("ghs split value\n")
        self.assert_fail_closed()

    def test_second_trailing_newline_fails_closed(self):
        self.write_token(self.FAKE_TOKEN + "\n\n")
        self.assert_fail_closed()

    def test_control_character_token_fails_closed(self):
        self.write_token("ghs\ttabbed\n")
        self.assert_fail_closed()

    def test_non_utf8_token_bytes_fail_closed(self):
        self.token.write_bytes(b"ghs\xff\xfebad\n")
        self.assert_fail_closed()

    def test_unreadable_token_file_fails_closed(self):
        self.write_token(self.FAKE_TOKEN + "\n")
        self.token.chmod(0o000)
        self.addCleanup(self.token.chmod, 0o600)
        self.assert_fail_closed()


class HelperMalformedRequestTests(FakeTokenMixin, unittest.TestCase):
    IN_SCOPE = ["protocol=https", "host=github.com", "path=timblakely/cogito-ops"]

    def assert_declined_no_file_access(self, lines):
        self.write_token(self.FAKE_TOKEN + "\n")
        real_open = builtins.open
        opened = []

        def spy_open(file, *args, **kwargs):
            opened.append(str(file))
            return real_open(file, *args, **kwargs)

        with mock.patch.object(builtins, "open", spy_open):
            code, out, err = run_helper(self.helper, request(lines=[*lines, ""]),
                                        self.token_path)
        self.assertEqual(code, 1, msg=f"lines={lines!r}")
        self.assertEqual(out, "")
        self.assertNotIn(self.FAKE_TOKEN, err)
        self.assertEqual(opened, [])

    def test_duplicate_path_key_is_declined(self):
        self.assert_declined_no_file_access(
            ["get", *self.IN_SCOPE, "path=timblakely/cogito-ops.git", ""])

    def test_duplicate_host_key_is_declined(self):
        self.assert_declined_no_file_access(
            ["get", "protocol=https", "host=github.com", "host=evil.example",
             "path=timblakely/cogito-ops", ""])

    def test_duplicate_protocol_and_username_keys_are_declined(self):
        for key in ("protocol=http", "username=attacker"):
            self.assert_declined_no_file_access(
                ["get", *self.IN_SCOPE, key, ""])

    def test_line_without_equals_is_declined(self):
        self.assert_declined_no_file_access(
            ["get", "protocol=https", "host=github.com", "garbage",
             "path=timblakely/cogito-ops", ""])

    def test_attribute_line_in_action_position_is_declined(self):
        self.assert_declined_no_file_access(
            ["protocol=https", "host=github.com", "path=timblakely/cogito-ops", ""])

    def test_empty_request_is_declined(self):
        self.assert_declined_no_file_access([""])

    def test_unknown_extra_keys_are_ignored_on_in_scope_get(self):
        self.write_token(self.FAKE_TOKEN + "\n")
        lines = ["get", *self.IN_SCOPE, "state=whatever", "capability[]=autofill", ""]
        code, out, err = run_helper(self.helper, request(lines=lines + [""]),
                                    self.token_path)
        self.assertEqual(code, 0)
        self.assertIn(f"password={self.FAKE_TOKEN}\n\n", out)


class HelperRotationCliTests(FakeTokenMixin, unittest.TestCase):
    IN_SCOPE = {"protocol": "https", "host": "github.com",
                "path": "timblakely/cogito-ops"}

    def test_token_rotation_swapped_by_symlink_dir_is_seen_without_reload(self):
        """Kubernetes projected Secrets swap a symlink atomically; the helper
        re-reads the token on every get and must never serve the old value."""
        root = self.token_dir
        v1, v2 = root / "data-v1", root / "data-v2"
        v1.mkdir()
        v2.mkdir()
        (v1 / "token").write_text(self.FAKE_TOKEN + "\n")
        (v2 / "token").write_text("ghs_ROTATED_SECOND_VALUE\n")
        current = root / "current"
        current.symlink_to(v1, target_is_directory=True)
        token_path = str(current / "token")

        code, out, _ = run_helper(self.helper, request(**self.IN_SCOPE), token_path)
        self.assertEqual(code, 0)
        self.assertIn(f"password={self.FAKE_TOKEN}\n\n", out)

        staged = root / "next-link"
        staged.symlink_to(v2, target_is_directory=True)
        staged.rename(current)  # atomic swap, same helper module lifetime

        code, out, _ = run_helper(self.helper, request(**self.IN_SCOPE), token_path)
        self.assertEqual(code, 0)
        self.assertIn("password=ghs_ROTATED_SECOND_VALUE\n\n", out)
        self.assertNotIn(self.FAKE_TOKEN, out)

    def test_cli_default_token_path_fails_closed_without_secret(self):
        secret = "/var/run/secrets/github/token"
        if Path(secret).exists():
            self.skipTest(f"{secret} exists on this host; refusing to probe it")
        import subprocess
        proc = subprocess.run(
            ["python3", str(HELPER)],
            input=request(**self.IN_SCOPE),
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "quit=true\n\n")
        self.assertIn("github-credential-helper", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_cli_reads_stdin_until_blank_line_over_real_pipe(self):
        import subprocess
        self.write_token(self.FAKE_TOKEN + "\n")
        driver = (
            "import importlib.util,sys;"
            f"s=importlib.util.spec_from_file_location('h',r'{HELPER}');"
            "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
            "sys.exit(m.run(sys.stdin,sys.stdout,sys.stderr,sys.argv[1]))")
        proc = subprocess.run(
            ["python3", "-c", driver, self.token_path,
             "trailing-argument-after-blank-line"],
            input=request(**self.IN_SCOPE) + "path=never/reached\n\n",
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "username=x-access-token\n"
                                      f"password={self.FAKE_TOKEN}\n\n")


GITCONFIG = APP / "github.gitconfig"
IN_CLUSTER_HELPER_PATH = "/etc/opencode/github/github-credential-helper.py"


class GitconfigContractTests(unittest.TestCase):
    def setUp(self):
        self.text = GITCONFIG.read_text()

    def test_config_enables_http_path_and_only_scoped_helper(self):
        self.assertIn("useHttpPath = true", self.text)
        helper_lines = [line.strip() for line in self.text.splitlines()
                        if line.strip().startswith("helper")]
        self.assertEqual(helper_lines,
                         ["helper =",
                          f"helper = !python3 {IN_CLUSTER_HELPER_PATH}"],
                         "managed system file must reset earlier helpers, "
                         "then add the scoped helper")

    def test_config_contains_no_auth_material(self):
        lowered = self.text.lower()
        for forbidden in ("password", "x-access-token", "ghp_", "ghs_",
                          "@github.com", "token"):
            self.assertNotIn(forbidden, lowered)


class GitCredentialFillIntegrationTests(FakeTokenMixin, unittest.TestCase):
    IN_SCOPE = {"protocol": "https", "host": "github.com",
                "path": "timblakely/cogito-ops"}

    def setUp(self):
        super().setUp()
        self.git = shutil.which("git")
        if self.git is None:
            self.skipTest("git not available")
        assert self.git is not None
        self.write_token(self.FAKE_TOKEN + "\n")
        staged_script = self.token_dir / "github-credential-helper.py"
        staged_text = HELPER.read_text().replace(
            "/var/run/secrets/github/token", str(self.token))
        self.assertNotIn("/var/run/secrets", staged_text)
        staged_script.write_text(staged_text)
        staged_config = self.token_dir / "gitconfig"
        staged_config.write_text(
            GITCONFIG.read_text().replace(IN_CLUSTER_HELPER_PATH,
                                          str(staged_script)))
        self.home = self.token_dir / "home"
        self.home.mkdir()
        self.env = {"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
                    "HOME": str(self.home),
                    "GIT_CONFIG_SYSTEM": str(staged_config),
                    "GIT_CONFIG_GLOBAL": str(self.home / "absent-gitconfig"),
                    "GIT_TERMINAL_PROMPT": "0"}

    def fill(self, **attrs):
        import subprocess
        return subprocess.run([self.git, "credential", "fill"],
                              input=request_attrs(**attrs), capture_output=True,
                              text=True, env=self.env, timeout=60,
                              cwd=str(self.home))

    def test_real_git_fill_gets_token_only_credential_for_scoped_repo(self):
        proc = self.fill(**self.IN_SCOPE)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        fields = dict(line.split("=", 1) for line in proc.stdout.splitlines()
                      if "=" in line)
        self.assertEqual(fields["protocol"], "https")
        self.assertEqual(fields["host"], "github.com")
        self.assertEqual(fields["path"], "timblakely/cogito-ops")
        self.assertEqual(fields["username"], "x-access-token")
        self.assertEqual(fields["password"], self.FAKE_TOKEN)
        self.assertNotIn(self.FAKE_TOKEN, proc.stderr)

    def test_real_git_fill_for_other_repo_never_sees_token(self):
        proc = self.fill(protocol="https", host="github.com",
                         path="timblakely/some-other-repo")
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn(self.FAKE_TOKEN, proc.stdout + proc.stderr)


class HelperArgvProtocolTests(FakeTokenMixin, unittest.TestCase):
    """Git invokes external helpers as ``helper get|store|erase`` and writes
    only key=value attribute lines to stdin, terminated by a blank line."""
    ATTRS = "protocol=https\nhost=github.com\npath=timblakely/cogito-ops\n\n"

    def run_argv(self, action, stdin_text=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = self.helper.run(io.StringIO(stdin_text or self.ATTRS), stdout,
                               stderr, self.token_path, action)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_get_action_from_argv_with_attributes_only_stdin(self):
        self.write_token(self.FAKE_TOKEN + "\n")
        code, out, err = self.run_argv("get")
        self.assertEqual(code, 0)
        self.assertEqual(out, "username=x-access-token\n"
                              f"password={self.FAKE_TOKEN}\n\n")
        self.assertEqual(err, "")

    def test_store_action_from_argv_is_ignored(self):
        self.write_token(self.FAKE_TOKEN + "\n")
        code, out, err = self.run_argv("store")
        self.assertEqual((code, out), (0, ""))

    def test_action_line_in_attribute_stdin_is_malformed_when_action_given(self):
        self.write_token(self.FAKE_TOKEN + "\n")
        code, out, err = self.run_argv("get", "get\n" + self.ATTRS)
        self.assertEqual((code, out), (1, ""))


if __name__ == "__main__":
    unittest.main()
