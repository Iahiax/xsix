import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

SPACE_DIR = Path(__file__).resolve().parent
if str(SPACE_DIR) not in sys.path:
    sys.path.insert(0, str(SPACE_DIR))

from arabic_evaluation import (
    EVALUATION_CASES,
    EVALUATION_SUITE_VERSION,
    evaluate_responses,
    suite_fingerprint,
)


class HttpException(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class FakeFastAPI:
    def __init__(self, **_kwargs):
        pass

    def get(self, *_args, **_kwargs):
        return lambda function: function

    def post(self, *_args, **_kwargs):
        return lambda function: function

    def middleware(self, *_args, **_kwargs):
        return lambda function: function


class FakeComponent:
    def __init__(self):
        self.launch_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: self

    def launch(self, *_args, **kwargs):
        self.launch_calls.append(kwargs)
        return self, "", ""


class FakeGradio(types.ModuleType):
    Error = type("Error", (Exception,), {})
    Server = None

    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: FakeComponent()


def install_app_import_stubs():
    fastapi = types.ModuleType("fastapi")
    fastapi.FastAPI = FakeFastAPI
    fastapi.Header = lambda default="", **_kwargs: default
    fastapi.HTTPException = HttpException
    fastapi.Request = type("Request", (), {})
    gradio = FakeGradio("gradio")
    gradio.Server = FakeFastAPI
    spaces = types.ModuleType("spaces")

    def gpu_decorator(**options):
        def decorate(function):
            function.__spaces_gpu_duration__ = options.get("duration")
            return function

        return decorate

    spaces.GPU = gpu_decorator
    huggingface_hub = types.ModuleType("huggingface_hub")
    huggingface_hub.HfApi = Mock()
    huggingface_hub.hf_hub_download = Mock()
    runtime = types.ModuleType("model_runtime")
    runtime.PROJECT_MODEL_ID = "private/project-model"
    runtime.PROJECT_MODEL_REVISION = ""
    runtime.SAFETY_SYSTEM_PROMPT = "test system prompt"
    runtime.model_status = Mock(return_value={"ready": True, "state": "project_checkpoint_loaded"})
    runtime.generate = Mock(return_value={"content": "test reply", "tool_calls": []})
    runtime.evaluate_candidate_responses = Mock()
    trainer = types.ModuleType("trainer")
    trainer.train_candidate = Mock()
    feedback_store = types.ModuleType("feedback_store")
    feedback_store.save_correction = Mock()

    sys.modules.update(
        {
            "fastapi": fastapi,
            "gradio": gradio,
            "spaces": spaces,
            "huggingface_hub": huggingface_hub,
            "model_runtime": runtime,
            "trainer": trainer,
            "feedback_store": feedback_store,
        }
    )
    return runtime


def import_app():
    install_app_import_stubs()
    sys.modules.pop("app", None)
    return __import__("app")


class SpaceAccessTests(unittest.TestCase):
    def setUp(self):
        self.app = import_app()
        self.runtime = sys.modules["model_runtime"]
        self.payload = {"messages": [{"role": "user", "content": "hello"}]}
        self.env_patch = patch.dict(os.environ, {}, clear=False)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.runtime.generate.reset_mock()

    def test_gpu_callbacks_are_discoverable_from_space_entrypoint(self):
        self.assertEqual(self.app.generate.__spaces_gpu_duration__, 120)
        self.assertEqual(self.app._respond.__spaces_gpu_duration__, 120)
        self.assertEqual(self.app._train.__spaces_gpu_duration__, 240)
        self.assertEqual(self.app._evaluate_candidate.__spaces_gpu_duration__, 240)

    def test_gradio_launch_hosts_ui_and_api_on_one_server(self):
        self.assertIsInstance(self.app.api, FakeFastAPI)
        self.app.launch_app()
        self.assertEqual(len(self.app.demo.launch_calls), 1)
        launch_options = self.app.demo.launch_calls[0]
        self.assertIs(launch_options["_app"], self.app.api)
        self.assertEqual(launch_options["server_name"], "0.0.0.0")

    def test_missing_space_api_secret_is_unavailable_and_does_not_generate(self):
        os.environ.pop("SPACE_API_TOKEN", None)
        with self.assertRaises(HttpException) as raised:
            self.app.chat_completions(self.payload, "")
        self.assertEqual(raised.exception.status_code, 503)
        self.runtime.generate.assert_not_called()

    def test_incorrect_space_api_secret_is_unauthorized_and_does_not_generate(self):
        os.environ["SPACE_API_TOKEN"] = "expected-private-token"
        with self.assertRaises(HttpException) as raised:
            self.app.chat_completions(self.payload, "incorrect-token")
        self.assertEqual(raised.exception.status_code, 401)
        self.runtime.generate.assert_not_called()

    def test_unready_checkpoint_is_unavailable_and_does_not_generate(self):
        os.environ["SPACE_API_TOKEN"] = "expected-private-token"
        self.runtime.model_status.return_value = {
            "ready": False,
            "state": "checkpoint_load_failed",
            "error": "RepositoryNotFoundError",
        }
        with self.assertRaises(HttpException) as raised:
            self.app.chat_completions(self.payload, "expected-private-token")
        self.assertEqual(raised.exception.status_code, 503)
        self.runtime.generate.assert_not_called()

    def test_error_diagnostics_requires_the_space_api_token(self):
        os.environ.pop("SPACE_API_TOKEN", None)
        with self.assertRaises(HttpException) as raised:
            self.app.diagnostics_errors("")
        self.assertEqual(raised.exception.status_code, 503)

    def test_error_diagnostics_returns_only_a_safe_summary_when_authorized(self):
        os.environ["SPACE_API_TOKEN"] = "expected-private-token"
        snapshot = self.app.diagnostics_errors("expected-private-token")
        self.assertIn(snapshot["state"], {"healthy", "attention"})
        self.assertIn("recentErrors", snapshot)
        self.assertNotIn("SPACE_API_TOKEN", str(snapshot))
        self.assertNotIn("test-read-token", str(snapshot))

    def test_private_checkpoint_read_token_failure_never_loads_or_serves_a_base_model(self):
        read_token = "test-read-token"
        hub = types.ModuleType("huggingface_hub")
        hub_api = Mock()
        hub_api.model_info.side_effect = PermissionError("private model access denied")
        hub.HfApi = Mock(return_value=hub_api)
        hub.hf_hub_download = Mock(side_effect=PermissionError("private file access denied"))
        spaces = types.ModuleType("spaces")
        spaces.GPU = lambda **_kwargs: lambda function: function
        with patch.dict(
            sys.modules,
            {"huggingface_hub": hub, "spaces": spaces},
        ), patch.dict(
            os.environ,
            {
                "PROJECT_MODEL_ID": "private/project-model",
                "HF_READ_TOKEN": read_token,
            },
        ):
            module_name = "checkpoint_runtime_access_test"
            spec = importlib.util.spec_from_file_location(
                module_name,
                SPACE_DIR / "model_runtime.py",
            )
            runtime = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = runtime
            spec.loader.exec_module(runtime)

        hub.HfApi.assert_called_once_with(token=read_token)
        hub_api.model_info.assert_called_once_with(
            repo_id="private/project-model",
            files_metadata=True,
        )
        self.assertFalse(runtime.model_status()["ready"])
        self.assertIsNone(runtime._model)
        with self.assertRaises(RuntimeError):
            runtime.generate([{"role": "user", "content": "hello"}])

    def test_evaluation_blocked_checkpoint_does_not_load_base_or_adapter_weights(self):
        hub = types.ModuleType("huggingface_hub")
        model_info = types.SimpleNamespace(sha="revision-1", siblings=[])
        hub_api = Mock()
        hub_api.model_info.return_value = model_info
        hub.HfApi = Mock(return_value=hub_api)
        hub.hf_hub_download = Mock(side_effect=FileNotFoundError("no passing report"))

        evaluation = types.ModuleType("arabic_evaluation")
        evaluation.EVALUATION_CASES = []
        evaluation.model_artifact_fingerprint = Mock(return_value="fingerprint-1")
        evaluation.promotion_report_is_valid = Mock(return_value=False)
        spaces = types.ModuleType("spaces")
        spaces.GPU = lambda **_kwargs: lambda function: function

        module_name = "blocked_checkpoint_no_weights_test"
        with patch.dict(
            sys.modules,
            {
                "huggingface_hub": hub,
                "arabic_evaluation": evaluation,
                "spaces": spaces,
                "torch": None,
                "peft": None,
                "transformers": None,
            },
        ), patch.dict(
            os.environ,
            {
                "PROJECT_MODEL_ID": "private/project-model",
                "HF_READ_TOKEN": "test-read-token",
            },
        ):
            spec = importlib.util.spec_from_file_location(
                module_name,
                SPACE_DIR / "model_runtime.py",
            )
            runtime = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = runtime
            spec.loader.exec_module(runtime)

        self.assertEqual(runtime.model_status()["state"], "promotion_blocked")
        self.assertEqual(runtime._load_error, "promotion_evaluation_missing_or_failed")
        self.assertIsNone(runtime._model)
        self.assertIsNone(runtime._tokenizer)
        hub_api.model_info.assert_called_once()
        hub.hf_hub_download.assert_called_once()

    def test_saved_pending_report_loads_without_rerunning_candidate_scoring(self):
        hub = sys.modules["huggingface_hub"]
        hub.HfApi.return_value.model_info.return_value = SimpleNamespace(sha="candidate-revision")
        report = {
            "candidate_model_id": "team/model-candidate-123",
            "candidate": {"summary": {"semantic_review_complete": False}},
        }
        self.app.model_artifact_fingerprint = Mock(return_value="artifact-fingerprint")
        self.app.restore_pending_evaluation_report = Mock(return_value=report)
        self.app._review_table_rows = Mock(return_value=[["case-1"]])
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as saved:
            json.dump(report, saved)
            saved.flush()
            self.app.hf_hub_download = Mock(return_value=saved.name)
            with patch.dict(
                os.environ,
                {
                    "CANDIDATE_MODEL_REPO_PREFIX": "team/model",
                    "HF_WRITE_TOKEN": "test-write-token",
                },
            ):
                restored, status, _prompt_rows, rows, state = self.app._load_pending_evaluation_report(
                    "team/model-candidate-123"
                )
        self.assertEqual(restored, report)
        self.assertIn("دون إعادة تشغيل النموذج", status)
        self.assertEqual(rows, [["case-1"]])
        self.assertEqual(state, report)
        self.app.restore_pending_evaluation_report.assert_called_once()
        self.runtime.evaluate_candidate_responses.assert_not_called()

    def test_semantic_review_rejects_anonymous_and_non_allowlisted_accounts(self):
        review_rows = []
        report = {"candidate_model_id": "team/model-candidate-123"}
        for username, allowlist in ((None, "reviewer-test"), ("other-user", "reviewer-test")):
            with self.subTest(username=username), patch.dict(
                os.environ,
                {
                    "CANDIDATE_MODEL_REPO_PREFIX": "team/model",
                    "SEMANTIC_REVIEWER_USERNAMES": allowlist,
                },
            ):
                with self.assertRaises(self.app.gr.Error):
                    self.app._save_semantic_review(
                        "team/model-candidate-123",
                        review_rows,
                        report,
                        SimpleNamespace(username=username),
                    )
        sys.modules["huggingface_hub"].HfApi.assert_not_called()

    def test_semantic_review_requires_a_configured_allowlist(self):
        with patch.dict(
            os.environ,
            {
                "CANDIDATE_MODEL_REPO_PREFIX": "team/model",
                "SEMANTIC_REVIEWER_USERNAMES": "",
            },
        ):
            with self.assertRaises(self.app.gr.Error):
                self.app._save_semantic_review(
                    "team/model-candidate-123",
                    [],
                    {"candidate_model_id": "team/model-candidate-123"},
                    SimpleNamespace(username="reviewer-test"),
                )
        sys.modules["huggingface_hub"].HfApi.assert_not_called()

    def test_semantic_review_saves_the_authenticated_allowlisted_account(self):
        responses = {}
        for case in EVALUATION_CASES:
            responses[case["id"]] = ""
            for variant in case.get("prompt_variants", []):
                responses[f"{case['id']}::{variant['id']}"] = ""
        candidate = evaluate_responses(responses)
        report = {
            "suite_version": EVALUATION_SUITE_VERSION,
            "suite_fingerprint": suite_fingerprint(),
            "candidate_model_id": "team/model-candidate-123",
            "candidate_revision": "candidate-revision",
            "candidate_artifact_fingerprint": "artifact-fingerprint",
            "baseline_model_id": "team/current-model",
            "baseline_revision": "baseline-revision",
            "candidate": candidate,
        }
        rows = self.app._review_table_rows(report)
        for row in rows:
            row[2] = "accepted"
        hub_api = sys.modules["huggingface_hub"].HfApi.return_value
        hub_api.model_info.return_value = SimpleNamespace(siblings=[])
        with patch.dict(
            os.environ,
            {
                "CANDIDATE_MODEL_REPO_PREFIX": "team/model",
                "HF_WRITE_TOKEN": "test-write-token",
                "SEMANTIC_REVIEWER_USERNAMES": "reviewer-test",
            },
        ), patch.object(
            self.app,
            "model_artifact_fingerprint",
            return_value="artifact-fingerprint",
        ):
            saved, _status, _prompt_rows, _review_rows, _state = self.app._save_semantic_review(
                "team/model-candidate-123",
                rows,
                report,
                SimpleNamespace(username="reviewer-test"),
            )

        self.assertEqual(saved["semantic_review"]["reviewer"], "reviewer-test")
        self.assertIs(saved["semantic_review"]["reviewer_verified"], True)
        self.assertEqual(
            saved["semantic_review"]["reviewer_provider"],
            "huggingface_oauth",
        )
        self.assertTrue(
            all(
                case["semantic_review"]["reviewer"] == "reviewer-test"
                for case in saved["candidate"]["cases"]
            )
        )
        self.assertEqual(hub_api.upload_file.call_count, 2)

    def test_error_diagnostics_requires_the_space_api_token(self):
        os.environ.pop("SPACE_API_TOKEN", None)
        with self.assertRaises(HttpException) as raised:
            self.app.diagnostics_errors("")
        self.assertEqual(raised.exception.status_code, 503)

    def test_error_diagnostics_returns_only_a_safe_summary_when_authorized(self):
        os.environ["SPACE_API_TOKEN"] = "expected-private-token"
        snapshot = self.app.diagnostics_errors("expected-private-token")
        self.assertIn(snapshot["state"], {"healthy", "attention"})
        self.assertIn("recentErrors", snapshot)
        self.assertNotIn("SPACE_API_TOKEN", str(snapshot))
        self.assertNotIn("test-read-token", str(snapshot))

    def test_private_checkpoint_read_token_failure_never_loads_or_serves_a_base_model(self):
        read_token = "test-read-token"
        hub = types.ModuleType("huggingface_hub")
        hub_api = Mock()
        hub_api.model_info.side_effect = PermissionError("private model access denied")
        hub.HfApi = Mock(return_value=hub_api)
        hub.hf_hub_download = Mock(side_effect=PermissionError("private file access denied"))
        spaces = types.ModuleType("spaces")
        spaces.GPU = lambda **_kwargs: lambda function: function
        with patch.dict(
            sys.modules,
            {"huggingface_hub": hub, "spaces": spaces},
        ), patch.dict(
            os.environ,
            {
                "PROJECT_MODEL_ID": "private/project-model",
                "HF_READ_TOKEN": read_token,
            },
        ):
            module_name = "checkpoint_runtime_access_test"
            spec = importlib.util.spec_from_file_location(
                module_name,
                SPACE_DIR / "model_runtime.py",
            )
            runtime = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = runtime
            spec.loader.exec_module(runtime)

        hub.HfApi.assert_called_once_with(token=read_token)
        hub_api.model_info.assert_called_once_with(
            repo_id="private/project-model",
            files_metadata=True,
        )
        self.assertFalse(runtime.model_status()["ready"])
        self.assertIsNone(runtime._model)
        with self.assertRaises(RuntimeError):
            runtime.generate([{"role": "user", "content": "hello"}])

    def test_evaluation_blocked_checkpoint_does_not_load_base_or_adapter_weights(self):
        hub = types.ModuleType("huggingface_hub")
        model_info = types.SimpleNamespace(sha="revision-1", siblings=[])
        hub_api = Mock()
        hub_api.model_info.return_value = model_info
        hub.HfApi = Mock(return_value=hub_api)
        hub.hf_hub_download = Mock(side_effect=FileNotFoundError("no passing report"))

        evaluation = types.ModuleType("arabic_evaluation")
        evaluation.EVALUATION_CASES = []
        evaluation.model_artifact_fingerprint = Mock(return_value="fingerprint-1")
        evaluation.promotion_report_is_valid = Mock(return_value=False)
        spaces = types.ModuleType("spaces")
        spaces.GPU = lambda **_kwargs: lambda function: function

        module_name = "blocked_checkpoint_no_weights_test"
        with patch.dict(
            sys.modules,
            {
                "huggingface_hub": hub,
                "arabic_evaluation": evaluation,
                "spaces": spaces,
                "torch": None,
                "peft": None,
                "transformers": None,
            },
        ), patch.dict(
            os.environ,
            {
                "PROJECT_MODEL_ID": "private/project-model",
                "HF_READ_TOKEN": "test-read-token",
            },
        ):
            spec = importlib.util.spec_from_file_location(
                module_name,
                SPACE_DIR / "model_runtime.py",
            )
            runtime = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = runtime
            spec.loader.exec_module(runtime)

        self.assertEqual(runtime.model_status()["state"], "promotion_blocked")
        self.assertEqual(runtime._load_error, "promotion_evaluation_missing_or_failed")
        self.assertIsNone(runtime._model)
        self.assertIsNone(runtime._tokenizer)
        hub_api.model_info.assert_called_once()
        hub.hf_hub_download.assert_called_once()


if __name__ == "__main__":
    unittest.main()
