# perma-payments

## Up and running

1. Install Docker (https://www.docker.com/community-edition). @rebeccacremona currently prefers Docker Tookbox (https://www.docker.com/products/docker-toolbox) due to certain performance issues when automatically re-building the [LIL website](https://github.com/harvard-lil/website-static); your mileage may vary.

2. We use [Fabric](http://www.fabfile.org/) to automate common tasks. Recommended: add the following alias to your .bash_profile or similar, so that it's easier run fabric tasks inside the Docker container.
`alias dfab="docker-compose exec web fab"`

3. Clone the repo and cd inside

4. Run `docker-compose up -d` to start two containers in the background:
    -  a "db" container with a postgres database
    -  a "web" container with python, Django, and the rest of our dev environment.

5. Run `dfab run` to start the Django development server.
    -  If you are using Docker for Mac, the app will be served at http://localhost:8000
    -  If you are running Docker Machine, run `docker-machine ip` to discover the IP address of your virtualbox. The app will be served at http://#.#.#.#:8000

  Other fabric tasks (e.g. `fab test`, `fab init_db`) can similarly be run using `dfab`.

To get to a bash terminal in the running docker container, run `docker-compose exec web bash`.

To stop all running containers, run `docker-compose stop`.

To stop and remove all containers created via docker-compose up, run `docker-compose down`.

If you need to start fresh for some reason, run `docker-compose down --rmi local`.

If you change the contents of docker-compose.yml, running `docker-compose up -d` again should cause your changes to get picked up.

## Updating the Docker image

If you change the Dockerfile or if you update requirements.txt, you need to rebuild the docker image.

  -  option 1 (best for iterating locally): run `docker-compose build` or `docker-compose up -d --build`
  -  option 2 (best for when you are finished): increment the tag for perma-payments in docker-compose.yml. This ensures that an automatic rebuild is triggered for all users, when they pull in your changes.

Periodically, you might want to run docker images to see if you have accumulated a lot of cruft. Clean up manually, or try running docker-compose down --rmi local.


## The plan

Infrastructure
- A Django 1.11 application
- Using Python 3.6.1
- Using a postgres database
- Hosted on AWS, in a completely separate account from anything else
- Developed locally using Docker

The app and its relationship with Perma
- Communicates via ssl with perma.cc via a JSON api
- Uses pynacl to sign communications with perma.cc: https://pynacl.readthedocs.io/en/latest/signing/
- If/when needed, stores info in encrypted session cookies
- Has the Django admin enabled during development for our convenience, but disabled in production. (If it turns out to be necessary/convenient, we can set up something for local use on one's laptop that is hooked up to the production database.)
- Doesn't have a concept of "users" (except insofar as to enable the Django admin for development, as per above)
- Whenever possible, passes users to perma.cc or to CyberSource for views, rather than returning a polished response to the user itself
- Whenever possible, outsources business logic to perma.cc (for example, does not attempt to see whether users have exceeded their monthly allotment)
- Retains the minimum subscription/transaction information necessary for compliance in its database; does not store user data (name, address, email address, etc.); associates transactions/subscriptions with a perma user id (or org id, or registrar id... TBD depending on pricing model) for easy retrieval (perma.cc will not itself store a record of transactions/subscription keys)

Communication with CyberSource
- passes the user to CyberSource via a redirect
(more to come here)
