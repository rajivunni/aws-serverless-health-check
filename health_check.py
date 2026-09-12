#!/usr/bin/env python3
"""Read-only, configurable AWS operational checks for a serverless backend.

Sanitized portfolio adaptation. Offline tests do not contact AWS.
"""

import argparse
import json
import subprocess
import sys
import time


def aws(cmd: list[str], profile: str, region: str) -> dict:
    """Call the CLI without a shell and avoid printing raw provider errors."""
    full_cmd = ["aws", *cmd, "--profile", profile, "--region", region,
                "--no-cli-pager", "--output", "json"]
    try:
        result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return {"error": "AWS CLI is not installed"}
    except subprocess.TimeoutExpired:
        return {"error": "AWS CLI request timed out"}
    if result.returncode:
        return {"error": f"AWS CLI failed (exit {result.returncode}); check access and configuration"}
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "AWS CLI returned invalid JSON"}
    if not isinstance(response, dict):
        return {"error": "AWS CLI returned an unexpected response"}
    return response


def check_alarm(profile: str, region: str, alarm_name: str) -> str:
    response = aws(["cloudwatch", "describe-alarms", "--alarm-names", alarm_name], profile, region)
    if "error" in response:
        return f"ERROR: {response['error']}"
    alarms = response.get("MetricAlarms", [])
    return alarms[0].get("StateValue", "UNKNOWN") if alarms else "NOT FOUND"


def scan_count(profile: str, region: str, table: str, expression: str,
               names: dict, values: dict, max_pages: int = 100) -> int | str:
    """Count every page explicitly; fail instead of returning a partial count."""
    command = ["dynamodb", "scan", "--table-name", table,
               "--filter-expression", expression,
               "--expression-attribute-names", json.dumps(names),
               "--expression-attribute-values", json.dumps(values),
               "--select", "COUNT", "--no-paginate", "--limit", "1000"]
    total = 0
    cursor = None
    seen_cursors = set()
    for _ in range(max_pages):
        page_command = command + (["--exclusive-start-key", json.dumps(cursor)] if cursor else [])
        response = aws(page_command, profile, region)
        if "error" in response:
            return f"ERROR: {response['error']}"
        count = response.get("Count")
        if type(count) is not int or count < 0:
            return "ERROR: Missing or invalid DynamoDB count"
        total += count
        cursor = response.get("LastEvaluatedKey")
        if not cursor:
            return total
        identity = json.dumps(cursor, sort_keys=True)
        if identity in seen_cursors:
            return "ERROR: Repeated DynamoDB page cursor"
        seen_cursors.add(identity)
    return "ERROR: Scan page limit reached; result is incomplete"


def count_dynamo_items(profile: str, region: str, table: str,
                       attr_name: str, attr_value: str) -> int | str:
    return scan_count(profile, region, table, "#s = :val",
                      {"#s": attr_name}, {":val": {"S": attr_value}})


def check_recent_activity(profile: str, region: str, table: str, days: int = 7) -> int | str:
    since = int(time.time()) - days * 86400
    return scan_count(profile, region, table, "#s = :succ AND #u > :since",
                      {"#s": "state", "#u": "updatedAt"},
                      {":succ": {"S": "success"}, ":since": {"N": str(since)}})


def check_sns(profile: str, region: str, topic_arn: str) -> dict:
    command = ["sns", "list-subscriptions-by-topic", "--topic-arn", topic_arn, "--no-paginate"]
    confirmed = pending = 0
    token = None
    seen_tokens = set()
    for _ in range(100):
        response = aws(command + (["--next-token", token] if token else []), profile, region)
        if "error" in response:
            return response
        subscriptions = response.get("Subscriptions")
        if not isinstance(subscriptions, list):
            return {"error": "Missing SNS subscription list"}
        for subscription in subscriptions:
            arn = subscription.get("SubscriptionArn", "")
            if arn.startswith("arn:"):
                confirmed += 1
            else:
                pending += 1
        token = response.get("NextToken")
        if not token:
            return {"confirmed": confirmed, "pending": pending}
        if token in seen_tokens:
            return {"error": "Repeated SNS page token"}
        seen_tokens.add(token)
    return {"error": "SNS page limit reached; result is incomplete"}


def assess(alarm: str, failures: int | str, pending: int | str,
           email_failures: int | str, recent: int | str, sns: dict,
           baseline: int) -> list[str]:
    issues = []
    if alarm != "OK":
        issues.append(f"Alarm is not confirmed OK: {alarm}")
    for label, value in [("Failed items", failures), ("Pending items", pending),
                         ("Failed emails", email_failures), ("Recent activity", recent)]:
        if type(value) is not int:
            issues.append(f"{label} could not be verified: {value}")
    if type(failures) is int and failures > baseline:
        issues.append(f"{failures - baseline} failures above the configured count baseline")
    if type(pending) is int and pending > 0:
        issues.append(f"{pending} pending items require review (age not evaluated)")
    if type(email_failures) is int and email_failures > 0:
        issues.append(f"{email_failures} failed email commands")
    if "error" in sns:
        issues.append(f"SNS could not be verified: {sns['error']}")
    elif not sns.get("confirmed") or sns.get("pending"):
        issues.append("SNS needs review: no confirmed subscription or unconfirmed subscriptions remain")
    return issues


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run read-only serverless operational checks")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--region", default="eu-west-2")
    parser.add_argument("--alarm", required=True)
    parser.add_argument("--workflow-table", required=True)
    parser.add_argument("--email-table", required=True)
    parser.add_argument("--sns-topic", required=True)
    parser.add_argument("--baseline-failures", type=int, default=0)
    args = parser.parse_args(argv)
    if args.baseline_failures < 0:
        parser.error("--baseline-failures must be zero or positive")

    alarm = check_alarm(args.profile, args.region, args.alarm)
    failures = count_dynamo_items(args.profile, args.region, args.workflow_table, "state", "failure")
    pending = count_dynamo_items(args.profile, args.region, args.workflow_table, "state", "pending")
    emails = count_dynamo_items(args.profile, args.region, args.email_table, "status", "failed")
    recent = check_recent_activity(args.profile, args.region, args.workflow_table)
    sns = check_sns(args.profile, args.region, args.sns_topic)
    sns_summary = ("ERROR: " + sns["error"] if "error" in sns else
                   f"{sns['confirmed']} confirmed, {sns['pending']} unconfirmed")
    for label, value in [("Alarm state", alarm), ("Failed items", failures),
                         ("Pending items", pending), ("Failed emails", emails),
                         ("Recent activity (7d)", recent), ("SNS routing", sns_summary)]:
        print(f"{label:<25} {value}")

    issues = assess(alarm, failures, pending, emails, recent, sns, args.baseline_failures)
    if issues:
        print("\nChecks need attention:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("\nConfigured checks passed. This is not a complete system-health guarantee.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
