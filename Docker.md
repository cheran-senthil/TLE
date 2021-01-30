# How to run the bot inside a docker container
## Motivation
Docker is a service that helps in creating isolation in the local environment. For example, if your machine runs on Windows with Python 2, you won't have to worry about running the bot that has been developed on Linux with Python 3.7  or 3.8.

The introduced `Dockerfile` uses `Ubuntu 18.04` and `Python3.8` to run the bot in an isolated environment.
### Clone the repository

```console
foo@bar:~$ git clone https://github.com/cheran-senthil/TLE
```

### Building docker images

- Navigate to `TLE` and open the file `environment.template`.
```console
export BOT_TOKEN="XXXXXXXXXXXXXXXXXXXXXXXX.XXXXXX.XXXXXXXXXXXXXXXXXXXXXXXXXXX"
export LOGGING_COG_CHANNEL_ID="XXXXXXXXXXXXXXXXXX"
export ALLOW_DUEL_SELF_REGISTER="false"
```
- Change the value of `BOT_TOKEN` with the token of the bot you created from [this step](https://github.com/reactiflux/discord-irc/wiki/Creating-a-discord-bot-&-getting-a-token).

- Replace the value of `LOGGING_COG_CHANNEL_ID` with discord [channel id](https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID-) that you want to use as a logging channel.

- Build the image using the following command:
```console
foo@bar:~$ sudo docker build .
```

### Running the container
- Get the id of the image you just built from `sudo docker images` and run it inside a container:
```console
foo@bar:~$ sudo docker run image_id
```
