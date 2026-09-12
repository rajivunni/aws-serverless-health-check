# AWS serverless operational checks

A sanitized Python CLI example based on operational monitoring of an AWS subscription-provisioning backend. Resource names are supplied by the operator. No client names, account inventory, credentials or production check results are included.

## What it checks

- A CloudWatch metric alarm's state.
- Failed and pending workflow records in DynamoDB.
- Failed email-command records in DynamoDB.
- Recent successful workflow records.
- Confirmed and unconfirmed SNS subscriptions.

This script inspects records and configuration. It does not invoke Lambda, repair data, send messages, deploy resources or prove that an alert actually reaches a recipient.

## Local use

Requires Python 3.10+ and AWS CLI v2, with an explicitly configured profile authorized to read the target resources. The operator must supply their own resource names. Example names below are fictitious.

```bash
python3 health_check.py \
  --profile demo-read-only \
  --region eu-west-2 \
  --alarm example-workflow-failures \
  --workflow-table example-workflows \
  --email-table example-email-commands \
  --sns-topic arn:aws:sns:eu-west-2:123456789012:example-alerts
```

The AWS identity needs `cloudwatch:DescribeAlarms`, `dynamodb:Scan`, and `sns:ListSubscriptionsByTopic` on the appropriate resources. No credentials are stored in the script. Read operations can incur charges and DynamoDB capacity usage. Test against a separate demo account before using an adaptation on a live system.

Expected table fields:

| Table | Fields used |
| --- | --- |
| Workflow | `state` as a string (`failure`, `pending`, `success`); `updatedAt` as a number of Unix seconds |
| Email commands | `status` as a string (`failed`) |

Adapt these assumptions to the actual schema. An attribute mismatch can return zero matching items rather than an error.

Exit status is zero only when the configured checks complete and report no flagged condition. Errors, unknown or missing alarms, incomplete scans, failed emails, and unconfirmed SNS routing produce a nonzero result.

## Offline tests

```bash
python3 -B scripts/run_offline_tests.py
```

Tests use mocks and do not call AWS. The runner rejects sockets and external subprocesses. All 13 tests pass locally. They were added for this public-copy preparation, not as a claim about historical client delivery.

The included GitHub Actions workflow only runs those tests, without cloud credentials or deployment steps. A hosted run has not been performed for this new package. See [SECURITY.md](SECURITY.md).

## Limitations

- Scans are paginated but capped at 100 pages per check. Reaching the cap is an error, never a partial-success result.
- Separate scans are not a transactional snapshot. Updates during a run can affect counts.
- A failure-count baseline cannot distinguish old and new item identities. It is not full reconciliation.
- Pending items are reported for review, not asserted to be stuck; no age threshold is evaluated.
- Zero recent successes is informational because expected traffic is not known.
- Lambda metrics, trace analysis, provider reconciliation, end-to-end alert delivery and service recovery are outside this example.

The public copy replaces shell-string execution with argument lists and stops reporting success when checks fail. No live AWS validation was performed during preparation.
