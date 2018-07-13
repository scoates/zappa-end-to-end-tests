import pytest
import os
from distutils.dir_util import copy_tree
import logging
import sys
import socket
import hashlib
from jinja2 import Template
from zappa_e2e import (
    PreservableTemporaryDirectory,
    DeployedZappaApp,
    venv_cmd,
    chdir,
    ENV_CONFIG,
    python_executables,
)
import subprocess
import time


SLEEP_BETWEEN = 30
DIR = os.path.realpath(os.path.dirname(__file__))
APPS_PREFIX = os.path.join(DIR, "apps")
logger = logging.getLogger()

ZAPPA_S3_BUCKET = os.environ.get(
    "ZAPPA_S3_BUCKET",
    "zappa-e2e-" + str(hashlib.md5(socket.gethostname().encode()).hexdigest()),
)
logger.debug("Zappa E2E: using s3 bucket " + ZAPPA_S3_BUCKET)


def _path_to_app(path):
    str_path = str(path)
    if str_path.startswith(APPS_PREFIX):
        apps_path = str_path[len(APPS_PREFIX) + 1 :]
        return apps_path.split("/", 1)
    return None, None


def pytest_collect_file(parent, path):
    app_name, sub_path = _path_to_app(path)
    if sub_path == "zappa_settings.json.j2":
        return ZappaAppFile(path, parent)


class ZappaAppFile(pytest.File):
    def __init__(self, name, parent=None, config=None, session=None, nodeid=None):
        super(ZappaAppFile, self).__init__(name, parent, config, session, nodeid=nodeid)

        app_name, sub_path = _path_to_app(name)
        self.app_name = app_name
        self.app_path = os.path.join(APPS_PREFIX, app_name)

    def collect(self):
        yield ZappaAppTest(self.app_name, self)


class ZappaAppTest(pytest.Item):
    first_run = True

    def __init__(self, name, parent):
        super(ZappaAppTest, self).__init__(name, parent)
        self.app_name = parent.app_name
        self.app_path = parent.app_path

    def _venv_cmd(self, cmd, params=[], as_json=False, check=False, extra_env={}):
        return venv_cmd(self.venv_dir, cmd, params, as_json, check, extra_env)

    def runtest(self):

        for py_version, py_executable in python_executables().items():

            if self.__class__.first_run:
                self.__class__.first_run = False
            else:
                logger.info(
                    "Sleeping for {}s to help with the AWS rate limit.".format(
                        SLEEP_BETWEEN
                    )
                )
                time.sleep(SLEEP_BETWEEN)

            if py_executable is None:
                logger.warn("Could not find a python {} executable.".format(py_version))
                continue

            logger.info(
                "Entering app {} with Python {}".format(self.app_name, py_version)
            )
            with PreservableTemporaryDirectory(self.app_name, "py" + py_version) as (
                app_tmp_dir,
                ptd,
            ):
                self.app_test_dir = os.path.join(
                    app_tmp_dir, "{}-py{}".format(self.app_name, py_version)
                )
                copy_tree(self.app_path, self.app_test_dir)
                chdir(self.app_test_dir)

                self.venv_dir = os.path.join(app_tmp_dir, "venv")

                req_path = os.path.join(self.app_test_dir, "requirements.txt")
                if os.path.isfile(req_path):
                    requirements_txt_path = req_path

                alt_req_path = os.path.join(
                    self.app_test_dir,
                    "requirements-py{}.txt".format(py_version.replace(".", "")),
                )
                if os.path.isfile(alt_req_path):
                    # override:
                    requirements_txt_path = alt_req_path

                if not os.path.isdir(self.venv_dir):
                    cmd = subprocess.run(
                        ["virtualenv", "-p", py_executable, self.venv_dir],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    if cmd.returncode != 0:
                        print(cmd.returncode, cmd.stdout, cmd.stderr)
                        raise EnvironmentError(
                            "Could not create virtualenv for py {}".format(py_version)
                        )

                ret, _, _ = self._venv_cmd(
                    "pip", ["install", "-r", "requirements.txt"], check=True
                )

                template_file = os.path.join(
                    self.app_test_dir, "zappa_settings.json.j2"
                )
                with open(template_file) as f:
                    template_source = f.read()

                template = Template(template_source)
                rendered_template = template.render(
                    S3_BUCKET=ZAPPA_S3_BUCKET, E2E_VERSION=py_version
                )

                settings_file = os.path.join(self.app_test_dir, "zappa_settings.json")
                with open(settings_file, "w") as zsj:
                    zsj.write(rendered_template)
                    logger.debug(
                        "Zappa E2E: wrote settings file {} from template {}".format(
                            settings_file, template_file
                        )
                    )

                with DeployedZappaApp(
                    self.app_test_dir, self.venv_dir, ptd
                ) as zappa_app:

                    # undeployed handled in DeployedZappaApp
                    if not ENV_CONFIG["undeploy_only"]:

                        ret, status, _ = self._venv_cmd(
                            "zappa", ["status"], as_json=True
                        )
                        assert ret == 0, "Got Zappa app status"

                        env_status = {"PY_VERSION": py_version}
                        for k, v in status.items():
                            if type(v) == str:
                                env_status[k.upper().replace(" ", "_")] = v

                        run_tests = os.path.join(self.app_test_dir, "run_tests")
                        if os.path.isfile(run_tests):
                            ret, out, err = self._venv_cmd(
                                run_tests, extra_env=env_status
                            )
                            if ret != 0:
                                logger.info("stdout:")
                                logger.info(out)
                                logger.info("stderr:")
                                logger.info(err)
                            assert (
                                ret == 0 or ret == 5
                            ), "run_tests success (or no tests)"
