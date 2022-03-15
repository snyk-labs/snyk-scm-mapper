# This is a multistage container builder for poetry projects

FROM python:3.9-slim AS requirements

ENV PYTHONDONTWRITEBYTECODE 1

# Add jq and curl

RUN apt-get -qq update && apt-get -qq install --no-install-recommends -y jq curl

RUN apt-get -qq clean

# step one is to create a container with poetry on it
RUN python -m pip install --quiet -U pip poetry

COPY scripts/install_snyk_tools.sh ./install_snyk_tools.sh
RUN /bin/bash ./install_snyk_tools.sh

WORKDIR /src

COPY pyproject.toml pyproject.toml
COPY poetry.lock poetry.lock

# now that we have poetry, we export the requirements file
RUN poetry export --quiet --no-interaction -f requirements.txt --without-hashes -o /src/requirements.txt

# now we create our final container, runtime
FROM python:3.9-slim AS runtime

WORKDIR /app

COPY --from=requirements /usr/local/bin/snyk /usr/local/bin/snyk
COPY --from=requirements /usr/local/bin/snyk-api-import /usr/local/bin/snyk-api-import

# copy stuff from this repo into the /app directory of the container
COPY snyk_sync/ /app/snyk_sync/

# now we use multistage containers to then copy the requirements from the other container
COPY --from=requirements /src/requirements.txt .

# now we're *just* deploying the needed packages for whatever was in the poetry setup
RUN python -m pip install --quiet -U pip
RUN pip install -r requirements.txt

COPY scripts/entrypoint.sh /usr/local/bin/
COPY scripts/entrypoint-api-import.sh /usr/local/bin/
COPY scripts/rate_limits.sh /usr/local/bin/
COPY scripts/rate_limit_debug.py /usr/local/bin/

RUN chmod +x /usr/local/bin/*

WORKDIR /runtime

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]