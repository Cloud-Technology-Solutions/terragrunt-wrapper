#!/usr/bin/env python3
"""
This script intercepts calls that the `kitchen-terraform` Test Kitchen driver
makes to the `terraform` executable and redirects them to Terragrunt.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import yaml

TK_HOME = os.environ.get("TK_HOME")
if not TK_HOME:
    try:
        workspace_dirs = os.listdir("/workspaces")
        if len(workspace_dirs) == 1:
            TK_HOME = f"/workspaces/{workspace_dirs[0]}"
        else:
            sys.exit("Too many workspaces found!")
    except FileNotFoundError as e:
        print(
            "Please set TK_HOME or run kitchen from a devcontainer",
        )
        sys.exit(e)
# export TERRAGRUNT_SOURCE_UPDATE=true to track a branch rather than a tag
os.environ["TF_INPUT"] = "false"

# `output` does not pass in the `env_name` variable; this needs to be
# persisted to disk across the various `terraform` runs
var_file = os.path.join(tempfile.gettempdir(), "env")


def configure_env(env_name):
    """
    Configure the TG_ENVIRONMENT environment variable for Terragrunt.
    """
    if "/" in env_name:
        os.environ["TG_ENVIRONMENT"] = env_name.split("/")[0]
    else:
        os.environ["TG_ENVIRONMENT"] = env_name


def get_output(command):
    """
    Run a subprocess directly and returns the output. Use when the output needs
    to be consumed directly rather than echoed.
    """
    try:
        result = subprocess.run(
            command, encoding="utf-8", capture_output=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        sys.exit(e.output)


def invoke_terragrunt(command):
    """
    Run a subprocess and stream the output to stdout. Use when the output needs
    to be echoed to the screen in real-time.
    """
    try:
        invoked_command = subprocess.Popen(
            command,
            encoding="utf-8",
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # Without the following, the output still gets excessively buffered
            universal_newlines=True,
            bufsize=1,
        )
        # poll() returns None until process finishes, then gives a return code
        while True:
            return_code = invoked_command.poll()
            if return_code is not None:
                break
            output = invoked_command.stdout.readline()
            if output:
                print(output.rstrip())
        if return_code != 0:
            sys.exit(invoked_command.stderr.read())
    except subprocess.CalledProcessError as e:
        sys.exit(e.output)


def tg_apply(args):
    # `env_name` is the only variable passed in by `kitchen-terraform`
    for arg in args:
        if arg.startswith("-var=env_name="):
            env_name = arg.split("-var=env_name=")[1]
    if not env_name:
        sys.exit("No env_name, aborting")
    with open(var_file, "w") as var_writer:
        var_writer.write(env_name)
    configure_env(env_name)
    invoke_terragrunt(
        [
            "terragrunt",
            "run-all",
            "apply",
            "--terragrunt-working-dir",
            os.path.join(TK_HOME, "terraform", env_name),
            "--terragrunt-include-external-dependencies",
        ]
    )


def tg_output():
    with open(var_file) as var_reader:
        env_name = var_reader.read()
        if not env_name:
            sys.exit("No env_name, aborting")
        configure_env(env_name)
        result = get_output(
            [
                "terragrunt",
                "run-all",
                "output",
                "-json",
                # terragrunt stupidly interleaves its output by default
                "--terragrunt-parallelism",
                "1",
                "--terragrunt-include-external-dependencies",
            ]
        )
        with open(
            os.path.join(tempfile.gettempdir(), "out.json"), "w"
        ) as output_json:
            output_json.write(result)
        # Massage this series of json objects into one dictionary
        merged_json = get_output(
            ["jq", "-rs", ".", os.path.join(tempfile.gettempdir(), "out.json")]
        )
        myobj = {}
        outputs_list = json.loads(merged_json)
        for output in outputs_list:
            myobj.update(output)
        print(json.dumps(myobj))


def tg_destroy(args):
    for arg in args:
        if arg.startswith("-var=env_name="):
            env_name = arg.split("-var=env_name=")[1]
    if not env_name:
        sys.exit("No env_name, aborting")
    configure_env(env_name)

    invoke_terragrunt(
        [
            "terragrunt",
            "run-all",
            "destroy",
            "--terragrunt-working-dir",
            os.path.join(TK_HOME, "terraform", env_name),
            "--terragrunt-include-external-dependencies",
        ]
    )


def tg_init():
    # options changed in tf15
    invoke_terragrunt(
        [
            "terraform",
            "init",
            "-input=false",
            "-upgrade",
            "-force-copy",
            "-backend=true",
            "-get=true",
        ]
    )


def tg_validate():
    # Terraform >= 0.15 errors if `-var` is passed to validate
    invoke_terragrunt(["terraform", "validate"])


def parse_input(stdin, tf_version):
    command = stdin[1]
    args = stdin[2:]
    if command == "version":
        # Just return the version string so that Terragrunt can validate it
        print(tf_version)
    elif command == "apply":
        tg_apply(args)
    elif command == "output":
        tg_output()
    elif command == "destroy":
        tg_destroy(args)
    elif command == "workspace":
        # no need for test kitchen to track workspaces
        sys.exit(0)
    elif command == "init":
        tg_init()
    elif command == "validate":
        tg_validate()
    else:
        # Catch-all passthrough of any other commands
        invoke_terragrunt(["terraform"] + [command] + args)


def main():
    try:
        # First sanity-check the config file
        with open(f"{TK_HOME}/test/integration/root.yaml") as f:
            assert yaml.safe_load(f)
        # Back it up and copy the test config across
        shutil.copy(
            f"{TK_HOME}/config/root.yaml", f"{TK_HOME}/config/root.yaml.bak"
        )
        shutil.copy(
            f"{TK_HOME}/test/integration/root.yaml",
            f"{TK_HOME}/config/root.yaml",
        )
        os.environ["GOOGLE_OAUTH_ACCESS_TOKEN"] = get_output(
            ["create-token", "-d", f"{TK_HOME}/config"]
        ).strip()
        parse_input(sys.argv, get_output(["terraform", "-v"]).split("\n")[0])
    except Exception as e:
        sys.exit(e)

    finally:
        # Always restore backed-up config when finished
        shutil.copy(
            f"{TK_HOME}/config/root.yaml.bak", f"{TK_HOME}/config/root.yaml"
        )
