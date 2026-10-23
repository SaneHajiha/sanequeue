## Summary

Describe the user-facing change, affected queues/roles, and reason.

## Validation

- [ ] No real AMI/production PBX mutations in development tests
- [ ] `python -m unittest tests.test_sanequeue -v` passes
- [ ] Python compile and JS syntax checks pass
- [ ] RBAC, queue scope and CSRF checked for control endpoints
- [ ] No secrets or private call data
- [ ] English/Persian UI and mobile/desktop states reviewed
- [ ] Documentation, CHANGELOG and VERSION updated when appropriate
- [ ] Regression, rollback, and upgrade impact documented

## Evidence

Test logs/screenshots without customer data. Link relevant issues.
