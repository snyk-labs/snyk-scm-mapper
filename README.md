![Snyk logo](https://snyk.io/style/asset/logo/snyk-print.svg)

![snyk-oss-category](https://github.com/snyk-labs/oss-images/blob/main/oss-community.jpg)

**This repository will be deprecated as of February 20, 2024.**

# Snyk Scm Mapper

A way to ensure your GitHub Repos containing projects that can be monitored by Snyk are infact monitored by Snyk.

## How does this work?

Snyk Scm Mapper connects to GitHub to retrieve a list of repositories from one or more GitHub organizations, cross references that list with the projects it can detect in a Snyk Group, and generates a list of Targets for [Snyk API Import](https://github.com/snyk-tech-services/snyk-api-import) to have Snyk attempt to monitor those unmonitored repositories.

Snyk Scm Mapper will check if a repository has a file [import.yaml](https://github.com/snyk-playground/org-project-import/blob/main/.snyk.d/import.yaml) in the root directory `.snyk.d/` this file specifies the Snyk Organization that any projects imported from the repository will be added to and any tags to ensure are added to those projects.

If there is no `import.yaml` file or the organization specified is not in the [snyk-orgs.yaml](conf/snyk-orgs.yaml) approved list the projects will go to the default organization as configured in the [snyk-sync.yaml](conf/snyk-sync.yaml) file.

Snyk Scm Mapper can be run by hand, by a scheduler, or in a github workflow (see: [config-repo](https://github.com/snyk-playground/config-repo) for a github workflow implementation)

Assumptions:

- A repository is considered monitored if it already has a single project (there are tools such as [scm-refresh](https://github.com/snyk-tech-services/snyk-scm-refresh) that will allow one to reprocess existing repositories and it is on the Snyk roadmap to reprocess them natively)
- Tags are additive: Any tags specified in the `import.yaml` will be added to all projects from the same repository. If the tag already exists as an exact match, it will not be added, and existing tags not declared in `import.yaml` will not be removed. Snyk allows for duplicate Key names, so "application:database" and "application:frontend" are both valid K:V tags that could be on the same project. This is not a suggestion to do this, but pointing out it is possible.
- Forks: Because of how GitHub's indexing works, it will not search forks. Snyk Scm Mapper uses GitHub's search functionality to detect `import.yaml` files (to keep API calls to a minimum). In order to add forks, use the `--forks` flag to have Snyk Scm Mapper search each fork individually for the `import.yaml` file. **CAUTION:** This will incur an API cost of atleast one request per fork and two if the fork contains an `import.yaml` 

## Topics

If an Org in the snyk-orgs.yaml file includes a list of topics, any repo that has matching topics will be assigned that org instead of default. This happens before import.yaml evaluation. The orgs with the highest number of matching topics is assigned in the case of multiple orgs matching for a single repo. If there is a tie in matches, the first by alphabetical order of org name is selected.

### Order of Precedence (most specific wins)

If a repo has a topic matching an org's topics list, and an import.yaml listing an org, who wins? The import.yaml does.

In the import.yaml, a top level org definition applies to all repos, unless a branch has an org listed.

An `instance` can be considered a prefilter to the import.yaml, because it is applied to the import.yaml first, then the branch overrides are evaluated.

```
A Repo is found -> Does an org match the topics? Yes -> Change org ->
  Does an import.yaml exist? Yes -> Evaluate for Instance ->
  Is an Org declared? -> Change org for all listed branches ->
  Does a branch have an org? -> Change org for specific branch
```

## Caching

If one has a large organization with many hundreds or thousands of repositories, the process of discovering all of them can be timeconsuming. In order to speed up this process, Snyk Scm Mapper builds a 'watchlist' in a cache directory (by default `cache`). It will only perform a sync (querying both GitHub and Snyk APIs) if the data is more than 60 minutes old (change with: --cache-timeout) or a sync is forced (`--sync`). This allows for the `targets` and `tags` subcommands to operate much more quickly. Depending on the size of the targets list given to snyk-api-import, it may take a long time for the project imports to complete, after which another sync should be performed and the `tags` command run to ensure any new projects that didn't exist before are now updated with their associated tags.

## Setup

See [scenarios](SCENARIOS.md)

Snyk Scm Mapper expects a `GITHUB_TOKEN` and `SNYK_TOKEN` environment variables to be present, along with a snyk-sync.yaml file, snyk-orgs.yaml file, and a folder to store the cache in (it will not create this folder). See the [example](/example) directory for a starting point.

```
example
├── cache
├── snyk-orgs.yaml
└── snyk-sync.yaml
```

- GITHUB_TOKEN: this access token must have read access to all repositories in all GitHub organizations one wishes to import
- SNYK_TOKEN: this should be a group level service account that has admin access to create new projects and tag them

Minimum snyk-sync.yaml contents:

```
---
schema: 1
github_orgs:
  - <<Name of GitHub Org>>
snyk:
  group: <<Group ID from Snyk>>
default:
  orgName: ie-playground
  integrationName: github-enterprise
```

Example minimum snyk-orgs.yaml:

```
---
ie-playground:
  orgId: 39ddc762-b1b9-41ce-ab42-defbe4575bd6
  integrations:
    github-enterprise: b87e1473-37ab-4f09-a4e3-a0139a50e81e
```

To get the Organization ID, navigate to the settings page of the organization in question
`https://app.snyk.io/org/<org-name>/manage/settings`

To get the GitHub Enterprise integration ID (currently the GitHub Enterprise integration is the only supported integration for snyk scm mapper, but it can be used with a GitHub.com Org as well) navigate to:
`https://app.snyk.io/org/<org-name>/manage/integrations/github-enterprise`

### Help

Base snyk-sync flags/environment variables

```
Usage: cli.py [OPTIONS] COMMAND [ARGS]...

Options:
  --cache-dir DIRECTORY    Cache location  [env var: SNYK_MAPPER_CACHE_DIR;
                           default: cache]
  --cache-timeout INTEGER  Maximum cache age, in minutes  [env var:
                           SNYK_MAPPER_CACHE_TIMEOUT; default: 60]
  --forks / --no-forks     Check forks for import.yaml files  [env var:
                           SNYK_MAPPER_FORKS; default: no-forks]
  --conf FILE              [env var: SNYK_MAPPER_CONFIG; default: snyk-
                           sync.yaml]
  --targets-file FILE      [env var: SNYK_MAPPER_TARGETS_FILE]
  --snyk-orgs-file FILE    Snyk orgs to watch  [env var: SNYK_MAPPER_ORGS]
  --default-org TEXT       Default Snyk Org to use from Orgs file.  [env var:
                           SNYK_MAPPER_DEFAULT_ORG]
  --default-int TEXT       Default Snyk Integration to use with Default Org.
                           [env var: SNYK_MAPPER_DEFAULT_INT]
  --snyk-group UUID        Group ID, required but will scrape from ENV  [env
                           var: SNYK_MAPPER_GROUP; required]
  --snyk-token UUID        Snyk access token  [env var: SNYK_TOKEN; required]
  --sync                   Forces a sync regardless of cache status
  --github-token TEXT      GitHub access token  [env var: GITHUB_TOKEN;
                           required]
  --log-level TEXT         The log-level which Scm Mapper will use (defaults)
                           to ERROR. Log levels corrospond to Python log levels,
                           see here: https://sematext.com/blog/logging-levels/
  --set-root-log-level     Sets the log level for all modules, not just Scm Mapper
                                              
  --help                   Show this message and exit.

Commands:
  status   Return if the cache is out of date
  sync     Force a sync of the local cache of the GitHub / Snyk data.
  tags     Returns list of project id's and the tags said projects are...
  targets  Returns valid input for api-import to consume
```

targets command:
Outputs the list of targets to stdout or saves them to a file. The output is formated json that [snyk-api-import](https://github.com/snyk-tech-services/snyk-api-import) accepts.

```
Usage: cli.py targets [OPTIONS]

  Returns valid input for api-import to consume

Options:
  --save  Write targets to disk, otherwise print to stdout
  --help  Show this message and exit.
```

```
Usage: cli.py tags [OPTIONS]

  Returns list of project id's and the tags said projects are missing

Options:
  --update  Updates tags on projects instead of outputting them
  --save    Write tags to disk, otherwise print to stdout
  --help    Show this message and exit.
```

### Container Build Steps

This pushes to GitHub's [container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

```
docker build --force-rm -f Dockerfile -t snyk-scm-mapper:latest .
docker tag snyk-scm-mapper:latest snyklabs/snyk-scm-mapper:latest
docker push snyklabs/snyk-scm-mapper:latest
```

### Container Run Steps

```
docker pull snyklabs/snyk-scm-mapper:latest
docker tag snyklabs/snyk-scm-mapper:latest snyk-scm-mapper:latest
docker run --rm -it -e GITHUB_TOKEN -e SNYK_TOKEN -v "${PWD}":/runtime snyk-scm-mapper:latest --sync target
```

### Using a custom CA Root Certificate / proxies

If using a proxy, ensure that you are passing HTTP_PROXY and HTTPS_PROXY environment variables to the container runtimes.

`-e HTTP_PROXY -e HTTPS_PROXY` will create env variables with the same values as the machine that ran the docker command.

**Custom Certificates**

Naming the custom certificate bundle `custom-ca.crt` and placing it in base directory you are mounting as runtime, both the snyk-sycn and api-import entrypoints will detect and set appropriate environment variables for Python and Node respectively. In most cases this is the same as the config-repo itself, and would be mounted to /runtime, which is the containers workdir.

So in most cases:

- Rename your custom certificate bundle as `custom-ca.crt`
- Ensure `custom-ca.crt` is in the root of your config-repo

If you want to specify your own path to the certificate bundle, ensure that file is present before the entrypoints run, and set the following environment flags:

```
REQUESTS_CA_BUNDLE="/custom/path/to/ca-bundle.crt"
NODE_EXTRA_CA_CERTS="/custom/path/to/ca-bundle.crt"
```
