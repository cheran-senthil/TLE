# TLE

TLE is a Discord bot centered around Competitive Programming, which shows statistics and suggests problems/contests to solve.

## Features
The features of the bot is split into a number of cogs, each handling their own set of commands.

### Codeforces cogs
- Codeforces: Commands that can recommend problems or contests to users, taking their rating into account.
- Contests: Shows details of upcoming/running contests.
- Graphs: Plots various data gathered from Codeforces. For example rating distributions and user problem statistics.
- Handles: Gets or sets information about a specific user's Codeforces handle, or shows list of Codeforces handles.

### CSES cog
- CSES: Commands related to the [CSES problemset](https://cses.fi/problemset/), such as showing leaderboards.

### Other cogs
- Starboard: Commands related to the starboard, which adds messages to a specific channel when enough users react with a `:star:`
- CacheControl: Commands related to data caching.

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

In order for the bot to function properly, the following roles need to exist in your Discord server, which will be set to each of your users
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
In order to find the commands which are available, you can execute the command `;help`. This will bring a list of commands / groups of commands which are available to use at the moment. To get more details about a specific command, you can type `;help <command-name>`

## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

Please make sure to update tests as appropriate.

## License
[MIT](https://choosealicense.com/licenses/mit/)
