# Administrator access

There is no public default password. New installations must ask the owner to choose a password; only its hash belongs in `local_accounts.json`. The test installation uses username `admin` and a randomly provisioned password delivered in private local/server handoff files. Those files never belong in Git, screenshots or release archives.

For a release containing the recovery script, run it from a trusted server terminal:

```bash
cd /opt/sanequeue
sudo -u sanequeue .venv/bin/python scripts/reset_password.py \
  --state /var/lib/sanequeue --username admin
sudo systemctl restart sanequeue
```

Enter the new 12–200 character password twice at the hidden prompt. Existing role and phone are preserved. A missing account or empty/mismatched password is rejected. Stop editing users through the web during offline recovery. Restart only the dashboard so its cached registry reloads and old sessions fail password-version validation; do not restart Asterisk. Adjust paths for your installation. Password hashes cannot reveal the original password.
