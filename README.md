# TLE

TLE is a Discord bot centered around Competitive Programming, which shows statistics and suggests problems/contests to solve.
## Installation

Firstly, clone the repository to copy the source files to your computer
```bash
git clone https://github.com/cheran-senthil/TLE
```
Then, enter the directory using 
```
cd TLE
```
Then, all dependencies need to be installed. TLE uses [Poetry](https://poetry.eustace.io/) to manage dependencies. After installing Poetry, use

```bash
poetry install
```

In order to run as a bot, TLE needs a Discord bot token. To generate one, follow the directions [here](https://github.com/reactiflux/discord-irc/wiki/Creating-a-discord-bot-&-getting-a-token). After getting the token from the discord website, run the following command to store it as an environment variable.
```
export BOT_TOKEN="<BOT_TOKEN_FROM_DISCORD_CONSOLE>"
```

Finally, in order to run the bot, you need to invite it to your Discord server as demonstrated in the instructions used to generate the bot token. When you can see the bot in your server, you can finally start it using
```
python -m tle
```

In order for the bot to start, the following roles need to exist in your Discord server, which will be set to each of your users
 - Newbie
 - Pupil
 - Specialist
 - Expert
 - Candidate Master
 - Master
 - International Master
 - Grandmaster
 - International Grandmaster
 - Legendary Grandmaster

These roles are needed even if none of the users in your server have these ranks in Codeforces

### Notes
 - In order to run admin-only commands, you need to have the `Admin` role, which needs to be created in your Discord server and assign it to yourself / other administrators
 - In order to prevent the bot suggesting an author's problems to the author, a python file needs to be run, since this can not be done through the Codeforces API, which will save the authors for specific contests to a file. To do this, run `python extra/scrape_cf_contest_writers.py`, which will generate a JSON file. 


## Usage

In order to run any bot commands, you can either ping the bot at the beginning of the command, or prefix the command with a semicolon (;), e.g. `;handle pretty`
The commands available are the following:

```
CSES:
  _updatecses Force update the CSES leaderboard
  cses        Shows compiled CSES leaderboard
Codeforces:
  gimme       Recommend a problem
  gitgud      Challenge
  gotgud      Report challenge completion
  nogud       Skip challenge
  vc          Recommend a contest
Contests:
  clist       Commands for listing contests
  ranklist    Show ranklist for given handles and/or server members
  remind      Commands for contest reminders
Graphs:
  plot        Graphs for analyzing Codeforces activity
Handles:
  gudgitters  show gudgitters
  handle      Commands that have to do with handles
​No Category:
  help        Shows this message

Type ;help command for more info on a command.
You can also type ;help category for more info on a category.
```
```
;plot

Plot various graphs. Wherever Codeforces handles are accepted it is possible to
use a server member's name instead by prefixing it with '!'.

Commands:
  centile Show percentile distribution on codeforces
  distrib Show rating distribution
  rating  Plot Codeforces rating graph
  scatter Show history of problems solved by rating.
  solved  Show histogram of solved problems on CF.

Type ;help command for more info on a command.
You can also type ;help category for more info on a category.
```
```
;handle

Change or collect information about specific handles on Codeforces

Commands:
  get    Get handle by Discord username
  list   Show all handles
  pretty Show colour handles
  remove Remove handle for Discord user (admin-only)
  set    Set Codeforces handle of a user (admin-only)

Type ;help command for more info on a command.
You can also type ;help category for more info on a category.
```

## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

Please make sure to update tests as appropriate.

## License
[MIT](https://choosealicense.com/licenses/mit/)
