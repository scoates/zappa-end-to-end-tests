# End-to-end testing for Zappa

This repository contains end-to-end tests. This tests *actual* deployments of Zappa, within a real AWS account. Running these tests costs money (in AWS usage fees).

They are separate from the main Zappa repository `tests/` because of this cost, and also because they are fundamentally different from the unit/integration tests in `tests/`.


## Requirements

These tests use [pytest](https://pytest.org/) (not nose like Zappa) and have a different set of requirements.

- an active AWS account (*ideally*, you'll want to run these tests in an AWS account that doesn't do anything else, so all resources can be cleaned up manually if something goes wrong)
- a working set of credentials in the environment (variables `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, or an [otherwise-configured set of Boto3 credentials](https://boto3.readthedocs.io/en/latest/guide/configuration.html))
- TODO: a sacrificial API Gateway Custom Domain Name that can be attached to tests when needed (these take ~40 minutes to properly provision, so unless we're testing this actual integration, it's best to use a pre-provisioned custom domain name). The tests will look for this in the environment variable `ZAPPA_TEST_APIGW_CDN`. The end-to-end tests will skip tests that use this sacrificial CDN if it cannot be found.
- TODO: DNS configured (in Route53) to point to the above-mentioned custom domain name. The end-to-end tests will skip tests that use this sacrificial CDN if attached DNS cannot be found.
- TODO: provide a script to set these up


## Directory structure

- each subdirectory within `apps/` will contain a "full" Zappa app, and the end-to-end tests will test these actual apps
- each subdirectory should be named for the Zappa issue number this test is verifying. If no issue exists, use a simple but descriptive name such as `vpc`
- whenever possible, reuse une of the generic test apps instead of adding a new app. New app creation is slow. For example: if you want to test an input string, but not a different Zappa configuration, maybe the `hello-world` app could do what you want.
- Each app should contain some or all of the following:
  - `zappa_settings.json.j2` a Jinja2 template that will be populated by the test suite (TODO: spec this out; TODO: spec stages if we implement multiple; TODO: actually do jinja)
  - functioning app code
  - a `run_tests` script that will run the tests. It receives the `$PY_VERSION` (either `27` or `36` for `2.7` and `3.6` respectively) in the environment.
    - the `run_tests` script is responsible for dependencies. It usually needs  a `requirements.txt` for the app to test, or better: a `requirements-py27.txt' and `requirements-py36.txt' for Python 2.7 and 3.6, respectively. Add `zappa` to the `requirements.txt` but don't specify a version
    - the `run_tests` script also calls tests. Usually in `tests_27/` (or `tests_36/`) and `tests/` for version-independent tests
  - TODO: *optionally*: a Cloudformation stack to invoke *before* tests on the zappa app, located in `zappa_cfn.json`, `zappa_cfn.yaml` or the standard output from `zappa_cfn.py` (as a [Troposphere](https://github.com/cloudtools/troposphere) based script). (TODO: not yet implemented)


## Running the tests:

  - run `py.test`
  - to get realtime output: `py.test --log-cli-level=debug`


### Environment Variables

Setting certain environment variables will affect how tests run. For the values marked "bool", set to `1` to enable:

- `ZAPPA_E2E_UNDEPLOY_ONLY` (bool) harnesses the test suite to only undeploy apps, if possible. Does not test. Main use here is to clean up after a catastrophic mess, if even possible, but also to undeploy after running `NO_UNDEPLOY` (below)
- `ZAPPA_E2E_NO_UNDEPLOY` (bool) do not undeploy apps
- `ZAPPA_E2E_UPDATE_OVER_DEPLOY` (bool) if an app is deployed, update instead of deploy
- `ZAPPA_E2E_PRESERVE_TEMP` (bool) preserve temporary app dirs
- `ZAPPA_E2E_SKIP_PYTHON_27` (bool) skip Python 2.7 app + tests
- `ZAPPA_E2E_SKIP_PYTHON_36` (bool) skip Python 3.6 app + tests
- `ZAPPA_E2E_PYTHON_27_PATH` path to the Python 2.7 executable
- `ZAPPA_E2E_PYTHON_36_PATH` path to the Python 3.6 executable
- `ZAPPA_E2E_ZAPPA_OVERRIDE` use this string to install Zappa. Can be something like `Zappa==0.44.1` or a local path e.g. `/path/to/src/Zappa`
- `ZAPPA_E2D_SLEEP_BETWEEN` sleep for this many seconds between tests; helps with the AWS API rate limit, but this was changed in mid-2018 so it might no longer be necessary

### Examples

- `py.test --log-cli-level=info` runs the tests, shows `INFO` class logs
- `ZAPPA_E2E_UNDEPLOY_ONLY=1 py.test` undeploys currently-deployed apps if applicable
- `py.test apps/hello-world/zappa_settings.json.j2` runs only the `hello-world` app + tests
- `ZAPPA_E2E_SKIP_PYTHON_27=1 py.test apps/hello-world/zappa_settings.json.j2` runs only the `hello-world` app + tests, only on Python 3.6
- `ZAPPA_E2E_ZAPPA_OVERRIDE=~/src/Zappa py.test` run the suite with the locally-checked out Zappa in `~/src/Zappa` (use this for testing unreleased versions of Zappa, local changes, etc.)
- `ZAPPA_E2E_UPDATE_OVER_DEPLOY=1 ZAPPA_E2E_PRESERVE_TEMP=1 ZAPPA_E2E_NO_UNDEPLOY=1 py.test` Keep deployed Zappa apps and update on the next run. This is useful for running the tests sequentially.
