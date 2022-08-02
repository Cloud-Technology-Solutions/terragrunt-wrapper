import os
import terragrunt_wrapper


def test_input():
    assert os.environ["TF_INPUT"] == "false"


def test_single_env():
    terragrunt_wrapper.configure_env("testing")
    assert os.environ["TG_ENVIRONMENT"] == "testing"


def test_split_env():
    terragrunt_wrapper.configure_env("split/testing")
    assert os.environ["TG_ENVIRONMENT"] == "split"
