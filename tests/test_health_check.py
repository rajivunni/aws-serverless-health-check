import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location("health_check", Path(__file__).parents[1] / "health_check.py")
health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health)


class HealthChecks(unittest.TestCase):
    def test_cli_uses_argument_list_without_shell(self):
        result = Mock(returncode=0, stdout='{"MetricAlarms": []}')
        with patch.object(health.subprocess, "run", return_value=result) as call:
            health.check_alarm("demo; echo not-run", "eu-west-2", "example alarm")
        args, kwargs = call.call_args
        self.assertIsInstance(args[0], list)
        self.assertIn("demo; echo not-run", args[0])
        self.assertIn("example alarm", args[0])
        self.assertFalse(kwargs.get("shell", False))

    def test_cli_failure_does_not_expose_stderr(self):
        result = Mock(returncode=1, stdout="", stderr="private provider response")
        with patch.object(health.subprocess, "run", return_value=result):
            response = health.aws(["dynamodb", "scan"], "demo", "eu-west-2")
        self.assertIn("error", response)
        self.assertNotIn("private provider response", str(response))

    def test_timeout_is_error(self):
        with patch.object(health.subprocess, "run", side_effect=subprocess.TimeoutExpired("aws", 60)):
            self.assertIn("error", health.aws([], "demo", "eu-west-2"))

    def test_invalid_json_is_error(self):
        with patch.object(health.subprocess, "run", return_value=Mock(returncode=0, stdout="invalid")):
            self.assertIn("error", health.aws([], "demo", "eu-west-2"))

    def test_dynamo_count_includes_all_pages(self):
        responses = [{"Count": 2, "LastEvaluatedKey": {"id": {"S": "demo-next"}}}, {"Count": 3}]
        with patch.object(health, "aws", side_effect=responses) as call:
            self.assertEqual(health.count_dynamo_items("demo", "eu-west-2", "example", "state", "failure"), 5)
        self.assertIn("--exclusive-start-key", call.call_args.args[0])

    def test_partial_scan_does_not_return_count(self):
        with patch.object(health, "aws", side_effect=[{"Count": 2, "LastEvaluatedKey": {"id": {"S": "demo"}}}, {"error": "denied"}]):
            value = health.count_dynamo_items("demo", "eu-west-2", "example", "state", "failure")
        self.assertTrue(value.startswith("ERROR"))

    def test_repeated_cursor_is_error(self):
        page = {"Count": 1, "LastEvaluatedKey": {"id": {"S": "demo"}}}
        with patch.object(health, "aws", return_value=page):
            self.assertIn("Repeated", health.scan_count("demo", "eu-west-2", "example", "x", {}, {}))

    def test_sns_paginates(self):
        with patch.object(health, "aws", side_effect=[
            {"Subscriptions": [{"SubscriptionArn": "arn:aws:sns:eu-west-2:123456789012:example:1"}], "NextToken": "demo-page"},
            {"Subscriptions": [{"SubscriptionArn": "PendingConfirmation"}]},
        ]):
            self.assertEqual(health.check_sns("demo", "eu-west-2", "example"), {"confirmed": 1, "pending": 1})

    def test_good_checks_pass(self):
        self.assertEqual(health.assess("OK", 0, 0, 0, 2, {"confirmed": 1, "pending": 0}, 0), [])

    def test_unknown_alarm_and_failed_emails_are_not_success(self):
        issues = health.assess("NOT FOUND", 0, 0, 3, 2, {"confirmed": 1, "pending": 0}, 0)
        self.assertEqual(len(issues), 2)

    def test_check_errors_and_missing_sns_are_not_success(self):
        issues = health.assess("ERROR: denied", "ERROR", "ERROR", "ERROR", "ERROR", {"error": "denied"}, 0)
        self.assertEqual(len(issues), 6)

    def test_pending_label_does_not_claim_age(self):
        issues = health.assess("OK", 0, 1, 0, 0, {"confirmed": 1, "pending": 0}, 0)
        self.assertIn("age not evaluated", issues[0])

    def test_main_error_exit(self):
        with patch.object(health, "check_alarm", return_value="NOT FOUND"), \
             patch.object(health, "count_dynamo_items", return_value=0), \
             patch.object(health, "check_recent_activity", return_value=0), \
             patch.object(health, "check_sns", return_value={"confirmed": 1, "pending": 0}), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            code = health.main(["--profile", "demo", "--alarm", "example", "--workflow-table", "example", "--email-table", "example", "--sns-topic", "example"])
        self.assertEqual(code, 1)
        self.assertNotIn("Configured checks passed", output.getvalue())


if __name__ == "__main__":
    unittest.main()
