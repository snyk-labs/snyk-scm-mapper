# Snyk Sync Deployment Scenarios

Different companies have different ways they want Snyk to handle importing projects from repositories. Snyk Sync is meant to be flexible, allowing developers to manage the policies of where those repos go, but within guardrails established by the operators of Snyk Sync. This is not an exhaustive list but some examples of how the features can be combined.

## Scenario: Security Catch All, promote to responsible Devs (One Group)

This is the original use case of Snyk Sync and requires the least amount of configuration.

By default, all repositories from one or more Github Organizations are imported into a single Snyk Org inside a single Snyk Group.

### PreWork:

- Single group level Snyk access token
- Single GitHub Access token with read access to all orgs in question
- Running the autoconf command will handle the rest
- Developers that are ready to manage their own projects have already populated a `.snyk.d/import.yaml` file in their respective repositories, with minimum information pointing to an organization they are admins on:

```yaml
schema: 2
orgName: cse-ownership
```

### Workflow:

- Run snyk sync
- Output snyk sync targets
- Run snyk-api-import to import targets
- Run snyk sync to refresh with the updated target information
- Perform snyk sync tag updates to apply tags to any newly created projects

## Scenario: Security Catch All, promote to responsible Devs (Multi Group)

This is an expanded use case, instead of importing projects into different orgs with one group, this allows for teams (maybe all within a single business unit) to have a dedicated Snyk Group containg multiple orgs that they want their projects split up among.

For the endusers, there is no change to their `import.yaml` workflow, they specify the name of an Org from within their group, and Snyk Sync can figure out how to import said repo into that Org.

For Snyk Sync admins, the difference is now you need to provide each Snyk Group's ID, with a corresponding 'nice name' (unlike orgs, Snyk doesn't generate these for you, but lower-case-with-dashes is best), and the name of the ENVIRONMENT variable that group's access token is stored under. Once the groups are populated, the autoconf feature will be able to generate a snyk-orgs.yaml file.

```yaml
schema: 2
default:
  integrationName: github-enterprise
  orgName: ie-playground
github_orgs:
  - snyk-playground
snyk:
  groups:
    - name: cse-engineering
      id: 36863d40-ba29-491f-af63-7a1a7d79e411
      token_env_name: SNYK_SYNC_GROUP_CSE
    - name: angrydome
      id: dcf9cae3-2f54-4ad2-98af-e70b844657f3
      token_env_name: SNYK_SYNC_GROUP_ANGRYDOME
```

## Scenario: Security Monitors Release, Developers Monitor Main, one or more groups, one team running Sync

In this scenario, the security team wants to ensure that they have a specific branch of a repository monitored (and tagged) appropriately. While the developers want to be focused on the main branch they are developing too, ensuring that Security will alert them to any issues in a previous release.

This follows that one of the previous two scenarios has already been configured. The difference in this scenario is that developers / security coordinate on changes to the `.snyk.d/import.yaml` file. One could ensure Snyk is monitoring two branches just by adding the names of the branches to the repositories `import.yaml` file:

```yaml
schema: 2
orgName: cse-ownership
branches:
  - main
  - development
```

However in this example, projects from both `main` and `development` branches would be imported into the org `cse-ownership` which might not be the ideal case. Branch overrides work by declaring the branch name as a hash instead of a string, so the following `release` branch would create an additional import statement, but with customizations just for that branch, meaning that Snyk Sync would now import `main` and `development` branches into `cse-ownership` and a branch called :

```yaml
schema: 2
orgName: cse-ownership
branches:
  - main
  - development
  - release:
      orgName: security-team
      tags:
        - status: latest
```

If the development team also want to monitor the release branch in their cse-ownership org, they would need to add `release` as a string:

```yaml
branches:
  - main
  - development
  - release
  - release:
      orgName: security-team
      tags:
        - status: latest
```

## Scenario: Multiple teams running Snyk Sync, with repositories in overlapping github organizations

This is the most complicated scenario as it involves multiple configuration files / repositories. If none of the above scenarios fit the need of a single snyk sync handling all repos in this fashion, than this is the next step. This is not required if different instances of snyk-scm-mapper are being running across different corressponding github orgs. This is specifically for the scenario of multiple snyk-scm-mapper's looking at the same import.yaml file.

This feature is activated by using an additional key in the import.yaml: `instance` and by running a corresponding snyk-scm-mapper instance with a matching value.

With the following example, there are two instances of Snyk Sync evaluating the same import.yaml file:

```yaml
schema: 2
orgName: security-cse
tags:
  team: cse
branches:
  - release
instance:
  cse-ownership:
    branches:
      - development
      - main
      release:
        orgName: cse-release-watch
        tags:
          status: latest
    tags:
      application: example
      team: cse-ownership
```

The first instance, or default instance, is run by the security team. It is configured and run by the security team. Since the security doesn't use `--instance` the top level values are what are used, so all projects from the `release` branch will get the tag `team: cse` and be imported into an org named `security-cse`.

The CSE Team is also running their own instance of snyk-scm-mapper and they are running it with the `--instance cse-ownership` flag. That means the values under `instance -> cse-ownership` will override any top level values. So the `development` and `main` branches get imported into the default org for the instance (since no orgName is specified and security-cse is not an instance that they have access to so it isn't in their snyk-orgs.yaml file). The branch override is also evaluated, so additionally the release branch will be imported into the `cse-release-watch` org with a tag of `status: latest`.
