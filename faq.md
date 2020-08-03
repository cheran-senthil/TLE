# TLE on Heroku

TLE cannot be fully functional when deployed on heroku due to its [ephemeral filesystem](https://devcenter.heroku.com/articles/dynos#ephemeral-filesystem) which does not preserve TLE's on-disk database
