This is a work in progress; not ready for use yet. PRs welcome. (-:

# End-to-end testing for Zappa

This directory contains end-to-end tests. This tests *actual* deployments of Zappa, within a real AWS account. Running these tests costs money (in AWS usage fees).

They are separate from the main `tests/` because of this cost, and also because they are fundamentally different from the unit/integration tests in `tests/`.


## Requirements

These tests use [pytest](https://pytest.org/) (not nose) and have a different set of requirements.

- an active AWS account (*ideally*, you'll want to run these tests in an AWS account that doesn't do anything else, so all resources can be cleaned up manually if something goes wrong)
- a working set of credentials in the environment (variables `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, or an [otherwise-configured set of Boto3 credentials](https://boto3.readthedocs.io/en/latest/guide/configuration.html))
- a sacrificial API Gateway Custom Domain Name that can be attached to tests when needed (these take ~40 minutes to properly provision, so unless we're testing this actual integration, it's best to use a pre-provisioned custom domain name). The tests will look for this in the environment variable `ZAPPA_TEST_APIGW_CDN`. The end-to-end tests will skip tests that use this sacrificial CDN if it cannot be found.
- DNS configured (in Route53) to point to the above-mentioned custom domain name. The end-to-end tests will skip tests that use this sacrificial CDN if attached DNS cannot be found.
- TODO: provide a script to set these up


## Directory structure

- each subdirectory within `tests.end-to-end/app/` will contain a "full" Zappa app, and the end-to-end tests will test these actual apps
- each subdirectory should be named for the Zappa issue number this test is verifying. If no issue exists, use a simple but descriptive name such as `test-vpc`
- Each app should contain some or all of the following:
  - `zappa_settings.json.j2` a Jinja2 template that will be populated by the test suite (TODO: spec this out; TODO: spec stages if we implement multiple)
  - functioning app code
  - a `requirements.txt` for the app to test (TODO: spec this out a little better, such as "don't include the Zappa version")
  - *optionally*: a Cloudformation stack to invoke *before* tests on the zappa app, located in `zappa_cfn.json`, `zappa_cfn.yaml` or the standard output from `zappa_cfn.py` (as a [Troposphere](https://github.com/cloudtools/troposphere) based script). (TODO: not yet implemented)
  - *optionally*: its own `tests/` to run against the app once it's up and running. (TODO: not yet implemented)
