# Security policy

Do not report suspected vulnerabilities in public issues if this repository is shared. Use the organization's private security contact/process.

Supported security baseline: Python 3.10+ source; production container uses Python 3.12. Secrets must never be committed. Rotate any credential that is accidentally exposed, even if the commit is later removed.

Release blockers include known exploitable high/critical dependency vulnerabilities, failing security tests, exposed credentials, disabled production authentication, wildcard production hosts, and unresolved high-risk threat-model findings.
