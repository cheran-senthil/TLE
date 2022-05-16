# How to run the bot inside a docker container
## Motivation
Docker is a service that helps in creating isolation in the local environment. For example, if your machine runs on Windows with Python 2, you won't have to worry about running the bot that has been developed on Linux with Python 3.7  or 3.8.

The introduced `Dockerfile` uses `Ubuntu 18.04` and `Python3.8` to run the bot in an isolated environment.
### Clone the repository

```console
foo@bar:~$ git clone https://github.com/cheran-senthil/TLE
```

### Building docker image


- Build the image using the following command:
```console
foo@bar:~$ sudo docker build .
```

### Setting up Environment Variables


- Navigate to `TLE` and Create a new file `environment` from `environment.template`.

```bash
cp environment.template environment
```

Fill in appropriate variables in new "environment" file.


- open the file `environment`.
```console
export BOT_TOKEN="XXXXXXXXXXXXXXXXXXXXXXXX.XXXXXX.XXXXXXXXXXXXXXXXXXXXXXXXXXX"
export LOGGING_COG_CHANNEL_ID="XXXXXXXXXXXXXXXXXX"
export ALLOW_DUEL_SELF_REGISTER="false"
```
- Change the value of `BOT_TOKEN` with the token of the bot you created from [this step](https://github.com/reactiflux/discord-irc/wiki/Creating-a-discord-bot-&-getting-a-token).

- Replace the value of `LOGGING_COG_CHANNEL_ID` with discord [channel id](https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID-) that you want to use as a logging channel.

### Running the container


- Get the id of the image you just built from `sudo docker images` and run:

```console
foo@bar:~$ sudo docker run -v ${PWD}:/TLE -it --net host <image_id>
```

PS: use `-d` flag to run in backgroud. Then to kill backgroud container, Get the id of the container using `sudo docker ps` and run `sudo docker kill <container_id>`

### Debugging/Running Commands inside the container

To Run Commands inside the container

- Get the id of the container you just run using `sudo docker ps` and run:

```console
foo@bar:~$ sudo docker exec -it <container_id> bash
```