import subprocess
import tempfile
import logging
import os
import json
import sys
import weakref
from distutils.spawn import find_executable
from distutils.errors import DistutilsExecError
from copy import copy


logger = logging.getLogger()


def env_bool(var):
    return os.environ.get("ZAPPA_E2E_" + var, False) in [
        1,
        "1",
        "True",
        "true",
        "TRUE",
        True,
    ]


ENV_CONFIG = {
    # harnesses the test suite to only undeploy apps, if possible. Does not test. Main use here is to clean up after a catastrophic mess, if even possible.
    "undeploy_only": env_bool("UNDEPLOY_ONLY"),
    # if an app is deployed, update instead of deploy
    "update_over_deploy": env_bool("UPDATE_OVER_DEPLOY"),
    # do not undeploy apps
    "no_undeploy": env_bool("NO_UNDEPLOY"),
    # preserve temporary app dirs
    "preserve_temp": env_bool("PRESERVE_TEMP"),
    # python versions
    "skip_python_27": env_bool("SKIP_PYTHON_27"),
    "skip_python_36": env_bool("SKIP_PYTHON_36"),
    "python_27_path": env_bool("PYTHON_27_PATH"),
    "python_36_path": env_bool("PYTHON_36_PATH"),

    # override Zappa?
    "zappa_override": os.environ.get("ZAPPA_E2E_ZAPPA_OVERRIDE"),

    # sleep between deployments (helps with AWS API limits; might not be necessary since they raised these)
    "sleep_between": os.environ.get("ZAPPA_E2E_SLEEP_BETWEEN"),
}


class PreservableTemporaryDirectory(tempfile.TemporaryDirectory):
    def __init__(self, app_name, version):
        """Preservable Temporary Directory

        uses the system temp directory path plus a declarative subpath so we can do things like keep apps always in the same place"""
        # borrowed most of this from https://github.com/python/cpython/blob/master/Lib/tempfile.py

        main_tmp_dir = os.path.join(tempfile.gettempdir(), "zappa-e2e")
        version_dir = os.path.join(main_tmp_dir, version)
        dir = os.path.join(version_dir, app_name)

        try:
            os.mkdir(main_tmp_dir)
        except FileExistsError:
            pass

        try:
            os.mkdir(version_dir)
        except FileExistsError:
            pass

        try:
            os.mkdir(dir)
        except FileExistsError:
            pass

        self.name = dir
        self._finalizer = weakref.finalize(
            self,
            self._cleanup,
            self.name,
            warn_message="Implicitly cleaning up {!r}".format(self),
        )

        self._preserve = True

        if ENV_CONFIG["preserve_temp"]:
            logger.info("Automatically preserving temp dir due to environment config")
            self.preserve()

    def preserve(self):
        self._finalizer.detach()

    @property
    def preserved(self):
        return self._preserve

    def __enter__(self):
        return self.name, self

    def __exit__(self, exc, value, tb):
        logger.debug(
            "Exiting PreservableTemporaryDirectory {} with preserve={}".format(
                self.name, "True" if self._preserve else "False"
            )
        )
        if not self._preserve:
            self.cleanup()


class DeployedZappaApp:
    def __init__(self, app_dir, venv_dir, ptd, stage="test"):
        self.skip_cleanup = False
        self.app_dir = app_dir
        self.venv_dir = venv_dir
        self.ptd = ptd
        self.failed = False
        self.stage = stage
        self.post_deploy_status = {}

    @property
    def status(self):
        """ example:
{
    "Lambda Versions": 2,
    "Lambda Name": "hello-world-test",
    "Lambda ARN": "arn:aws:lambda:us-east-1:REDACTED:function:hello-world-test",
    "Lambda Role ARN": "arn:aws:iam::REDACTED:role/hello-world-test-ZappaLambdaExecutionRole",
    "Lambda Handler": "handler.lambda_handler",
    "Lambda Code Size": 19346351,
    "Lambda Version": "$LATEST",
    "Lambda Last Modified": "2018-07-05T00:26:52.796+0000",
    "Lambda Memory Size": 512,
    "Lambda Timeout": 30,
    "Lambda Runtime": "python3.6",
    "Lambda VPC ID": null,
    "Invocations (24h)": 7,
    "Errors (24h)": 0,
    "Error Rate (24h)": "0.00%",
    "API Gateway URL": "https://REDACTED.execute-api.us-east-1.amazonaws.com/test",
    "Domain URL": "None Supplied",
    "Num. Event Rules": 1,
    "Events": [
        {
            "Event Rule Name": "hello-world-test-zappa-keep-warm-handler.keep_warm_callback",
            "Event Rule Schedule": "rate(4 minutes)",
            "Event Rule State": "Enabled",
            "Event Rule ARN": "arn:aws:events:us-east-1:REDACTED:rule/hello-world-test-zappa-keep-warm-handler.keep_warm_callback"
        }
    ]
}
        """
        return self.post_deploy_status

    @property
    def name(self):
        return self.post_deploy_status.get("Lambda Name", "(no name)")

    def __repr__(self):
        return "<{} {!r}>".format(self.__class__.__name__, self.name)

    def __enter__(self):
        chdir(self.app_dir)
        ret, out, _ = venv_cmd(
            self.venv_dir, "zappa", ["status", "--json"]
        )  # not using as_json because zappa status doesn't return json when it fails
        pre_deploy_status_exists = ret == 1

        if not pre_deploy_status_exists and not (
            ENV_CONFIG["update_over_deploy"] or ENV_CONFIG["undeploy_only"]
        ):
            logger.error(
                "{}: Status succeeded before deploy. This probably means that the app is already deployed. Bailing.".format(
                    self.__class__.__name__
                )
            )
            self.skip_cleanup = True
            sys.exit(1)

        elif not pre_deploy_status_exists:
            try:
                self.post_deploy_status = json.loads(out)
            except json.decoder.JSONDecodeError:
                pass

        if ENV_CONFIG["undeploy_only"]:
            # exit early
            logger.info("{}: doing undeploy only".format(self.__class__.__name__))
            return self.name

        if not pre_deploy_status_exists and ENV_CONFIG["update_over_deploy"]:
            logger.info(
                "{}: updating instead of deploying for {}".format(
                    self.__class__.__name__, self.name
                )
            )
            ret, out, err = venv_cmd(self.venv_dir, "zappa", ["update", self.stage])
            if ret != 0:
                logger.error(
                    "{}: failed to update. Bailing.".format(
                        self.__class__.__name__
                    )
                )
                logger.info("stdout=")
                [logger.info(l) for l in out.decode().split("\n") if l != ""]
                logger.info("stderr=")
                [logger.info(l) for l in err.decode().split("\n") if l != ""]
                return None

        else:
            ret, out, err = venv_cmd(self.venv_dir, "zappa", ["deploy", self.stage])
            if ret != 0:
                logger.error(
                    "{}: failed to deploy. Bailing.".format(
                        self.__class__.__name__
                    )
                )
                logger.info("stdout=")
                [logger.info(l) for l in out.decode().split("\n") if l != ""]
                logger.info("stderr=")
                [logger.info(l) for l in err.decode().split("\n") if l != ""]
                self.skip_cleanup = True
                return None

        ret, out, _ = venv_cmd(
            self.venv_dir, "zappa", ["status", self.stage], as_json=True
        )
        if ret != 0:
            logger.error(
                "{}: something went wrong with the post-deploy status check.".format(
                    self.__class__.__name__
                )
            )
            self.failed = True
            return None

        self.post_deploy_status = out
        logger.info(
            "{}: zappa app {} published.".format(self.__class__.__name__, self.name)
        )

        return self.post_deploy_status

    def __exit__(self, exc, value, tb):
        self.cleanup()

    def _preserve_and_fail(self, msg):
        self.failed = True
        self.ptd.preserve()
        logger.error(
            "{}: failing with message '{}'. App directory preserved at: {}".format(
                self.__class__.__name__, msg, self.ptd.name
            )
        )

    def cleanup(self):
        if self.skip_cleanup:
            logger.warn(
                "{}: Skipping cleanup for {} in {}".format(
                    self.__class__.__name__, self.name, self.app_dir
                )
            )
            if self.failed:
                self._preserve_and_fail("Failed before cleanup.")
        else:
            logger.debug(
                "{}: Cleaning up for {} in {}".format(
                    self.__class__.__name__, self.name, self.app_dir
                )
            )
            if self.failed:
                self._preserve_and_fail("Failed before cleanup.")
            else:
                if ENV_CONFIG["no_undeploy"]:
                    logger.info(
                        "Not undeploying {} due to environment config".format(self.name)
                    )
                else:
                    os.chdir(self.app_dir)
                    ret, out, err = venv_cmd(
                        self.venv_dir, "zappa", ["undeploy", "-y", self.stage]
                    )
                    if ret == 0 or ENV_CONFIG["undeploy_only"]:
                        ret, out, _ = venv_cmd(self.venv_dir, "zappa", ["status"])
                        if ret != 1:
                            self._preserve_and_fail(
                                "Zappa status should have returned 1. Returned {}. With output: {}".format(
                                    ret, out
                                )
                            )

                    else:
                        self._preserve_and_fail("Could not undeploy")
                        logger.error(
                            "{}: Zappa failed to undeploy.\nstderr={}\nstdout={}".format(
                                self.__class__.__name__, err, out
                            )
                        )

            if self.failed:
                sys.exit(1)


def venv_cmd(venv_dir, cmd, params=[], as_json=False, check=False, extra_env={}):
    args = [os.path.join(venv_dir, "bin", cmd)]
    args.extend(params)
    if as_json:
        args.append("--json")
    logger.debug("Calling '{}'".format(" ".join(args)))

    env = copy(os.environ)
    env.update(extra_env)

    prefix = 'VIRTUAL_ENV="'
    with open(os.path.join(venv_dir, "bin", "activate")) as f:
        l = f.readline()
        while l:
            if l.startswith(prefix):
                env["VIRTUAL_ENV"] = l[len(prefix) : -2]
                break
            l = f.readline()

    # logger.debug("venv_cmd: calling {} with env {}".format(args, env))
    cmd = subprocess.run(
        args, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
    )
    if as_json:
        try:
            return cmd.returncode, json.loads(cmd.stdout), cmd.stderr
        except json.decoder.JSONDecodeError:
            pass  # returns below

    return cmd.returncode, cmd.stdout, cmd.stderr


def chdir(wd):
    logger.debug("Changing os directory to {}".format(wd))
    os.chdir(wd)


def _try_run_python(name):
    out = ""
    cmd = find_executable(name)
    if cmd:
        try:
            run = subprocess.run(
                [cmd, "-V"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
            if run:
                out = run.stdout.decode()
        except DistutilsExecError:
            pass
    return out, cmd


def python_executables():

    found = {"2.7": None, "3.6": None}

    if ENV_CONFIG["python_27_path"]:
        out, cmd = _try_run_python(ENV_CONFIG["python_27_path"])
        if out.startswith("Python 2.7"):
            found["2.7"] = ENV_CONFIG["python_27_path"]
        else:
            raise EnvironmentError(
                "Python 2.7 path specified, but is not actually a Python 2.7 executable."
            )

    if ENV_CONFIG["python_36_path"]:
        out, cmd = _try_run_python(ENV_CONFIG["python_36_path"])
        if out.startswith("Python 3.6"):
            found["3.6"] = ENV_CONFIG["python_36_path"]
        else:
            raise EnvironmentError(
                "Python 3.6 path specified, but is not actually a Python 3.6 executable."
            )

    if not found["2.7"] or not found["3.6"]:
        # try plain `python` first
        out, cmd = _try_run_python("python")
        if not found["2.7"] and out and out.startswith("Python 2.7"):
            found["2.7"] = cmd
        elif not found["3.6"] and out and out.startswith("Python 3.6"):
            found["3.6"] = cmd

    if not found["2.7"] and out and (found["2.7"] is None):
        out, cmd = _try_run_python("python2")
        if out.startswith("Python 2.7"):
            found["2.7"] = cmd

    if not found["3.6"] and out and found["3.6"] is None:
        out, cmd = _try_run_python("python3")
        if out.startswith("Python 3.6"):
            found["3.6"] = cmd

    if ENV_CONFIG['skip_python_27']:
        del found["2.7"]
    if ENV_CONFIG['skip_python_36']:
        del found["3.6"]

    return found
