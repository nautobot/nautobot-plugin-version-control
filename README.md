# Nautobot Version Control

The Nautobot Version Control app brings version control to the [Nautobot](https://github.com/nautobot/nautobot) open source Network Source of Truth and Network Automation Platform. 

Nautobot provides a number of features to validate its data model and safeguard network configuration from errors. Adding database versioning provides another layer of assurance by enabling human review of proposed changes to production data, use of automated testing pipelines, and database rollback in the case of errors. 

The database versioning is made possible by the use of a [Dolt](https://github.com/dolthub/dolt) database. Dolt is a MySQL-compatible SQL database that you can fork, clone, branch, merge, push and pull just like a Git repository.

Dolt’s *branch* and *merge* versioning model allows operators to safely modify the data model on feature branches, merging to production only after validation is complete.

## Documentation

In addition to this `README` file, there are docs covering the following topics:

* [Version control operations](docs/version-control-operations.md)
  * Covers common version control operations in the Version Control app
* [Common workflows](docs/workflows/common_workflows.md)
  * Covers common workflows enabled by the Version Control app
* [Design](docs/design.md)
  * Describes the technical design and implementation details of the Version Control app

## Installation

### Installation Considerations

There are some special considerations for running the Version Control app:

* Nautobot 1.2.0 or later is required
* The Nautobot installation **must** be running a Dolt database
* There are some [additional configurations](#configuring-nautobot-to-use-version-control) required in `nautobot_config.py`

The version control app can be installed with pip3:

```no-highlight
pip3 install nautobot-version-control
```

To ensure the version control app is automatically reinstalled during future upgrades, create a new file named `local_requirements.txt` (if not already existing) in the Nautobot root directory (e.g. `/opt/nautobot`) to include the `nautobot-version-control` package:

```no-highlight
echo nautobot-version-control >> local_requirements.txt
```

### Configuring Nautobot to use Version Control

Add this to your `nautobot_config.py` to prepare your Nautobot settings for Dolt:

```python
# Dolt requires a second database using the same credentials as the default database so that it may 
# generate diffs.
DATABASES["global"] = DATABASES["default"]

# Dolt requires a custom database router to generate the before & after queries for generating diffs.
DATABASE_ROUTERS = ["nautobot_version_control.routers.GlobalStateRouter"]

# Because Dolt creates branches of the database, the default database sessions cannot be used. We 
# must tell Nautobot to use Redis for sessions instead. This adds a distinct cache configuration for
# using Redis cache for sessions.
# See: https://github.com/jazzband/django-redis#configure-as-session-backend
CACHES["sessions"] = {
    "BACKEND": "django_redis.cache.RedisCache",
    "LOCATION": parse_redis_connection(redis_database=2),
    "TIMEOUT": 300,
    "OPTIONS": {
        "CLIENT_CLASS": "django_redis.client.DefaultClient",
    },
}

# Use the sessions alias defined in CACHES for sessions caching
SESSION_CACHE_ALIAS = "sessions"

# Use the Redis cache as the session engine
SESSION_ENGINE = "django.contrib.sessions.backends.cache"

# Enable the Version Control app
PLUGINS = [ "nautobot_version_control" ]
```

Then run database migrations:

```no-highlight
$ nautobot-server migrate
```

### Production Deployment

TBD as we progress towards stable release.

## Development Environment

In addition to the instructions below, we also have a [demonstration video](https://youtu.be/XHrTHwhbZLc) that walks the user through the dev and test setup process described below. 

### Getting Started

Getting started with development for the Version Control plugin is straightforward. It is modeled directly after the development environment of Nautobot itself, and should feel very familiar to anyone with Django development experience.

The Version Control app uses a Docker Compose environment to make it simple to manage dependencies like Dolt and Redis.

### Install Invoke

Because it is used to execute all common Docker workflow tasks, Invoke must be installed for your user environment. 
On most systems, if you're installing without root/superuser permissions, the default will install into your local user environment.

```no-highlight
$ pip3 install invoke
```

If you run into issues, you may also deliberately tell pip3 to install into your user environment by adding the --user flag:

```no-highlight
$ pip3 install --user invoke
```

### List Invoke Tasks

Now that you have an invoke command, list the tasks defined in tasks.py with `invoke --list`:

```no-highlight
$ invoke --list
Available tasks:

  bandit              Run bandit to validate basic static code security analysis.
  black               Check Python code style with Black.
  build               Build Nautobot docker image.
  check-migrations    Check for missing migrations.
  cli                 Launch a bash shell inside the running Nautobot container.
  createsuperuser     Create a new Nautobot superuser account (default: "admin"), will prompt for password.
  debug               Start Nautobot and its dependencies in debug mode.
  destroy             Destroy all containers and volumes.
  flake8              Check for PEP8 compliance and other style issues.
  generate-packages   Generate all Python packages inside docker and copy the file locally under dist/.
  hadolint            Check Dockerfile for hadolint compliance and other style issues.
  load-data           Load data.
  makemigrations      Perform makemigrations operation in Django.
  migrate             Perform migrate operation in Django.
  nbshell             Launch an interactive nbshell session.
  post-upgrade        Performs Nautobot common post-upgrade operations using a single entrypoint.
  pydocstyle          Run pydocstyle to validate docstring formatting adheres to NTC defined standards.
  pylint              Run pylint code analysis.
  restart             Gracefully restart all containers.
  sphinx              Rebuild Sphinx documentation on changes, with live-reload in the
                      browser.
  start               Start Nautobot and its dependencies in detached mode.
  stop                Stop Nautobot and its dependencies.
  tests               Run all tests for this plugin.
  unittest            Run Nautobot unit tests.
  unittest-coverage   Report on code test coverage as measured by 'invoke unittest'.
  vscode              Launch Visual Studio Code with the appropriate Environment variables to run in a container.
  yamllint            Run yamllint to validate formating adheres to NTC defined YAML standards.
```

### Using Docker with Invoke

A development environment can be easily started up from the root of the project using commands detailed below.

### Initialize the Local environment

Run the following commmands to initialize the local environment:

```
cp development/creds.example.env development/creds.env
invoke build
```

From here, you can either [start the local environment with a sample database](#start-the-local-environment-with-a-sample-database) or [start the local environment with an empty database](#start-the-local-environment-with-an-empty-database).

### Start the Local environment with a sample database

This is a good option for those who want to quickly spin up a working instance of Nautobot running the Version Control app. The steps below will create a Nautobot instance running Version Control and install sample data to experiment with.

```
invoke migrate
invoke load-data
invoke start
```

> `invoke load-data` can take up to 30 min to run and it will generate many warning messages which may be safely ignored.

After a few minutes, Nautobot will be available at `http://0.0.0.0:8080` 

You can connect with either of these 2 accounts:

* Login `admin` / Password `admin`
* Login `demo` / Password `nautobot`


Run the following commands to reset the local environment and load the sample dataset again:

```
invoke stop
invoke destroy
invoke migrate
invoke load-data
invoke start
```

### Start the Local environment with an empty database

This option will simply start the local dev environment. Nautobot will have an empty database:

```
invoke migrate
invoke start
```

After a few minutes, Nautobot will be available at `http://0.0.0.0:8080` 

You can connect with:

- Login `admin` / Password `admin`

Run the following commands to reset the local environment:

```
invoke stop
invoke destroy
invoke migrate
invoke start
```
