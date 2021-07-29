# How to push docker-image and deploy on Heroku
## Reason to do it
Deploying docker image via Heroku is a faster method than deploying the whole project on Heroku and requires less effort.

## Prior Knowledge
- Deploy the bot on Discord. 

## Create Environment file
- Create a copy of file `environment.template` and name it `.env` file.
- Replace `xxxxxxxxx.xxxxxxxxx` with your credentials.

## Build Docker Image
Follow the steps written in the `Docker.md` file or use the alternative method listed below. 
```bash
docker-compose up --build -d
```
 
To check if your docker image is running or not:
```bash 
docker-compose logs -f
```
this will print the log
press `Ctrl+C` to get out of it

run `docker ps` or docker images to get the name of docker image, which will look like this.
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

 - Open heroku dashboard, then open the Resources tab and turn on the worker.
