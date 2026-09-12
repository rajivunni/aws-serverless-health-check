# Security and operating boundaries

This example is read-only but must still be treated as an AWS client. The operator supplies the account access and resource names. No credentials, client inventory, private event records or production check reports are included.

- Use a dedicated read-only identity scoped to the intended tables, alarm and SNS topic.
- Never commit AWS configuration, environment files, private keys or report output.
- The tool launches AWS CLI using an argument list, not a shell command. It does not print raw CLI stderr or service payloads.
- Cloud reads consume resources and may incur charges. DynamoDB scans can be expensive even when few records match a filter.
- Test on a separate demo environment and confirm the table schemas before relying on counts.
- Successful checks do not prove full reconciliation, notification delivery, correct Lambda execution, or overall system health.
- No cloud provisioning, repair or notification-send command is included in the validation workflow.

The offline test runner rejects socket connections and external subprocesses. Unit tests replace the service boundary with mocked responses. No live cloud validation was performed as part of portfolio preparation.

If reporting an issue, omit credentials, real resource identifiers, private records and raw provider responses. Use synthetic reproduction data.
