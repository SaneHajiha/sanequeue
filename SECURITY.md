# Security

SaneQueue can control live calls. Use authenticated users, queue scoping, explicit roles, a strong session secret, TLS and a restricted AMI account. Default roles and anonymous mode are read-only. Supervisor listening destinations are configured per user. Do not commit config.ini, credentials, call logs, recordings, audit files or report databases.

The new application targets Python 3.10–3.12 and modern Flask. Legacy Python 3.6 compatibility exists to migrate existing PBXs; it does not make the underlying EOL runtime suitable for exposed services. Keep the dashboard behind trusted network access and update supported runtimes/dependencies.

Report vulnerabilities privately to the repository owner via GitHub's private vulnerability reporting when enabled. If that option is unavailable, open an issue requesting a private contact without publishing exploit details, passwords or caller data. Never include production credentials in bug reports.

Audit results reflect HTTP/AMI request acceptance. Asynchronous Originate acceptance is not proof that a supervisor answered or that audio monitoring began. Audit files contain user/queue/interface identifiers and must remain access-controlled.
