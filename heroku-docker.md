# How to push docker-image and deploy on Heroku
## Reason to do it
Deploying docker image via Heroku is a faster method and requires less effort in deploying the whole project on Heroku.

## Prerequisites
- Already know how to deploy the bot on Discord. 

## Create Environment file
- Create a file `.env` from `environment.template` file.

## Build Docker Image
Follow the steps written in `Docker.md` file or use the alternative method. 
```bash
docker-compose up --build -d
```
 
Now check if your docker image is working or not. To check the logs, do:
```bash 
docker-compose logs -f
```
press `Ctrl+C` to get out of it

Do, docker ps or docker images to get the name of docker image.
```
CONTAINER ID   IMAGE                   COMMAND   CREATED   STATUS    PORTS     NAMES
123123         <docker-image name_1>              latest                    <docker-image name>
```
- Open Heroku now and create an app or use heroku cli for it.
```bash
heroku create <heroku app-name>
```
- Push the docker image onto heroku
```bash
 heroku container:push <docker-image name> -a <heroku app name> 
 ```

 - Release the docker image
```bash
 heroku container:release <docker-image name> -a <heroku app name> 
 ```

 - Go on heroku dashboard and switch on by going to Resources