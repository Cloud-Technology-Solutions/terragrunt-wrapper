# `terragrunt-wrapper` README

This repo contains a shell script which makes it possible to used Terragrunt
with the [Test Kitchen](kitchen.chef.io) framework more natural. It intercepts
the calls that the `kitchen-terraform` driver makes to the `terraform` binary
and instead directs them to `terragrunt` while ensuring that the differences
between how the two commands are invoked are accounted for.

Inspec testing is fully supported and outputs from Terraform modules are
serialised in a manner that permits them to be loaded as inputs to Inspec.

## Usage

Ensure that the `TK_HOME` environment variable is set to the directory that
contains the Test Kitchen config.

## Configuration

The tool expects the following directory structure:

```none
/
  .kitchen.yml
  environments/
    root.yaml
    empty.yaml
    terragrunt.hcl
    provider.tf
    [env]/
      env.yaml
      [resource]/
        terragrunt.hcl
  test/
    root.yaml
    integration/
      [env]/
        controls/
          default.rb
        inspec.yml
```

The `.kitchen.yml` file should have the following format:

```yaml
---
driver:
  name: terraform
  verify_version: false
  client: /path/to/tg-wrapper
  command_timeout: 1800

provisioner:
  name: terraform

verifier:
  name: terraform
  systems:
    - name: gcp
      backend: gcp
      controls:
        - gcp
    - name: local
      backend: local
      controls:
        - local

platforms:
  - name: default

suites:
  - name: dev
    driver:
      variables:
        env_name: dev
      root_module_directory: environments/dev
```

## Testing

Inspec with the `inspec-gcp` profile is used for testing.

Outputs from Terraform are saved in the Test Kitchen runtime directory and are
automatically made available to Inspec as `input`s (prefixed with `output_`).

To get access to the root config used when building stacks, the following Ruby
can be added to the controls file:

```ruby
require 'yaml'
vars = YAML.load(File.read('environments/root.yaml'))
.merge(YAML.load(File.read("environments/#{input('input_env_name')}/env.yaml")))
```

This permits values to be looked up as e.g. `vars['env_name']`.

## Workflow

todo

Export `TERRAGRUNT_SOURCE_UPDATE=true` to track a branch rather than a tag.

## Notes

-   Inter-environment dependencies will be processed as normal: this means that
    you can test a parent environment before its children and they will be able
    to locate the existing resources through the Terraform state. Note however
    that the if two suites have the same dependencies, then deleting one suite
    will break the other, as it will remove the parent resources. This will
    require either that the dependencies be reinstated (e.g. by re-converging
    a separate suite containing them) or manually cleaning up environments with
    broken dependencies. This is not fixable as Test Kitchen does not consider
    the possibility of inter-suite dependencies. It is recommended therefore
    not to converge stacks with overlapping dependencies at the same time.
-   Terragrunt's `output-all` command is incredibly basic and expects to be
    able to just run `terraform output` on all of its modules with the same
    level of parallelism as other Terraform commands. This obviously does not
    work correctly with structured output. While this is handled by forcing
    outputs to be run without parallelism, the problem remains that Terraform
    expects the names of its outputs to be unique (and provides no facility for
    customising their names due to the limitations of HCL's identifiers) and so
    if Terragrunt runs the same module more than once when building out an
    environment then the resultant output will be invalid YAML. The correct fix
    here would be for Terragrunt to rename outputs according to the environment
    in some manner itself. For now an imperfect solution of inline Python is
    used to manually modify `project` resource outputs only. There is no reason
    that this could not be improved to handle all output objects.
-   The `inspec-gcp` profile is a very thin wrapper around the underlying API
    calls and is missing a lot of possible introspection. For resource types
    that it does not cover or does not expose sufficient attributes for, it is
    recommended to use the `local` profile and just run `gcloud` commands
    directly.
